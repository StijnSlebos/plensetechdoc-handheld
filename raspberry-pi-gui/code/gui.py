#!/usr/bin/env python3
# flake8: noqa: E402
"""
GUI for combined Force-Deflection and NanoVNA measurements.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime as dt
import json
import logging
import traceback
import math
import pandas as pd
import time
import csv
import matplotlib.dates as mdates
import numpy as np
import matplotlib.pyplot as plt

# Ensure local modules are on the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from motor_test import MeasurementProtocol, OUTPUT_DIR
from nanovna import NanoVnaController
from motor_test import plot_force_deflection
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from diameter_extractor import DiameterExtractor
from arduino_force_controller import ArduinoErrorType

class MeasurementApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Measurement Controller")
        # Set window size and make it non-resizable for touchscreen
        # self.geometry("1280x720")
        self.geometry("1024x500")
        self.resizable(False, False)
        self.option_add('*Dialog.msg.font', 'Arial 20') # Make message boxes larger

        # Make the window full screen
        self.attributes('-fullscreen', True)

        self.protocol = None
        self.vna_ctrl = None
        self.measure_thread = None
        self.stop_event = threading.Event()
        self.metadata_file = os.path.join(OUTPUT_DIR, "metadata.json")
        self.diameter_extractor = DiameterExtractor()
        
        # Calibration state
        self.is_calibrated = False
        self.zero_offset_mm = 0.0  # Calculated during calibration

        # Error tracking
        self.current_errors = []
        self.last_arduino_state = None

        # Matplotlib figure and axes
        self.fig = Figure()
        self.ax_force, self.ax_s21 = self.fig.subplots(1, 2)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)

        # —— Logging Setup ——
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s - %(levelname)s - ""%(message)s", "%Y-%m-%d %H:%M:%S"
        )
        log_file_handler = logging.FileHandler("gui.log")
        log_file_handler.setFormatter(fmt)
        self.logger.addHandler(log_file_handler)
        # Also log to console for immediate feedback during development
        self.logger.addHandler(logging.StreamHandler())

        # Configure ttk styles for fonts
        self.style = ttk.Style()
        self.style.configure("TLabel", font=("Arial", 16))
        self.style.configure("TButton", font=("Arial", 16))
        self.style.configure("TEntry", font=("Arial", 16))
        self.style.configure("TCombobox", font=("Arial", 16))
        
        # Error status styles
        self.style.configure("Error.TLabel", font=("Arial", 12), foreground="red")
        self.style.configure("Warning.TLabel", font=("Arial", 12), foreground="orange")
        self.style.configure("Success.TLabel", font=("Arial", 12), foreground="green")

        self._clear_log_files()
        # self._cleanup_serial_connections()  # Temporarily disabled - might interfere with connection
        self._load_input_settings()
        # Remove the old zero offset notice - we'll use calibration instead
        self._build_ui()
        self._update_last_measurement_label()
        
        # Show calibration notice
        messagebox.showinfo(
            "Calibration Required",
            "Please place a 12.05mm PMMA cylinder in the sensor and click 'Calibrate' before taking measurements."
        )

    def _clear_log_files(self):
        log_files = ["gui.log", "nanovna.log", "error.log"]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for log_file_name in log_files:
            log_path = os.path.join(script_dir, log_file_name)
            if os.path.exists(log_path):
                try:
                    with open(log_path, "w") as f:
                        f.truncate(0)
                    # Note: We can't use self.logger here as it's not yet fully configured
                except Exception as e:
                    print(f"Error clearing {log_file_name}: {e}") # Use print for early errors

    def _cleanup_serial_connections(self):
        """Clean up any stale serial connections that might be blocking."""
        import serial.tools.list_ports
        
        self.logger.info("Cleaning up serial connections...")
        
        # List all available serial ports
        ports = serial.tools.list_ports.comports()
        arduino_ports = []
        
        for port in ports:
            # Look for Arduino-like devices (common VID/PID combinations)
            if (port.vid and port.pid and 
                (port.vid in [0x2341, 0x1A86, 0x0403] or  # Arduino, CH340, FTDI
                 'arduino' in (port.description or "").lower() or
                 'ch340' in (port.description or "").lower() or
                 'usb serial' in (port.description or "").lower())):
                arduino_ports.append(port.device)
            # Also check for common Linux Arduino ports
            elif port.device.startswith('/dev/ttyACM') or port.device.startswith('/dev/ttyUSB'):
                arduino_ports.append(port.device)
        
        # Try to reset each potential Arduino port
        for port_name in arduino_ports:
            try:
                self.logger.info(f"Attempting to reset port: {port_name}")
                
                # Open and immediately close to reset the connection
                ser = serial.Serial(port_name, 115200, timeout=0.5)
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                ser.close()
                
                self.logger.info(f"Successfully reset port: {port_name}")
                
            except Exception as e:
                self.logger.warning(f"Could not reset port {port_name}: {e}")
        
        # Small delay to let ports settle
        import time
        time.sleep(1)

    def _load_input_settings(self):
        """Load input settings from metadata.json input_settings"""
        self.zero_distance_mm = 13.45 # Default value, updated by user's last edit
        try:
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r') as f:
                    metadata = json.load(f)
                input_settings = metadata.get('input_settings', {})
                self.zero_distance_mm = float(input_settings.get('zero_distance_mm', self.zero_distance_mm))
                self.logger.info(f"Loaded zero_distance_mm: {self.zero_distance_mm}")
            else:
                self.logger.warning(f"Metadata file not found: {self.metadata_file}")
        except Exception as e:
            self.logger.exception(f"Error loading input settings: {e}")

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding="1")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top frame for inputs and actions - make more compact
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 2))

        # --- Inputs on the left ---
        inputs_container = ttk.Frame(top_frame)
        inputs_container.pack(side=tk.LEFT, anchor=tk.N)

        # Node Number - more compact
        node_frame = ttk.Frame(inputs_container)
        node_frame.pack(side=tk.LEFT, padx=(0, 10), expand=False, fill=tk.BOTH)
        ttk.Label(node_frame, text="Node #", font=("Arial", 14)).pack(pady=(0,0))
        
        node_input_frame = ttk.Frame(node_frame)
        node_input_frame.pack(pady=(0,0), padx=(5,10), fill=tk.X)
        ttk.Button(node_input_frame, text="-", width=2, command=self._decrement_node, padding=[5, 1]).pack(side=tk.LEFT, padx=(0,1), pady=0)
        self.node_var = tk.StringVar(value="1")
        node_entry = ttk.Entry(node_input_frame, textvariable=self.node_var, width=4, justify='center', font=("Arial", 14))
        node_entry.pack(side=tk.LEFT, padx=(0,1), pady=0, expand=True, fill=tk.X)
        ttk.Button(node_input_frame, text="+", width=2, command=self._increment_node, padding=[5, 1]).pack(side=tk.LEFT, pady=0)

        # Plant Number - more compact
        plant_frame = ttk.Frame(inputs_container)
        plant_frame.pack(side=tk.LEFT, padx=(5, 10), expand=False, fill=tk.BOTH)
        ttk.Label(plant_frame, text="Plant #", font=("Arial", 14)).pack(pady=(0,0))
        
        plant_input_frame = ttk.Frame(plant_frame)
        plant_input_frame.pack(pady=(0,0), fill=tk.X)
        ttk.Button(plant_input_frame, text="-", width=2, command=self._decrement_plant, padding=[5, 1]).pack(side=tk.LEFT, padx=(0,1), pady=0)
        self.plant_var = tk.StringVar(value="1")
        plant_entry = ttk.Entry(plant_input_frame, textvariable=self.plant_var, width=4, justify='center', font=("Arial", 14))
        plant_entry.pack(side=tk.LEFT, padx=(0,1), pady=0, expand=True, fill=tk.X)
        ttk.Button(plant_input_frame, text="+", width=2, command=self._increment_plant, padding=[5, 1]).pack(side=tk.LEFT, pady=0)

        # --- Actions on the right ---
        actions_container = ttk.Frame(top_frame)
        actions_container.pack(side=tk.LEFT, padx=(15, 0), fill=tk.Y, expand=False)

        buttons_frame = ttk.Frame(actions_container)
        buttons_frame.pack(fill=tk.X) 
        
        self.start_single_btn = ttk.Button(buttons_frame, text="Single", command=self._start_single, padding=[12, 8])
        self.start_single_btn.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X) 
        
        self.start_reps_btn = ttk.Button(buttons_frame, text="3 Reps", command=self._start_multiple_reps, padding=[12, 8])
        self.start_reps_btn.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X)

        self.status_var = tk.StringVar(value="Last measurement: None")
        ttk.Label(buttons_frame, textvariable=self.status_var, font=("Arial", 12)).pack(side=tk.LEFT, padx=(10, 0), pady=0)

        # --- Error Status Display ---
        error_frame = ttk.Frame(main_frame)
        error_frame.pack(fill=tk.X, pady=(1, 1))
        
        ttk.Label(error_frame, text="System Status:", font=("Arial", 12)).pack(side=tk.LEFT, padx=(5, 5))
        self.error_status_var = tk.StringVar(value="Ready")
        self.error_status_label = ttk.Label(error_frame, textvariable=self.error_status_var, style="Success.TLabel")
        self.error_status_label.pack(side=tk.LEFT, padx=(0, 10))
        
        # Error details button
        self.error_details_btn = ttk.Button(error_frame, text="Details", command=self._show_error_details, 
                                           padding=[4, 2], state="disabled")
        self.error_details_btn.pack(side=tk.LEFT, padx=(5, 0))

        # --- Plots - remove figsize to let it auto-size ---
        self.fig = Figure()
        self.ax_force, self.ax_s21 = self.fig.subplots(1, 2)
        self.canvas = FigureCanvasTkAgg(self.fig, master=main_frame)
        self.canvas.get_tk_widget().pack(fill=tk.X, pady=(1, 1))
        self.canvas.get_tk_widget().config(height=350)  # Reduced height to make room for error status
        self._create_dummy_plot()

        # --- Bottom Buttons - ensure they're always visible ---
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(1, 1))
        
        # Left side buttons
        left_buttons = ttk.Frame(bottom_frame)
        left_buttons.pack(side=tk.LEFT)
        ttk.Button(left_buttons, text="Remove", command=self._remove_previous_measurement, padding=[8, 3]).pack(side=tk.LEFT, padx=2)
        self.calibrate_btn = ttk.Button(left_buttons, text="Calibrate", command=self._calibrate, padding=[8, 3])
        self.calibrate_btn.pack(side=tk.LEFT, padx=2)
        self.stop_btn = ttk.Button(left_buttons, text="Stop", state="disabled", command=self._stop, padding=[8, 3])
        self.stop_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(left_buttons, text="Reset Serial", command=self._reset_serial, padding=[8, 3]).pack(side=tk.LEFT, padx=2)
        
        # Right side buttons
        right_buttons = ttk.Frame(bottom_frame)
        right_buttons.pack(side=tk.RIGHT)
        ttk.Button(right_buttons, text="Exit", command=self._exit_app, padding=[8, 3]).pack(side=tk.RIGHT, padx=2)
        ttk.Button(right_buttons, text="Restart", command=self._restart_app, padding=[8, 3]).pack(side=tk.RIGHT, padx=2)
        
        # Initially disable measurement buttons until calibration is done
        self._set_measurement_buttons_state("disabled")

    def _increment_var(self, var, max_val=None):
        try:
            val = int(var.get())
            if max_val is None or val < max_val:
                var.set(str(val + 1))
        except ValueError:
            var.set("1")

    def _decrement_var(self, var, min_val=1):
        try:
            val = int(var.get())
            if val > min_val:
                var.set(str(val - 1))
        except ValueError:
            var.set("1")

    def _increment_node(self): self._increment_var(self.node_var)
    def _decrement_node(self): self._decrement_var(self.node_var)
    def _increment_plant(self): self._increment_var(self.plant_var, 56)
    def _decrement_plant(self): self._decrement_var(self.plant_var)

    def _update_last_measurement_label(self):
        try:
            metadata = {}
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r') as f:
                    metadata = json.load(f)
            log = metadata.get('measurement_log', [])
            if not log:
                self.status_var.set("Last measurement: None")
                return

            last_entry = log[-1]['us_properties']
            ts_iso = last_entry['timestamp']
            timestamp = dt.fromisoformat(ts_iso).strftime("%Y%m%d_%H%M%S")
            s2p = os.path.join(OUTPUT_DIR, f"sweep_{timestamp}.s2p")
            csv = os.path.join(OUTPUT_DIR, f"fd_{timestamp}.csv")
            s2p_size = f"{os.path.getsize(s2p)/1024:.1f}KB" if os.path.exists(s2p) else "N/A"
            csv_size = f"{os.path.getsize(csv)/1024:.1f}KB" if os.path.exists(csv) else "N/A"
            self.status_var.set(f"Last: {timestamp}, s2p: {s2p_size}, csv: {csv_size}")
        except Exception:
            self.status_var.set("Last measurement: Error reading logs")
            self.logger.exception("Error updating last measurement label")

    def _remove_previous_measurement(self):
        if not messagebox.askyesno("Confirm", "Remove last measurement and its files?"):
            return
        try:
            metadata = {}
            if not os.path.exists(self.metadata_file):
                messagebox.showinfo("Info", "No metadata file. Nothing to remove.")
                return
            with open(self.metadata_file, 'r') as f:
                metadata = json.load(f)
            log = metadata.get('measurement_log', [])
            if not log:
                messagebox.showinfo("Info", "Log is empty. Nothing to remove.")
                return

            last_entry = log.pop()['us_properties']
            ts_iso = last_entry['timestamp']
            timestamp = dt.fromisoformat(ts_iso).strftime("%Y%m%d_%H%M%S")
            
            s2p = os.path.join(OUTPUT_DIR, f"sweep_{timestamp}.s2p")
            csv = os.path.join(OUTPUT_DIR, f"fd_{timestamp}.csv")
            if os.path.exists(s2p): os.remove(s2p)
            if os.path.exists(csv): os.remove(csv)

            metadata['measurement_log'] = log
            with open(self.metadata_file, 'w') as f:
                json.dump(metadata, f, indent=4)
                
            messagebox.showinfo("Success", f"Removed measurement: {timestamp}")
            self._update_last_measurement_label()
            self.fig.clear()
            self.canvas.draw()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to remove last measurement: {e}")
            self.logger.exception("Error removing last measurement")

    def _restart_app(self):
        self.destroy()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def _calibrate(self):
        """Perform calibration using a 12.05mm PMMA cylinder to determine zero offset."""
        if not messagebox.askyesno("Calibration", 
                                   "Is the 12.05mm PMMA cylinder properly positioned in the sensor?"):
            return
            
        self.calibrate_btn.config(state="disabled")
        self.calibrate_btn.config(text="Calibrating...")
        
        # Run calibration in a thread to avoid blocking the UI
        self.measure_thread = threading.Thread(
            target=self._run_calibration, daemon=True
        )
        self.measure_thread.start()
    
    def _run_calibration(self):
        """Run the calibration measurement sequence."""
        self.stop_event.clear()
        
        try:
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            fd_csv = os.path.join(OUTPUT_DIR, f"cal_{timestamp}.csv")
            s2p_file = os.path.join(OUTPUT_DIR, f"sweep_cal_{timestamp}.s2p")
            
            self.logger.info("Starting calibration measurement...")
            
            # Initialize VNA
            self.logger.info("Configuring NanoVNA...")
            self.vna_ctrl = NanoVnaController(
                calibration_filename=os.path.join(os.path.dirname(SCRIPT_DIR), "calibration", "calibration_10-500khz.cal"),
                sweep_range=(10e3, 500e3, 256),
                hub_location="1-1.2", hub_port=1, output_dir=OUTPUT_DIR
            )

            vna_success = False
            def run_vna():
                nonlocal vna_success
                self.logger.info("NanoVNA calibration sweep running...")
                if self.vna_ctrl.sweep_and_save(timestamp=f"cal_{timestamp}"):
                    vna_success = True
                    self.logger.info("NanoVNA calibration sweep done.")
                else:
                    self.logger.error("NanoVNA calibration sweep failed.")

            # Setup and run force-deflection protocol for calibration
            self.logger.info("Creating MeasurementProtocol for calibration...")
            self.protocol = MeasurementProtocol(csv_filename=fd_csv, on_measurement_start=run_vna, stop_event=self.stop_event)
            self.logger.info("MeasurementProtocol created successfully, starting force-deflection run...")
            
            self.protocol.run()  # This is blocking until FD is done
            self.logger.info("Force-deflection protocol completed.")

            # Wait for VNA thread to finish if it started
            if self.protocol._vna_thread:
                self.protocol._vna_thread.join()
            
            if self.stop_event.is_set():
                self.logger.warning("Calibration stopped by user.")
                self._cleanup_failed_measurement(fd_csv)
                if os.path.exists(s2p_file): os.remove(s2p_file)
                self.after(0, self._calibration_failed, "Calibration cancelled by user")
                return

            # Plotting function now returns fig, axes, and dataframe - call AFTER data is written
            _, _, force_data_df = plot_force_deflection(
                csv_filename=fd_csv, 
                zero_distance_mm=self.zero_distance_mm,
                ax_force=self.ax_force,
                ax_s21=self.ax_s21
            )

            if force_data_df is None or force_data_df.empty:
                self.logger.error("Calibration failed: No force-deflection data.")
                self.after(0, self._calibration_failed, "No force-deflection data recorded during calibration.")
                return

            # Handle any errors that occurred during calibration
            self.after(0, lambda: self._handle_measurement_errors(self.protocol))
            
            if vna_success:
                # Calculate diameter using current extractor (before calibration)
                calculated_diameter, flags, flaginfo_list = \
                    self.diameter_extractor.diameter_from_force_data(force_data_df)
                
                flaginfo = {} # Initialize as empty dict
                if flaginfo_list:
                    flaginfo = flaginfo_list[0] # Extract the dictionary from the list

                # Get the flush index for calibration
                _, flush_idx, _ = self.diameter_extractor.get_step_flush_indices(force_data_df)

                # Set calibration using known diameter and measured flush index
                actual_diameter_mm = 12.05
                self.diameter_extractor.set_calibration(actual_diameter_mm, flush_idx)
                self.zero_offset_mm = self.diameter_extractor.zero_offset_mm
                
                # Recalculate diameter with new calibration
                calculated_diameter_calibrated, _, _ = \
                    self.diameter_extractor.diameter_from_force_data(force_data_df)
                
                self.logger.info(f"Calibration complete. Initial diameter: {calculated_diameter:.3f}mm, "
                               f"Calibrated diameter: {calculated_diameter_calibrated:.3f}mm, "
                               f"Actual: {actual_diameter_mm}mm, Zero offset: {self.zero_offset_mm:.3f}mm")
                
                # Save calibration as a measurement entry
                self._update_metadata(f"cal_{timestamp}", "0", None, 1, 
                                    self.zero_distance_mm, self.zero_offset_mm, 
                                    "calibration", calculated_diameter_calibrated, flags, flaginfo)
                
                # Show power spectrum in the plot
                self._show_calibration_results(calculated_diameter_calibrated, actual_diameter_mm, s2p_file)
                
                # Check if calibration had critical errors
                if self.protocol.get_error_summary() and self.protocol.get_error_summary().get('critical_error'):
                    self.after(0, self._calibration_failed, "Critical errors occurred during calibration")
                    return
                
                # Mark as calibrated and enable measurement buttons
                self.is_calibrated = True
                self.after(0, self._calibration_complete)
                
            else:
                self.logger.error("Calibration failed: no .s2p file created.")
                self._cleanup_failed_measurement(fd_csv)
                self.after(0, self._calibration_failed, "VNA sweep failed during calibration")

        except ConnectionError as ce:
            self.logger.exception("Connection error during calibration.")
            # Try to reset serial connections automatically
            try:
                self._cleanup_serial_connections()
            except Exception:
                pass
            self.after(0, self._calibration_failed, "Connection error. Please check Arduino connection and try again.")
        except Exception as e:
            self.logger.exception("An error occurred during calibration.")
            # Try to reset serial connections on any error
            try:
                self._cleanup_serial_connections()
            except Exception:
                pass
            self.after(0, self._calibration_failed, f"An unexpected error occurred: {e}")
        
        finally:
            if self.protocol:
                self.protocol.close()
    
    def _show_calibration_results(self, calculated_diameter, actual_diameter, s2p_file):
        """Update the plot to show calibration results including power spectrum."""
        # Update force plot title with calibration info
        title_text = f"Calibration: Calc: {calculated_diameter:.2f}mm, Actual: {actual_diameter:.2f}mm, Offset: {self.zero_offset_mm:.3f}mm"
        self.ax_force.set_title(title_text, fontsize=10)
        
        # Add power spectrum plot if S2P file exists
        # Clear the s21 axis before plotting new data
        self.ax_s21.clear()
        if os.path.exists(s2p_file):
            freq, s21_db = [], []
            try:
                with open(s2p_file, 'r') as f:
                    for line in f:
                        if line.strip() and not line.startswith(('!', '#')):
                            parts = line.split()
                            if len(parts) >= 5:
                                f_val = float(parts[0])
                                s21_real = float(parts[3])
                                s21_imag = float(parts[4])
                                s21 = max(
                                    (s21_real**2 + s21_imag**2)**0.5, 1e-12
                                )
                                freq.append(f_val / 1000)  # to kHz
                                s21_db.append(20 * math.log10(s21))
                if freq and s21_db:
                    self.ax_s21.plot(freq, s21_db, marker='.', linestyle='-', color='red')
                    self.ax_s21.set_xlabel("Frequency (kHz)", fontsize=9)
                    self.ax_s21.set_ylabel("S21 (dB)", fontsize=9)
                    self.ax_s21.set_title("Calibration Power Spectrum (S21)", fontsize=10)
                    self.ax_s21.grid(True)
                    self.ax_s21.tick_params(labelsize=8)
            except (ValueError, IndexError):
                pass  # Ignore malformed lines
        else:
            self.ax_s21.text(0.5, 0.5, "s2p file not found\nor has no data", ha="center",
                             va="center", transform=self.ax_s21.transAxes, fontsize=10)

        self.fig.tight_layout(pad=0.5)
        self.after(0, self._update_plot)
    
    def _calibration_complete(self):
        """Handle successful calibration completion."""
        self.calibrate_btn.config(state="normal")
        self.calibrate_btn.config(text="Re-calibrate")
        self._set_measurement_buttons_state("normal")
        messagebox.showinfo("Calibration Complete", 
                          f"Calibration successful!\nZero offset: {self.zero_offset_mm:.3f}mm\n"
                          f"Measurement buttons are now enabled.")
    
    def _calibration_failed(self, error_msg):
        """Handle calibration failure."""
        self.calibrate_btn.config(state="normal")
        self.calibrate_btn.config(text="Calibrate")
        messagebox.showerror("Calibration Failed", error_msg)

    def _validate_inputs(self):
        try:
            int(self.node_var.get())
            int(self.plant_var.get())
            return True
        except ValueError:
            messagebox.showerror("Error", "Node and Plant must be valid numbers.")
            return False

    def _toggle_controls(self, state):
        self._set_measurement_buttons_state(state)

    def _start_single(self):
        self._run_sequence_wrapper(num_repetitions=1)

    def _start_multiple_reps(self):
        self._run_sequence_wrapper(num_repetitions=3)
        
    def _run_sequence_wrapper(self, num_repetitions):
        if not self._validate_inputs():
            return
        if not self.is_calibrated:
            messagebox.showerror("Calibration Required", 
                               "Please complete calibration before taking measurements.")
            return
        self._toggle_controls("disabled")
        self.measure_thread = threading.Thread(
            target=self._run_sequence, args=(num_repetitions,), daemon=True
        )
        self.measure_thread.start()

    def _stop(self):
        self.stop_event.set()
    
    def _reset_serial(self):
        """Reset serial connections manually - useful when things get stuck."""
        if self.measure_thread and self.measure_thread.is_alive():
            messagebox.showwarning("Reset Serial", "Cannot reset serial while measurement is running. Stop measurement first.")
            return
            
        self.logger.info("Manual serial reset requested")
        try:
            # Store calibration state before reset
            was_calibrated = self.is_calibrated
            
            # Stop any active protocol
            if self.protocol:
                self.protocol.close()
                self.protocol = None
            
            # Clean up serial connections
            self._cleanup_serial_connections()
            
            # Clear error status
            self._update_error_status("Serial connections reset - ready for new connection")
            self.current_errors.clear()
            
            # Show appropriate message based on calibration state
            if was_calibrated:
                messagebox.showinfo("Reset Serial", 
                                  f"Serial connections have been reset.\n"
                                  f"Calibration preserved (zero offset: {self.zero_offset_mm:.3f}mm).\n"
                                  f"Measurements can continue without recalibration.")
                self.logger.info(f"Serial reset completed. Calibration preserved: zero_offset_mm={self.zero_offset_mm:.3f}")
            else:
                messagebox.showinfo("Reset Serial", "Serial connections have been reset. Please calibrate before taking measurements.")
            
            # Preserve calibration state - only reset if never calibrated
            if not was_calibrated:
                self.is_calibrated = False
                self.calibrate_btn.config(text="Calibrate")
                self._set_measurement_buttons_state("disabled")
            else:
                # Keep calibration state and measurement buttons enabled
                self.is_calibrated = True
                self.calibrate_btn.config(text="Re-calibrate")
                self._set_measurement_buttons_state("normal")
            
        except Exception as e:
            self.logger.exception("Error during serial reset")
            self._update_error_status("Error during serial reset", "error")
            messagebox.showerror("Reset Serial", f"Error resetting serial connections: {e}")

    def _reset_serial_silent(self):
        """Reset serial connections silently after successful measurement - no user dialogs."""
        try:
            # Store calibration state before reset
            was_calibrated = self.is_calibrated
            
            # Clean up serial connections
            self._cleanup_serial_connections()
            
            # Log the activity
            if was_calibrated:
                self.logger.info(f"Post-measurement serial reset completed. Calibration preserved: zero_offset_mm={self.zero_offset_mm:.3f}")
            else:
                self.logger.info("Post-measurement serial reset completed.")
            
            # Preserve calibration state - only reset if never calibrated
            if not was_calibrated:
                self.is_calibrated = False
                self.calibrate_btn.config(text="Calibrate")
                self._set_measurement_buttons_state("disabled")
            else:
                # Keep calibration state and measurement buttons enabled
                self.is_calibrated = True
                self.calibrate_btn.config(text="Re-calibrate")
                self._set_measurement_buttons_state("normal")
            
        except Exception as e:
            self.logger.exception("Error during silent serial reset")
            # Don't show error dialog for silent reset - just log it

    def _auto_recovery_attempt(self, error_type):
        """Attempt automatic recovery based on error type"""
        self.logger.info(f"Attempting automatic recovery for error: {error_type}")
        
        if error_type == ArduinoErrorType.FORCE_SENSOR_ERROR:
            # Try serial reset for sensor issues
            self._reset_serial()
            return True
        elif error_type == ArduinoErrorType.I2C_TIMEOUT:
            # For I2C timeouts, suggest checking sensor connections
            self._update_error_status("I2C sensor timeout - check sensor connections", "warning", has_details=True)
            return False
        
        return False

    def _cleanup_failed_measurement(self, csv_file):
        if os.path.exists(csv_file):
            try:
                os.remove(csv_file)
                self.logger.info(f"Deleted failed measurement CSV: {csv_file}")
            except Exception:
                self.logger.exception(f"Error deleting CSV file {csv_file}")
    
    def _get_next_repetition(self, object_id):
        max_rep = 0
        try:
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r') as f:
                    metadata = json.load(f)
                for measurement in metadata.get('measurement_log', []):
                    props = measurement.get('us_properties', {})
                    if props.get('object_id') == object_id:
                        rep = int(props.get('repetition', 0))
                        max_rep = max(max_rep, rep)
        except (IOError, json.JSONDecodeError):
            self.logger.exception("Could not read metadata to get repetition count.")
        return max_rep + 1

    def _run_sequence(self, num_repetitions):
        self.stop_event.clear()
        
        for i in range(num_repetitions):
            if self.stop_event.is_set():
                self.logger.info("Measurement sequence stopped by user.")
                break
                
            repetition_num = self._get_next_repetition(self.plant_var.get())
            self.logger.info(f"Starting measurement {i+1}/{num_repetitions} (Repetition #{repetition_num})")

            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            node_number = self.node_var.get()
            object_id = self.plant_var.get()

            fd_csv = os.path.join(OUTPUT_DIR, f"fd_{timestamp}.csv")
            s2p_file = os.path.join(OUTPUT_DIR, f"sweep_{timestamp}.s2p")
            
            # Initialize variables for finally block
            vna_success = False
            has_critical_error = False
            
            try:
                # Initialize VNA
                self.logger.info("Configuring NanoVNA...")
                self.vna_ctrl = NanoVnaController(
                    calibration_filename=os.path.join(os.path.dirname(SCRIPT_DIR), "calibration", "calibration_10-500khz.cal"),
                    sweep_range=(10e3, 500e3, 256),
                    hub_location="1-1.2", hub_port=1, output_dir=OUTPUT_DIR
                )

                vna_success = False
                def run_vna():
                    nonlocal vna_success
                    self.logger.info("NanoVNA sweep running...")
                    if self.vna_ctrl.sweep_and_save(timestamp=timestamp):
                        vna_success = True
                        self.logger.info("NanoVNA sweep done.")
                    else:
                        self.logger.error("NanoVNA sweep failed.")

                # Setup and run force-deflection protocol
                self.protocol = MeasurementProtocol(csv_filename=fd_csv, on_measurement_start=run_vna, stop_event=self.stop_event)
                self.logger.info("Running force-deflection...\n") # Added newline for better logging output
                self.protocol.run() # This is blocking until FD is done

                # Wait for VNA thread to finish if it started
                if self.protocol._vna_thread:
                    self.protocol._vna_thread.join()
                
                if self.stop_event.is_set():
                    self.logger.warning("Stop detected, cleaning up measurement files.")
                    self._cleanup_failed_measurement(fd_csv)
                    if os.path.exists(s2p_file): os.remove(s2p_file)
                    continue # This continue applies to the for loop.

                # Plotting function now returns fig, axes, and dataframe - call AFTER data is written
                _, _, force_data_df = plot_force_deflection(
                    csv_filename=fd_csv, 
                    zero_distance_mm=self.zero_distance_mm,
                    ax_force=self.ax_force,
                    ax_s21=self.ax_s21
                )

                if force_data_df is None or force_data_df.empty:
                    self.logger.error("Measurement failed: No force-deflection data.")
                    self.after(0, lambda: messagebox.showerror("Measurement Failed", "No force-deflection data recorded. CSV file deleted."))
                    self._cleanup_failed_measurement(fd_csv)
                    return

                # Handle measurement errors first
                self.after(0, lambda: self._handle_measurement_errors(self.protocol))
                
                # Check if measurement had critical errors before proceeding
                error_summary = self.protocol.get_error_summary()
                has_critical_error = error_summary and error_summary.get('critical_error', False)
                
                if vna_success and not has_critical_error:
                    self.logger.info("Measurement successful.")
                    
                    # Extract diameter and flags AFTER force_data_df is available
                    calculated_diameter, flags, flaginfo_list = \
                        self.diameter_extractor.diameter_from_force_data(force_data_df)

                    flaginfo = {} # Initialize as empty dict
                    if flaginfo_list:
                        flaginfo = flaginfo_list[0] # Extract the dictionary from the list

                    # Pass zero_distance_mm loaded from metadata
                    self._update_metadata(timestamp, object_id, node_number, 
                                          repetition_num, self.zero_distance_mm, self.zero_offset_mm,
                                          None, calculated_diameter, flags, flaginfo)

                    # Update plot title with estimated diameter
                    title_text = f"Force vs Timestamp (Est. Diameter: {calculated_diameter:.2f} mm)"
                    self.ax_force.set_title(title_text)

                    # Add flags to the plot if present
                    if flags:
                        y_pos = 0.95  # Start Y position for annotations
                        for flag in flags:
                            text = flaginfo.get(flag, flag)  # Use flaginfo if available, else flag
                            self.ax_force.text(0.02, y_pos,
                                     text, transform=self.ax_force.transAxes, color='red', fontsize=12,
                                     verticalalignment='top',
                                     bbox=dict(facecolor='white', alpha=0.7))
                            y_pos -= 0.05 # Adjust Y position for next flag

                    self.after(0, self._update_plot)
                elif has_critical_error:
                    self.logger.error("Measurement failed due to critical Arduino errors.")
                    self._cleanup_failed_measurement(fd_csv)
                    # Error details already shown by _handle_measurement_errors
                else:
                    self.logger.error("Measurement failed: no .s2p file created.")
                    self._cleanup_failed_measurement(fd_csv)
                    self.after(0, lambda: messagebox.showerror("Measurement Failed", "No .s2p file created. CSV file deleted."))

            except ConnectionError as ce:
                self.logger.exception("Connection error during measurement sequence.")
                # Try to reset serial connections automatically
                try:
                    self._cleanup_serial_connections()
                except Exception:
                    pass
                self.after(0, lambda: messagebox.showerror("Connection Error", 
                                                           "Connection error. Please check Arduino connection and try again."))
                self._cleanup_failed_measurement(fd_csv) # Clean up CSV if it was created before the connection failed.
            except Exception as e:
                self.logger.exception("An error occurred during the measurement sequence.")
                # Try to reset serial connections on any error
                try:
                    self._cleanup_serial_connections()
                except Exception:
                    pass
                self.after(0, lambda: messagebox.showerror("Error", f"An unexpected error occurred: {e}"))
                self._cleanup_failed_measurement(fd_csv) # Clean up CSV on other errors.
            
            finally:
                if self.protocol:
                    self.protocol.close()
                    # Small delay to let Arduino settle after protocol cleanup
                    time.sleep(0.5)
                    
                    # Only reset serial connections after successful measurement to prevent Arduino blocking
                    # Skip reset if measurement failed to avoid interfering with error recovery
                    if (vna_success and not has_critical_error):
                        self._reset_serial_silent()
                    
                self._update_last_measurement_label()
        
        self.after(0, self._toggle_controls, "normal")

    def _update_plot(self):
        """Triggers a redraw of the Matplotlib canvas."""
        self.fig.tight_layout()
        self.canvas.draw()

    def _create_dummy_plot(self):
        # Clear existing axes, don't recreate them
        self.ax_force.clear()
        self.ax_s21.clear()

        # Dummy Force vs Time plot
        time_data = [i for i in range(100)]
        force_data = [i * 0.1 + math.sin(i / 5.0) for i in time_data]
        self.ax_force.plot(time_data, force_data, color='blue')
        self.ax_force.set_title("Dummy Force vs Time (Est. Diameter: 12.34 mm)", fontsize=10)
        self.ax_force.set_xlabel("Time (s)", fontsize=9)
        self.ax_force.set_ylabel("Force (N)", fontsize=9)
        self.ax_force.grid(True)
        self.ax_force.tick_params(labelsize=8)

        # Add a dummy flag example
        self.ax_force.text(0.02, 0.88, "MIP:3 (Dummy Flag)", transform=self.ax_force.transAxes, color='red',
                 fontsize=10, verticalalignment='top', bbox=dict(facecolor='white', alpha=0.7))

        # Dummy Power Spectrum (S21) plot
        freq_data = [i * 10 for i in range(1, 101)]  # 100 points from 10 to 1000 kHz
        s21_data = [-20 * math.exp(-0.01 * (f - 500)**2) + 10 for f in freq_data] # Example S21 data
        self.ax_s21.plot(freq_data, s21_data, color='red')
        self.ax_s21.set_title("Dummy Power Spectrum (S21)", fontsize=10)
        self.ax_s21.set_xlabel("Frequency (kHz)", fontsize=9)
        self.ax_s21.set_ylabel("S21 (dB)", fontsize=9)
        self.ax_s21.grid(True)
        self.ax_s21.tick_params(labelsize=8)

        # Use tight layout with minimal padding
        self.fig.tight_layout(pad=0.5)
        self.canvas.draw()

    def _update_metadata(self, timestamp_str, object_id, node_number, repetition, zero_distance_mm, zero_offset_mm, object_name=None, calculated_diameter=None, flags=None, flaginfo=None):
        """Updates the metadata JSON file with new measurement details."""
        try:
            metadata = {}
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r') as f:
                    metadata = json.load(f)

            if 'measurement_log' not in metadata:
                metadata['measurement_log'] = []

            # Convert string timestamp to datetime object then to ISO format
            ts_dt = dt.strptime(timestamp_str.replace("cal_", ""), "%Y%m%d_%H%M%S")
            ts_iso = ts_dt.isoformat()

            us_properties = {
                "timestamp": ts_iso,
                "object_id": object_id,
                "node_number": node_number,
                "repetition": repetition,
                "object_name": object_name if object_name else f"plant_{object_id}", # Add object_name
                "zero_offset_mm": zero_offset_mm,  # Store calibration offset with each measurement
            }
            
            # Add diameter and flags if provided
            if calculated_diameter is not None:
                us_properties["calculated_diameter_mm"] = calculated_diameter
            if flags:
                us_properties["flags"] = flags
            if flaginfo:
                us_properties["flaginfo"] = flaginfo

            new_log_entry = {
                "us_properties": us_properties,
                "measurement_files": {
                    "s2p": f"sweep_{timestamp_str}.s2p",
                    "csv": f"fd_{timestamp_str}.csv"
                }
            }

            metadata['measurement_log'].append(new_log_entry)

            if 'input_settings' not in metadata:
                metadata['input_settings'] = {}
            metadata['input_settings']['zero_distance_mm'] = zero_distance_mm
            metadata['input_settings']['node_number'] = node_number
            metadata['input_settings']['plant_number'] = object_id

            with open(self.metadata_file, 'w') as f:
                json.dump(metadata, f, indent=4)
            self.logger.info(f"Metadata updated for timestamp: {timestamp_str}")

        except Exception as e:
            self.logger.exception("Error updating metadata file.")
            self.after(0, lambda: messagebox.showerror("Error", f"Failed to update metadata: {e}"))

    def _set_measurement_buttons_state(self, state):
        for btn in [self.start_single_btn, self.start_reps_btn]:
            btn.config(state=state)
        self.stop_btn.config(state="normal" if state == "disabled" else "disabled")

    def _exit_app(self):
        self.destroy()

    def _update_error_status(self, status_text, status_type="success", has_details=False):
        """Update the error status display"""
        self.error_status_var.set(status_text)
        
        if status_type == "error":
            self.error_status_label.configure(style="Error.TLabel")
        elif status_type == "warning":
            self.error_status_label.configure(style="Warning.TLabel")
        else:
            self.error_status_label.configure(style="Success.TLabel")
        
        self.error_details_btn.configure(state="normal" if has_details else "disabled")

    def _handle_measurement_errors(self, protocol):
        """Process errors from a measurement protocol and update the GUI"""
        if not protocol:
            return
        
        error_summary = protocol.get_error_summary()
        if not error_summary:
            self._update_error_status("Measurement completed successfully")
            self.current_errors.clear()
            return
        
        # Store errors for details view
        self.current_errors = error_summary['recent_errors']
        
        # Update Arduino state
        if hasattr(protocol, 'ard') and protocol.ard:
            self.last_arduino_state = protocol.ard.get_state()
        
        # Determine status message and type
        total_errors = error_summary['total_errors']
        error_types = error_summary['error_types']
        is_critical = error_summary['critical_error']
        
        if is_critical:
            status_msg = f"CRITICAL: {', '.join(error_types)} ({total_errors} errors)"
            status_type = "error"
        elif total_errors > 5:
            status_msg = f"WARNING: {total_errors} errors - {', '.join(error_types)}"
            status_type = "warning"
        else:
            status_msg = f"Minor issues: {', '.join(error_types)} ({total_errors} errors)"
            status_type = "warning"
        
        self._update_error_status(status_msg, status_type, has_details=True)
        
        # Show popup for critical errors
        if is_critical:
            error_details = ", ".join(error_types)
            messagebox.showerror(
                "Critical Arduino Error", 
                f"Measurement failed due to critical error(s):\n{error_details}\n\n"
                f"Please check Arduino connection and sensor status.\n"
                f"Click 'Details' for more information."
            )

    def _show_error_details(self):
        """Show detailed error information in a popup"""
        if not self.current_errors:
            messagebox.showinfo("Error Details", "No detailed error information available.")
            return
        
        details_window = tk.Toplevel(self)
        details_window.title("Error Details")
        details_window.geometry("600x400")
        details_window.transient(self)
        details_window.grab_set()
        
        # Create scrollable text widget
        frame = ttk.Frame(details_window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        text_widget = tk.Text(frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Add error information
        text_widget.insert(tk.END, "Recent Arduino Errors:\n")
        text_widget.insert(tk.END, "=" * 50 + "\n\n")
        
        for i, error in enumerate(self.current_errors, 1):
            text_widget.insert(tk.END, f"Error {i}:\n")
            text_widget.insert(tk.END, f"  Time: {error.get('timestamp', 'Unknown')}\n")
            text_widget.insert(tk.END, f"  Type: {error.get('error_type', 'Unknown')}\n")
            text_widget.insert(tk.END, f"  Message: {error.get('message', 'No message')}\n")
            text_widget.insert(tk.END, "\n")
        
        # Add Arduino state if available
        if self.last_arduino_state:
            text_widget.insert(tk.END, "\nArduino State:\n")
            text_widget.insert(tk.END, "=" * 20 + "\n")
            text_widget.insert(tk.END, f"Connected: {self.last_arduino_state.is_connected}\n")
            text_widget.insert(tk.END, f"Last Error: {self.last_arduino_state.last_error.value}\n")
            text_widget.insert(tk.END, f"Error Count: {self.last_arduino_state.error_count}\n")
            text_widget.insert(tk.END, f"Consecutive Errors: {self.last_arduino_state.consecutive_errors}\n")
            text_widget.insert(tk.END, f"Last Force: {self.last_arduino_state.last_force:.3f} N\n")
            text_widget.insert(tk.END, f"Last Position: {self.last_arduino_state.last_position}\n")
        
        text_widget.configure(state=tk.DISABLED)
        
        # Close button
        ttk.Button(details_window, text="Close", command=details_window.destroy).pack(pady=10)

if __name__ == "__main__":
    app = MeasurementApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("Application interrupted by user. Shutting down gracefully.")
        app.destroy()
