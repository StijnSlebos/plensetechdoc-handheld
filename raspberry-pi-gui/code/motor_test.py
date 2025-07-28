#!/usr/bin/env python3
"""
Force-Deflection Measurement and Young's Modulus Extraction
"""
import logger_setup  # noqa: F401
import csv
import time
import threading
from datetime import datetime
from arduino_force_controller import ArduinoForceController, ArduinoErrorType
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime as dt
import sys
# from matplotlib.figure import Figure  # Unused import
import pandas as pd
import matplotlib.dates as mdates

# Configuration
PORT = "/dev/ttyACM0"  # Changed from ttyACM1 to ttyACM0 (more common)
TARGET_FORCE = 9.0  # N
HOLD_SECONDS = 21  # how long Arduino holds before homing
SETTLE_SECONDS = 1  # wait after force reached before measuring
MEASURE_TIME = 20  # duration of your measurement
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
CSV_FILENAME = os.path.join(
    OUTPUT_DIR,
    f"fd_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
)

# Arduino Homing Timeout
ARDUINO_HOMING_TIMEOUT_SECONDS = 10.0  # Maximum time to wait for Arduino

# Geometry for Young's modulus calculation
DEFAULT_ZERO_DISTANCE_MM = 21.45  # Default zero reference in mm

# Spindle and stepper configuration
LEAD_MM_PER_REV = 2.0  # TR8×2 -> 2 mm per full revolution
STEPS_PER_REV = 200  # 360° / 1.8° per step = 200 steps per revolution
MICROSTEP_DIVIDER = 1  # MS1=0,MS2=0,MS3=0 => full step (no microstepping)
STEPS_PER_MM = (STEPS_PER_REV * MICROSTEP_DIVIDER) / LEAD_MM_PER_REV
# e.g. (200*1)/2 = 100 steps per mm => 0.01 mm per step

