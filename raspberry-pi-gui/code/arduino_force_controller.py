# arduino_force_controller.py

import threading
import serial
import time
import re
from typing import Callable, Optional
import logging
from enum import Enum

# Configure module-level logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

LINE_RE = re.compile(r"F(?P<force>[-\d\.]+)\s+S(?P<steps>-?\d+)")

class ArduinoErrorType(Enum):
    """Types of errors that can occur with Arduino communication"""
    NONE = "NONE"
    FORCE_SENSOR_ERROR = "FORCEERROR"
    I2C_TIMEOUT = "I2CTIMEOUT"
    GENERAL_FAIL = "FAIL"
    ENDSTOP_HIT = "ENDSTOP_HIT"
    MAX_FORCE_EXCEEDED = "MAX_FORCE_EXCEEDED"

class ArduinoState:
    """Track the current state of the Arduino"""
    def __init__(self):
        self.last_error = ArduinoErrorType.NONE
        self.error_count = 0
        self.last_force = 0.0
        self.last_position = 0
        self.is_connected = False
        self.consecutive_errors = 0

class ArduinoForceController:
    def __init__(self, port: str, on_reading: Optional[Callable[[float,int],None]] = None, on_error: Optional[Callable[[ArduinoErrorType, str],None]] = None):
        self.port = port
        self.on_reading = on_reading
        self.on_error = on_error  # New callback for error handling
        self._stop = threading.Event()
        self._last_line = ""
        self.ser = None
        self._thread = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self.state = ArduinoState()
        
        # Initialize serial connection with retry and cleanup
        self._init_serial_connection()
        
    def _init_serial_connection(self, max_retries=3):
        """Initialize serial connection with cleanup and retry logic."""
        for attempt in range(max_retries):
            try:
                # Clean up any existing connection first
                self._cleanup_serial()
                
                self.logger.info(f"Attempting to connect to Arduino on {self.port} (attempt {attempt + 1}/{max_retries})")
                
                # Open serial connection
                self.ser = serial.Serial(
                    port=self.port,
                    baudrate=9600,  # Arduino expects 9600 baud
                    timeout=3.0,    # Restore original timeout
                    write_timeout=1.0
                )
                
                # Wait for Arduino to initialize
                time.sleep(2)
                
                # Clear any stale data in buffers
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                
                # Start reading thread
                self._thread = threading.Thread(target=self._read_loop, daemon=True)
                self._thread.start()
                
                self.state.is_connected = True
                self.state.consecutive_errors = 0
                self.logger.info(f"Successfully connected to Arduino on {self.port}")
                return
                
            except serial.SerialException as e:
                self.logger.warning(f"Serial connection attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    self.logger.error(f"Failed to connect to Arduino after {max_retries} attempts")
                    self.state.is_connected = False
                    raise ConnectionError(f"Could not connect to Arduino on {self.port}: {e}")
                time.sleep(1)  # Wait before retry
    
    def _cleanup_serial(self):
        """Clean up existing serial connection."""
        if hasattr(self, 'ser') and self.ser and self.ser.is_open:
            try:
                self.ser.close()
                self.logger.info("Closed existing serial connection")
            except Exception as e:
                self.logger.warning(f"Error closing existing serial connection: {e}")
        
        if hasattr(self, '_thread') and self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                self.logger.warning("Serial thread did not terminate cleanly")
    
    def reset_connection(self):
        """Reset the serial connection - useful for recovery from errors."""
        self.logger.info("Resetting Arduino connection...")
        self._stop.set()
        
        # Wait for thread to stop
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        
        # Clear stop event and reinitialize
        self._stop.clear()
        self._init_serial_connection()

    def _handle_error_message(self, line: str):
        """Handle error messages from Arduino"""
        error_type = ArduinoErrorType.NONE
        
        if line == "FORCEERROR":
            error_type = ArduinoErrorType.FORCE_SENSOR_ERROR
            self.logger.error("Arduino reported force sensor error - sensor communication failed")
        elif line == "I2CTIMEOUT":
            error_type = ArduinoErrorType.I2C_TIMEOUT
            self.logger.error("Arduino reported I2C timeout - force sensor not responding")
        elif line == "FAIL":
            error_type = ArduinoErrorType.GENERAL_FAIL
            self.logger.error("Arduino reported general failure - endstop hit or max force exceeded")
        
        if error_type != ArduinoErrorType.NONE:
            self.state.last_error = error_type
            self.state.error_count += 1
            self.state.consecutive_errors += 1
            
            # Call error callback if provided
            if self.on_error:
                self.on_error(error_type, line)
            
            self.logger.warning(f"Arduino error: {error_type.value}, consecutive errors: {self.state.consecutive_errors}")

    def _read_loop(self):
        while not self._stop.is_set():
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
                if line:
                    # Check for error messages first
                    if line in ["FORCEERROR", "I2CTIMEOUT", "FAIL"]:
                        self._handle_error_message(line)
                        self._last_line = line
                        continue
                    
                    # Check for startup message
                    if line == "STARTUP":
                        self.logger.info("Arduino startup detected")
                        self._last_line = line
                        continue
                    
                    # Try to parse force/position data
                    m = LINE_RE.match(line)
                    if m:
                        f = float(m.group("force"))
                        s = int(m.group("steps"))
                        
                        # Update state
                        self.state.last_force = f
                        self.state.last_position = s
                        self.state.consecutive_errors = 0  # Reset on successful reading
                        
                        # Log every force and step reading
                        self.logger.info("Force: %.3f N, Steps: %d", f, s)
                        if self.on_reading:
                            self.on_reading(f, s)
                    else:
                        # Debug log for unparsed lines (might be START, ERROR, etc.)
                        self.logger.debug("Unparsed line from serial: %s", line)
                    
                    self._last_line = line
            except Exception as e:
                self.logger.error(f"Error in read loop: {e}")
                break
        
        self.logger.info("Arduino read loop stopped")

    def move_to_force(self, force: float, delay_s: int):
        """Send move to force command with error handling."""
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Serial connection not available")
            
        try:
            cmd = f"MOVETOFORCE {force:.2f} {delay_s}\n"
            self.ser.write(cmd.encode())
            self.ser.flush()  # Ensure command is sent immediately
            self.logger.info(f"Sent command: {cmd.strip()}")
        except serial.SerialException as e:
            self.logger.error(f"Error sending command: {e}")
            raise ConnectionError(f"Failed to send command to Arduino: {e}")

    def get_last_reading(self) -> str:
        return self._last_line

    def get_state(self) -> ArduinoState:
        """Get current Arduino state"""
        return self.state

    def is_measurement_likely_complete(self) -> bool:
        """Check if measurement appears to have completed normally based on recent data"""
        # If we haven't seen recent force data but connection is still good, 
        # and last force was low, measurement likely completed
        return (self.state.is_connected and 
                self.state.last_error == ArduinoErrorType.NONE and
                self.state.last_force < 0.5)  # Low force suggests measurement finished

    def has_critical_error(self) -> bool:
        """Check if Arduino has a critical error that requires attention"""
        return (self.state.consecutive_errors >= 3 or 
                self.state.last_error == ArduinoErrorType.FORCE_SENSOR_ERROR)

    def close(self):
        """Safely close the Arduino connection."""
        self.logger.info("Closing Arduino connection...")
        self._stop.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                self.logger.info("Arduino connection closed successfully")
            except Exception as e:
                self.logger.warning(f"Error closing serial connection: {e}")
        
        self.state.is_connected = False

    def dummy_measurement(self, target_force: float = 1.0, hold_seconds: int = 1):
        """
        Start a short, non-blocking dummy measurement to clear Arduino state.
        This does not block; it just sends the command.
        """
        try:
            self.move_to_force(target_force, hold_seconds)
        except Exception as e:
            self.logger.warning(f"Dummy measurement failed: {e}")
            # Try to reset connection if dummy measurement fails
            try:
                self.reset_connection()
                self.move_to_force(target_force, hold_seconds)
            except Exception as e2:
                self.logger.error(f"Dummy measurement failed even after reset: {e2}")
