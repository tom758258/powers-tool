# Commands Parameter Contract

Core owns the numeric parameter constraints used by direct Core requests, CLI,
Power Worker, and WebUI Commands. Adapter defaults are not limits.

## Fixed Limits

- Voltage and current values must be finite and non-negative.
- `step_voltage` must be finite and greater than zero.
- Ramp and Ramp List `delay_ms` is the additional delay after each voltage
  step completes before starting the next step. It is a non-negative integer.
- `hold_ms`, settle delays, and Sequence waits are non-negative.
- Cycle Output, Smoke Output, and Sequence Cycle `duration_ms` are positive
  integers.
- `max_reads`, `max_errors`, and `wait_timeout_ms` are positive integers.
- Trigger poll intervals are integers of at least 50 ms.
- Trigger LIST count is 1 through 256. LIST dwell is 0.01 through 3600 seconds.
- Ramp supports at most 1000 voltage steps. Ramp List supports 1 through 10
  segments, each with at most 1000 voltage steps.

No unspecified maximum is added to time or read-count fields.

## Ramp Timing

Ramp and Ramp List use software setpoint steps. `delay_ms` starts only after
the voltage write and any synchronous every-step completion pulse finish. It
does not include write or pulse execution time and is not a real-time or exact
step interval.

Segment-complete and every-step completion pulses are mutually exclusive.
Every-step pulses accept `delay_ms = 0`.

## Effective Electrical Limits

Safety config limits are explicit local limits and may only make an operation
more restrictive. Model/channel electrical ratings must be added only after
verification against the relevant official Keysight programming or data
sheet. Until verified ratings are present, the project does not invent an
electrical maximum.
