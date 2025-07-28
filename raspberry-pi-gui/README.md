## Force & NanoVNA Control Suite for Raspberry Pi

This repository contains scripts to:

* Control a stepper-driven indenter via Arduino for force–deflection measurements
* Perform continuous NanoVNA sweeps with automated USB power-cycling
* Manage USB hub ports for nanoVNA recovery

---

## Files

* **`gui.py`**
  **New Graphical User Interface (GUI)** for managing force-deflection and NanoVNA measurements. This fullscreen, touchscreen-friendly interface allows users to configure and initiate single or repetitive measurements, with dedicated controls for Node #, Plant #, and measurement actions (Start, Stop, Remove Previous, Restart App). It integrates the `motor_test.py` and `nanovna.py` functionalities for a streamlined workflow.

* **`arduino_force_controller.py`**
  Python class to communicate with an Arduino over serial, read force/step data, and send move commands.

* **`motor_test.py`**
  High-level measurement protocol: drives the indenter to a target force, logs force vs. deflection, and plots results. **Now includes a configurable zero_distance_mm, loaded from metadata.json, and improved resilience against Arduino communication hangs with an homing timeout.**

* **`nanovna.py`**
  Continuous NanoVNA sweep script with auto-recovery via USB power-cycling. Segments the sweep, retries on failure, and writes `.s2p` files. **Enhanced to return a success/failure boolean to the GUI, enabling robust error handling and file cleanup.**

* **`usb_controller_subprocess.py`**
  Wraps `uhubctl` calls to power-cycle a UUGear MEGA4 hub port. Used by `nanovna.py` for recovery.

* **`../arduino-firmware/clamp-control/clamp-control.ino`**
  Arduino sketch running on the Pi-connected Arduino to report force and stepper position over serial.

---

## Metadata (`output/metadata.json`)

The `output/metadata.json` file now contains enhanced logging for each measurement under the `measurement_log` array, with `us_properties` for each entry including:
*   `measurement_id`: Unique identifier for the measurement.
*   `timestamp`: ISO-formatted timestamp of the measurement.
*   `object_id` (Plant #): Identifies the specific plant being measured.
*   `node_number`: Indicates the node or sensor location.
*   `repetition`: The repetition number for the given object_id.
*   `zero_distance`: The zero reference distance used for the measurement, loaded from `input_settings`.

Other fields in `us_properties` are set to "none" by default.

---

## Prerequisites

1. **Raspberry Pi OS** (Buster or later)

2. **Enable serial port**

   ```bash
   sudo raspi-config
   # Interface Options → Serial Port → Disable shell, enable serial hardware
   ```

3. **Install system packages**

   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-pip python3-venv uhubctl
   ```

---

## Python Environment Setup

### Initializing Virtual Environment

1. **Navigate to the raspberry-pi-gui directory:**

   ```bash
   cd raspberry-pi-gui
   ```

2. **Create a virtual environment:**

   ```bash
   python3 -m venv venv
   ```

3. **Activate the virtual environment:**

   ```bash
   source venv/bin/activate
   ```

   **Note**: You should see `(venv)` at the beginning of your command prompt when the virtual environment is active.

4. **Upgrade pip and install dependencies:**

   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

### Managing the Virtual Environment

- **To activate the virtual environment in future sessions (on raspberry pi):**
  ```bash
   cd raspberry-pi-gui
   source venv/bin/activate
   ```

- **To deactivate the virtual environment:**
  ```bash
   deactivate
   ```

- **To remove and recreate the virtual environment (if needed):**
  ```bash
   deactivate
   rm -rf venv
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

**Important**: Always activate the virtual environment before running any Python scripts in this project.

---

## requirements.txt

```text
pyserial
numpy
scipy
matplotlib
pynanovna
```

---

## Arduino CLI Setup

1. **Install Arduino CLI**

   ```bash
   curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
   sudo mv bin/arduino-cli /usr/local/bin/
   ```

2. **Initialize & install AVR core**

   ```bash
   arduino-cli config init
   arduino-cli core update-index
   arduino-cli core install arduino:avr
   ```

3. **Compile & upload sketch**

   ```bash
   # Navigate to the arduino-firmware directory
   cd ../arduino-firmware/clamp-control
   
   # Compile the sketch
   arduino-cli compile --fqbn arduino:avr:uno clamp-control.ino
   
   # Upload to Arduino (adjust port if needed)
   arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno clamp-control.ino
   ```

---

## Usage

1. **Run the GUI application**

   ```bash
   python gui.py
   ```

2. **Run force measurement** (legacy, primarily used by GUI)

   ```bash
   python motor_test.py
   ```

3. **Run NanoVNA sweeps** (legacy, primarily used by GUI)

   ```bash
   python nanovna.py
   ```

4. **Power-cycle USB ports manually** (if needed)

   ```bash
   python usb_controller_subprocess.py
   ```

---

## Testing on Raspberry Pi

Before running the full GUI application, it's recommended to test individual components to ensure proper hardware connectivity:

### 1. **Test Arduino Connection**
Ensure your Arduino is connected and appears as `/dev/ttyACM0` (or adjust the port in `motor_test.py`):

```bash
# Test Arduino communication
python code/motor_test.py
```

**Expected behavior**: The script should connect to Arduino, perform a force measurement, and create output files.

### 2. **Test NanoVNA Connection**
Verify NanoVNA is connected to the correct USB hub port:

```bash
# Test NanoVNA sweeps
python code/nanovna.py
```

**Expected behavior**: The script should connect to NanoVNA, perform sweeps, and save `.s2p` files.

### 3. **Test USB Hub Control**
Verify USB hub power cycling works:

```bash
# Test USB port power cycling
python code/usb_controller_subprocess.py
```

**Expected behavior**: The specified USB port should power off for 5 seconds, then power back on.

### 4. **Run Full GUI Application**
Once individual components are working:

```bash
# Run the main GUI application
python code/gui.py
```

**Expected behavior**: Fullscreen GUI should appear with measurement controls and real-time plotting.

### Troubleshooting

- **Arduino Connection Issues**: Check if Arduino appears as `/dev/ttyACM0` or `/dev/ttyACM1`
- **NanoVNA Issues**: Verify USB hub location and port numbers in `nanovna.py`
- **Permission Issues**: Ensure `uhubctl` is installed and user has sudo privileges
- **Port Conflicts**: Use `_cleanup_serial_connections()` in GUI to reset stale connections

---

## Notes

* All outputs (CSV, `.s2p`, plots) are saved in the `output/` directory.
* Adjust port names (e.g. `/dev/ttyUSB0`) and parameters at the top of each script.
* Ensure your Arduino is running `arduino.ino` and appears as `/dev/ttyACM0` (or similar).

## Architecture & Integration

This suite is composed of multiple components that work together to perform precise measurements and control actions:

- The Arduino microcontroller code (located in the `arduino-firmware/clamp-control/` folder) handles low-level control of the stepper motor and sensors. The `clamp-control.ino` sketch provides the firmware for the Arduino.
- The `arduino_force_controller.py` script serves as the interface between the Python application and the Arduino, wrapping the communication logic.
- The `motor_test.py` script uses the Arduino controller to drive the stepper motor, execute force measurements, and log results.
- The `nanovna.py` script manages continuous NanoVNA sweeps and implements auto-recovery via USB power-cycling by calling `usb_controller_subprocess.py`.
- The `usb_controller_subprocess.py` leverages the `uhubctl` tool to manage USB port power, ensuring robust device recovery in case of sweep failures.
- Each component is modular, allowing for separate testing and maintenance while collectively contributing to the measurement and control suite.
