### 📡 Serial Log Reference

This module communicates over serial at **115200 baud**. Logs, data, and error messages follow a compact and parsable format.

- All logs begin with `L#`, errors with `E#`, and data lines with `F... S...`.
- Endstop and Killstop states are printed as: `L#E:1`, `L#K:0` (1 = active, 0 = inactive).
- Force-position data follows the format: `F<force> S<step>`, e.g., `F1.234 S100`.

You can use [Arduino Serial Monitor](https://docs.arduino.cc/software/ide-v2/tutorials/ide-v2-serial-monitor) or [Python `pyserial`](https://pyserial.readthedocs.io/en/latest/pyserial.html) for reading and parsing these messages in real-time.

| Code     | Type   | Description                          | Trigger Location                  |
|----------|--------|--------------------------------------|-----------------------------------|
| L#INI    | Log    | Initialization started               | `setup()`                         |
| L#STU    | Log    | Setup complete                       | End of `setup()`                  |
| L#SST    | Log    | Start of force control command       | `parseCommand()` on success       |
| L#SER    | Log    | Serial command parse error           | `parseCommand()` on failure       |
| L#RST    | Log    | FX29 sensor reset initiated          | `resetFX29()`                     |
| L#E:[b]  | Log    | ENDSTOP status: 1 = reached, 0 = not | `setup()`                         |
| L#K:[b]  | Log    | KILLSTOP status: 1 = triggered, 0 = not | `setup()`                      |
| E#FER    | Error  | Force sensor read failure            | `readForce()` after retries fail  |
| E#STP    | Error  | Safety stop triggered                | `moveToPosition()`                |
| F[val] S[pos] | Data   | Force and step position log        | `serialForcePositionLog()`        |
