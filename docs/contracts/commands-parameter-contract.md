# Commands Parameter Contract

Core owns the numeric parameter constraints used by direct Core requests, CLI,
Power Worker, and WebUI Commands. Adapter defaults are not limits.

## Fixed Limits

- Public Core and raw JSON `channel` values are type-strict: an accepted
  channel is an exact positive integer. Exact `"all"` is accepted only by
  commands that support all-channel selection. Booleans, floats, numeric
  strings, whitespace-padded strings, null, arrays, objects, and alternate
  spellings such as `"ALL"` are rejected rather than coerced. CLI text is
  parsed by argparse before it reaches this contract.
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
- Ramp `enable_output` is an optional exact boolean and defaults to `false`.
  Ramp List version 2 always means `false`; versions 3 and 4 require an exact
  top-level JSON boolean. Adapters must not coerce strings or numbers.
- Ramp, Ramp List, and Sequence `loop_count` is the total number of complete
  workflow executions. It must be an exact integer from 1 through 255;
  booleans, floats, strings, null, zero, negatives, and 256 are rejected.
  `1` is one normal execution, while `2` restarts once. Ramp List v4 and
  Sequence v2 require the field. Older supported document versions imply 1.
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

One canonical timing is selected. Ramp accepts `step` (every voltage step),
`segment` (Ramp complete after each iteration), or `loop` (once after every
iteration). Ramp List accepts `step`, `segment` (after each Segment), or
`loop`. Loop-complete timing requires `loop_count >= 2`. Every-step pulses
accept `delay_ms = 0`.

With `enable_output: true`, Ramp validates every effective setpoint before
writes, then orders current, first voltage, output ON, mandatory ON readback,
remaining voltage steps, per-iteration Ramp-complete pulse when selected, and
final output-state readback. Ramp List applies the same first-setpoint rule
once per channel and does not repeat output ON in later segments or loops.

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
models have no invented rating. Output-family, Ramp List, Sequence, and
protection-write dry-run/simulate planning requires an explicit model profile
or a known deterministic simulator resource before model-specific channel
validation. In live mode, CLI `--model` / `runtime.expected_model_id` is only an
expected-model guard checked against `*IDN?`; it does not choose the driver or
provide channel/capability limits. OVP values are not constrained by the DC
output rating. Auto-series and parallel combined ratings are unsupported.