# ── PROTOCOL ─────────────────────────────────────────────────────────────────
class MeasurementProtocol:
    def __init__(self, csv_filename=None, on_measurement_start=None, stop_event=None):
        target_file = csv_filename if csv_filename else CSV_FILENAME
        self._csv_file = open(target_file, "w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(["timestamp", "force_N", "deflection_mm"])
        # Callback for starting external measurement (e.g., NanoVNA)
        self._on_measurement_start = on_measurement_start
        print(
            f">>> MeasurementProtocol init: callback = "
            f"{self._on_measurement_start is not None}"
        )
        # Thread handle for external measurement
        self._vna_thread = None
        self._logging_active = False
        self._lock = threading.Lock()
        
        # Error tracking
        self._arduino_errors = []
        self._critical_error_occurred = False
        self._error_recovery_attempted = False
        
        print(f">>> Initializing Arduino connection on port: {PORT}")
        try:
            self.ard = ArduinoForceController(
                port=PORT,
                on_reading=self._on_reading,
                on_error=self._on_arduino_error  # New error callback
            )
            print(">>> Arduino connection established successfully")
        except Exception as e:
            print(f">>> ERROR: Failed to connect to Arduino: {e}")
            raise
        # used to detect first arrival in the target window
        self._meas_started = threading.Event()
        # event to signal measurement completion
        self._finished = threading.Event()
        self.stop_event = stop_event # Store the stop event

    def _on_arduino_error(self, error_type: ArduinoErrorType, message: str):
        """Handle Arduino error callbacks"""
        error_info = {
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type,
            'message': message
        }
        self._arduino_errors.append(error_info)
        
        print(f">>> Arduino Error: {error_type.value} - {message}")
        
        # Check for critical errors that should stop measurement
        # CONNECTION_LOST during measurement completion is often normal, so be more careful
        if error_type == ArduinoErrorType.FORCE_SENSOR_ERROR:
            self._critical_error_occurred = True
            print(f">>> CRITICAL ERROR: {error_type.value} - stopping measurement")
            self._finished.set()  # Signal measurement to stop
        elif error_type == ArduinoErrorType.I2C_TIMEOUT:
            recent_i2c_errors = [e for e in self._arduino_errors[-5:] 
                               if e['error_type'] == ArduinoErrorType.I2C_TIMEOUT]
            if len(recent_i2c_errors) >= 3:
                print(">>> Multiple I2C timeouts detected - sensor may be failing")
                self._critical_error_occurred = True

    def _on_reading(self, force, step_pos):
        """Called ~10 Hz by the ArduinoForceController.
        Logs all force and deflection readings to capture the full yield curve.
        """
        ts = datetime.now().isoformat()
        defl = step_pos / STEPS_PER_MM
        with self._lock:
            self._csv_writer.writerow([ts, f"{force:.3f}", f"{defl:.4f}"])
        # Detect initial arrival at target and schedule
        # measurement-phase logging
        if (not self._meas_started.is_set() and
                abs(force - TARGET_FORCE) < 1.1):
            print(f">>> Target force {TARGET_FORCE:.1f} N reached! "
                  f"Starting measurement in {SETTLE_SECONDS}s...")
            self._meas_started.set()
            t = threading.Timer(SETTLE_SECONDS, self._start_logging)
            t.daemon = True
            t.start()

    def _start_logging(self):
        """Turn on CSV logging for the next MEASURE_TIME seconds."""
        try:
            sys.stdout.log_file.seek(0)
            sys.stdout.log_file.truncate()
            sys.stderr.log_file.seek(0)
            sys.stderr.log_file.truncate()
        except Exception as e:
            print(f"Error clearing log file: {e}")
        with self._lock:
            self._logging_active = True
        # schedule stop
        t = threading.Timer(MEASURE_TIME, self._stop_logging)
        t.daemon = True
        t.start()
        print(f">>> Logging CSV for {MEASURE_TIME} s ...")
        # Trigger external measurement callback if provided
        if self._on_measurement_start:
            print(">>> Starting NanoVNA measurement...")
            # start VNA measurement in a separate thread
            vna_thread = threading.Thread(target=self._on_measurement_start)
            vna_thread.daemon = True
            vna_thread.start()
            self._vna_thread = vna_thread
        else:
            print(">>> No NanoVNA callback provided")

    def _stop_logging(self):
        with self._lock:
            self._logging_active = False
        print("<<< Measurement window complete. CSV logging stopped.")
        # Wait until Arduino is homed before signaling finished
        start_time = time.time()
        while time.time() - start_time < ARDUINO_HOMING_TIMEOUT_SECONDS:
            if self.stop_event and self.stop_event.is_set():
                print(">>> Stop event detected in _stop_logging. Aborting homing wait.")
                break
            
            # Check for critical errors
            if self._critical_error_occurred:
                print(">>> Critical error detected - aborting homing wait")
                break
                
            last = self.ard.get_last_reading()
            # Check for valid completion signals (removed CONNECTION_LOST from here)
            if (last.startswith("S0") or last == "FAIL" or 
                last in ["FORCEERROR", "I2CTIMEOUT"]):
                print(f">>> Arduino signal received: {last}")
                break
            
            # Check if Arduino is still connected but just finished
            if (self.ard.is_measurement_likely_complete() and
                time.time() - start_time > 5):  # Give some time for normal completion
                print(">>> Arduino appears to have completed measurement normally")
                break
                
            time.sleep(0.5)
        else:
            print(
                f"<<< WARNING: Arduino did not send expected signal "
                f"within {ARDUINO_HOMING_TIMEOUT_SECONDS} seconds."
            )
        self._finished.set()

    def get_measurement_success(self):
        """Check if the measurement completed successfully"""
        return (self._finished.is_set() and self._meas_started.is_set() and 
                not self._critical_error_occurred)

    def get_error_summary(self):
        """Get summary of errors that occurred during measurement"""
        if not self._arduino_errors:
            return None
        
        error_summary = {
            'total_errors': len(self._arduino_errors),
            'critical_error': self._critical_error_occurred,
            'error_types': list(set([e['error_type'].value for e in self._arduino_errors])),
            'recent_errors': self._arduino_errors[-3:] if len(self._arduino_errors) > 3 else self._arduino_errors
        }
        return error_summary

    def run(self):
        # reset the state machine so we can measure again
        self._meas_started.clear()
        self._finished.clear()
        self._logging_active = False
        self._arduino_errors.clear()
        self._critical_error_occurred = False
        self._error_recovery_attempted = False

        try:
            start_time = time.time()
            print(f">>> Sending MOVETOFORCE {TARGET_FORCE:.2f} {HOLD_SECONDS}")
            self.ard.move_to_force(TARGET_FORCE, HOLD_SECONDS)
            print(f">>> Command sent successfully, waiting for Arduino response...")

            # wait until measurement complete or Arduino goes home or critical error
            while not self._finished.is_set():
                if self.stop_event and self.stop_event.is_set():
                    print(">>> Stop event detected in MeasurementProtocol.run(). Aborting.")
                    self._finished.set()
                    break
                
                # Check for critical errors
                if self._critical_error_occurred:
                    print(">>> Critical Arduino error detected. Stopping measurement.")
                    break
                    
                time.sleep(0.5)

            # Notify end of run
            if self._critical_error_occurred:
                print(">>> Measurement ended due to critical error")
            else:
                print("Arduino returned home or measurement complete.")
            
            elapsed = time.time() - start_time
            print(f">>> Total run duration: {elapsed:.2f} s", flush=True)
            
            # Print error summary if errors occurred
            error_summary = self.get_error_summary()
            if error_summary:
                print(f">>> Errors during measurement: {error_summary['total_errors']} total, "
                      f"Critical: {error_summary['critical_error']}")
                print(f">>> Error types: {', '.join(error_summary['error_types'])}")
                
        finally:
            self.ard.close()
            self._csv_file.close()

    def close(self):
        """Explicitly close Arduino and CSV resources."""
        self.ard.close()
        self._csv_file.close()

def plot_force_deflection(
    csv_filename=CSV_FILENAME, zero_distance_mm=None, ax_force=None, ax_s21=None
):
    """Read force and deflection data from CSV and plot."""
    forces, deflections, timestamps = [], [], []
    try:
        with open(csv_filename, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                forces.append(float(row["force_N"]))
                deflections.append(abs(float(row["deflection_mm"])))
                timestamps.append(row["timestamp"])
    except (IOError, KeyError, ValueError) as error:
        print(f"Error reading CSV for plotting: {error}")
        # Return empty DataFrame and None for axes if an error occurs
        return None, None, pd.DataFrame(columns=['timestamp', 'force_N', 'deflection_mm'])

    # --- Create Figure / Use existing axes ---
    if ax_force is None or ax_s21 is None:
        fig, (ax_force, ax_s21) = plt.subplots(1, 2)
        return_fig = fig
    else:
        return_fig = None
        ax_force.clear()
        ax_s21.clear()

    # --- Top-right: Timestamp vs Force (now ax_force) ---
    try:
        times = mdates.datestr2num(timestamps)
        ax_force.plot(times, forces, marker=".", linestyle="-")
        ax_force.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax_force.set_xlabel("Timestamp")
    except Exception:
        ax_force.plot(range(len(forces)), forces, marker=".", linestyle="-")
        ax_force.set_xlabel("Sample index")
    ax_force.set_ylabel("Force (N)")
    ax_force.set_title("Force vs Timestamp")  # No diameter or flags here initially
    ax_force.grid(True)

    # --- Bottom-right: NanoVNA Power Spectrum (S21) (now ax_s21) ---
    s2p_filename = csv_filename.replace("fd_", "sweep_").replace(
        ".csv", ".s2p"
    )
    if os.path.exists(s2p_filename):
        freq, s21_db = [], []
        try:
            with open(s2p_filename, 'r') as s2p_file:
                for line in s2p_file:
                    if line.strip() and not line.startswith(('!', '#')):
                        parts = line.split()
                        if len(parts) >= 5:
                            f_val = float(parts[0])
                            s21_real = float(parts[3])
                            s21_imag = float(parts[4])
                            s21 = max(
                                np.sqrt(s21_real**2 + s21_imag**2), 1e-12
                            )
                            freq.append(f_val / 1000)  # to kHz
                            s21_db.append(20 * np.log10(s21))
            if freq and s21_db:
                ax_s21.plot(freq, s21_db, marker='.', linestyle='-')
        except (ValueError, IndexError):
            pass  # Ignore malformed lines
            
    ax_s21.set_xlabel("Frequency (kHz)")
    ax_s21.set_ylabel("S21 (dB)")
    ax_s21.set_title("NanoVNA Power Spectrum (S21)")
    ax_s21.grid(True)
    if not ax_s21.lines:
        ax_s21.text(0.5, 0.5, "s2p file not found\nor has no data", ha="center",
                 va="center", transform=ax_s21.transAxes)

    plt.tight_layout()
    # Depending on whether new figure was created or existing axes were used
    if return_fig:
        return return_fig, ax_force, pd.DataFrame({'timestamp': timestamps, 'force_N': forces,
                                   'deflection_mm': deflections})
    else:
        return None, None, pd.DataFrame({'timestamp': timestamps, 'force_N': forces,
                                   'deflection_mm': deflections})

if __name__ == "__main__":
    # Run a short dummy measurement to clear any state issues (non-blocking)
    print("Running short dummy measurement to clear state...")
    dummy_controller = ArduinoForceController(port=PORT)
    dummy_controller.dummy_measurement(target_force=1.0, hold_seconds=1)
    time.sleep(2)  # Give Arduino time to process dummy command
    dummy_controller.close()

    print(
        "Starting full measurement with continuous logging "
        "of force and displacement..."
    )
    protocol = MeasurementProtocol()
    protocol._start_logging()  # Begin logging force and displacement
    protocol.run()
    protocol._stop_logging()  # Stop logging after measurement
    protocol.close()
    fig, ax2, df = plot_force_deflection()
