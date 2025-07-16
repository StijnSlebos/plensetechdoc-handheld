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
