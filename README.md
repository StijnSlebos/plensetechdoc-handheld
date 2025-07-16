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
│   └── mechanical_parts/     # 3D printable STL & CAD files
│       ├── clamp_arm.stl
│       └── enclosure.stl
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

---

## 1. **Introduction**
## 2. **System Components**
## 3. **How It Works**
## 4. **Setup Instructions**
   - Arduino firmware upload
   - Raspberry Pi GUI setup
## 5. **Usage Workflow**
   - Clamping routine
   - Triggering miniVNA
   - Data retrieval
## 6. **Data Format**
   - Touchstone (.s2p) description
## 7. **Hardware Assembly**
   - BOM and 3D models
## 8. **Theoretical Background**
   - Acoustic impedance
   - Plant sensing rationale
## 9. **Contributing & License**

Let me know which sections you'd like filled in first.

