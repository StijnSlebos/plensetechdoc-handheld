![System Overview](assets/docslogo.png)
# plensetechdoc-handheld
Documentation and code for the ultrasound handheld measuring device built by plense-technologies.

## Overview

A precision-engineered handheld setup for in-situ acoustic measurement of plant stems. The system integrates a force-controlled stepper motor clamp, dual piezoelectric transducers, and a Raspberry Pi GUI. Measurements are triggered by controlled force application and executed via a miniVNA, producing calibrated Touchstone files.

## Features

- Arduino-based motor and endstop control
- Force sensor for precise clamping
- Dual piezo transducers for signal transmission/reception
- Signal conditioning hardware
- miniVNA for impedance/transfer measurements
- Raspberry Pi GUI for system control and data capture

---

## Repository Structure

```text
handheld-acoustic-device/
├── README.md                  # Documentation overview
├── /arduino-firmware/        # Stepper motor & sensor control firmware
│   └── clamp_control.ino
├── /raspberry-pi-gui/        # GUI Python application
│   ├── gui_main.py
│   ├── vna_control.py
│   └── force_controller.py
├── /hardware/
│   ├── schematics/           # Circuit and filtering board schematics
│   │   └── signal_chain.pdf
│   ├── bill_of_materials.xlsx
│   └── cad/                  # Fusion360 CAD files
│   └── stl/                  # 3D printable STL  files
├── /data/
│   ├── example_measurements/
│   │   └── plant_stem_001.s2p
│   └── calibration/
│       └── baseline.s2p
└── /docs/
    ├── usage_guide.md
    ├── calibration_guide.md
    └── theory_background.md
```
<p float="left">
  <img src="assets/handheld-picture-1.jpeg" width="45%" />
  <img src="assets/handheld-picture-2.jpeg" width="45%" />
</p>

---

## 1. **Introduction**
Welcome to the startup guide for using our plant acoustic sensing system. This document provides an overview of system components, setup procedures, operating routines, and background theory.

![System Overview](assets/system-diagram-overview.png)

## 2. **System Components**
- Arduino-based motor and endstop control
- Force sensor for precise clamping
- Dual piezo transducers for signal transmission/reception
- Signal conditioning hardware
- nanoVNA for impedance and frequency response measurement
- Raspberry Pi GUI for system control and data capture
- Caliper (schuifmaat)
- Smartphone for photo documentation

## 3. **How It Works**
The system analyzes the frequency-dependent transmission characteristics of acoustic signals through the plant stem, reflecting physiological and structural traits. The stem is clamped and probed using piezo transducers, while signal analysis is conducted via the nanoVNA. Coordination is handled by the Raspberry Pi and Arduino.

## 4. **Setup Instructions**
### Arduino Firmware Upload
Firmware upload is only necessary when building a new system.

For existing setups:
- Ensure power is connected to both Arduino and the motor driver (black adapter)
- On power-up, the Arduino will automatically home and enter wait mode

> ⚠️ **Warning**: If homing does not occur immediately, disconnect power to avoid mechanical damage.

### Raspberry Pi GUI Setup
Startup sequence:
```bash
cd contact-edge-code
source venv/bin/activate
python gui.py
```

- GUI may stall on message boxes — check active windows.
- The nanoVNA **does not require manual calibration**: calibration files are loaded automatically from the Raspberry Pi.
- However, the mechanical setup **must be calibrated on startup** using a 12 mm stave to align motor steps with diameter.
- Use "Single" measurement mode (3 repetitions does not function reliably).
- GUI failure mode is non-destructive; no need to delete files.

**Per Plant Protocol:**
- Measure stem diameter using caliper
- Take a photo of the plant using a smartphone

## 5. **Usage Workflow**
### Clamping Routine
- Position stem in clamp
- Allow automatic homing and engagement

### Triggering nanoVNA
- Use GUI to start frequency response measurement
- Ensure mechanical calibration has been completed

### Data Retrieval
- Measurements saved locally on Raspberry Pi
- Access via SCP or USB export

## 6. **Data Format**
### Touchstone (.s2p)
- Standard 2-port network parameter file
- Contains frequency, magnitude, and phase of S11/S21 etc.
- Can be visualized with tools like NanoVNA Saver or MATLAB

## 7. **Hardware Assembly**
- Include Bill of Materials (BOM)
- STL files and CAD models for 3D-printed parts
- *Future additions:*
  - Image of amplifier configuration (tunable gain stages)
  - Signal conditioning circuit schematic
  - Full Arduino wiring diagram: FX29 force sensor, DRV8825 motor driver, endstop, button, cooling fan, NEMA 17 stepper motor

## 8. **Theoretical Background**
### Acoustic Impedance and Frequency Transmission
- Frequency-dependent impedance and transfer response represent internal mechanical structure
- Influenced by stem stiffness, geometry, water content, and health status

### Plant Sensing Rationale
- Transfer functions provide insights into physiological condition
- Non-destructive and consistent over time

## 9. **Troubleshooting Guide**
### Common Problems & Tips
- Start measurements at 8:00 — helps reduce heat and avoids interference with irrigation (sproeiers)
- Time might be inaccurate if there’s no internet connection
- Use a comfortable amount of ultrasound gel — not too much, not too little
- Always calibrate using the 12 mm stave — either one is acceptable
- Calibrate hourly unless failure mode disrupts the flow, in which case recalibration might not be required
- Use keyboard and mouse due to gloves (touchscreen is unreliable)
- **Remove the dripper before starting measurements**
- Manually measured diameters are preferred — the values in `metadata.json` are unreliable

### Failure Modes
- Stop immediately if a measurement takes unusually long

### Full Restart Procedure
1. Unplug Arduino cable (on the Arduino side)
2. Exit the GUI
3. Power cycle the nanoVNA using its slider switch
4. Open Arduino IDE and check the port number:
   - Program: Arduino, under Programming
   - Tools → Port: identify the correct `/dev/ttyACM*` port
5. If needed, update the port in `motor_test.py` to match
6. Reconnect the Arduino USB cable
7. Restart the GUI and perform calibration

## 10. **Contributing & License**
Open contributions welcome. Licensing details to be added.






