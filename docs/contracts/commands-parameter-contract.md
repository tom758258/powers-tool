# Commands Parameter Contract

Core owns the numeric parameter constraints used by direct Core requests, CLI,
Power Worker, and WebUI Commands. Adapter defaults are not limits.

## Fixed Limits

- Voltage and current values must be finite and non-negative.
- `set` requires `channel` plus at least one of `voltage` or `current`.
  Supplying only one setpoint leaves the omitted setpoint unchanged on the
  instrument; adapters must not replace omitted values with zero or readback
  guesses.
- `apply`, `ramp`, `smoke-output`, Ramp List, and Sequence set/apply steps keep
  their complete setpoint requirements.
- `step_voltage` must be finite and greater than zero.
- Ramp and Ramp List `delay_ms` is the additional delay after each voltage
  step completes before starting the next step. It is a non-negative integer.
- `hold_ms`, settle delays, and Sequence waits are non-negative.
- Cycle Output, Smoke Output, and Sequence Cycle `duration_ms` are positive
  integers.
- `max_reads`, `max_errors`, and `wait_timeout_ms` are positive integers.
- Trigger poll intervals are integers of at least 50 ms.
- Trigger LIST count is 1 through 256. LIST dwell is 0.01 through 3600 seconds.
- Native Trigger LIST accepts canonical `bost_list`, `eost_list`,
  `trigger_output_pins`, and `trigger_output_polarity`. BOST/EOST lengths must
  match the voltage step count, and any enabled BOST/EOST pulse requires
  explicit output pins. Legacy `completion_pulse_pins` remains a final-step
  EOST pulse and must not be mixed with canonical fields.
- Native `trigger-step` and `trigger-list` reject `fire=true` with Immediate
  source because `INIT` starts Immediate execution.
- Native BUS `trigger-step` and `trigger-list` requests with
  `wait_complete=true` require `fire=true` in the same command.
- Native `trigger-list` arm-only requests require
  `leave_trigger_configured=true`, so a later `trigger-fire` can start the
  armed LIST.
- A started native `trigger-list` without `wait_complete=true` requires
  `leave_trigger_configured=true`, so restore does not abort the active LIST.
- With `wait_complete=true` and `leave_trigger_configured=false`, native
  Trigger LIST restores the pre-run Trigger configuration and LIST table after
  completion. `leave_trigger_configured=true` retains the newly configured
  LIST table.
- `trigger-fire` sends global `*TRG`. When `wait_complete=true`, `channel` is
  required only as the output channel to abort if the instrument-wide
  completion wait times out or is interrupted.
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

The verified independent-channel `DC output rating (0 to 40 C)` is a hard
setpoint maximum:

| Model | Channel | Maximum voltage | Maximum current |
|---|---:|---:|---:|
| E36312A | 1 | 6 V | 5 A |
| E36312A | 2, 3 | 25 V | 1 A |
| EDU36311A | 1 | 6 V | 5 A |
| EDU36311A | 2, 3 | 30 V | 1 A |

Sources are Keysight `E36300 Series Triple Output Bench Power Supply`,
publication `5992-2124EN`, dated `2023-08-25`, and `EDU36311A Triple-Output
Bench Power Supply`, publication `3121-1003.ZHTW`, dated `2021-01-11`.

Official ratings and safety config remain separate. The effective maximum is
the smaller value. A more permissive safety config never widens an official
rating. Confirmation thresholds remain safety-config policy only.

These ratings are not claims about SCPI maximum programmable values. Unknown
models have no invented rating. Plain dry-run without a confirmed model uses
fixed and safety-config validation only. OVP values are not constrained by the
DC output rating. Auto-series and parallel combined ratings are unsupported.
