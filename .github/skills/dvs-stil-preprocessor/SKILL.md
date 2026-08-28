---
name: dvs-stil-preprocessor
description: 'Preprocess customer DVS STIL body files by expanding 16 SE_CMD dps_trigger blocks with free-drive and stress loops. Use when the user asks to preprocess DVS STIL, process dps_trigger instructions, insert waiting_after_trigger/start_stress labels, calculate loops from free-drive time and TAP period, or force UART_RXD_DRD low in copied vectors. Supports .stil and .stil.gz.'
argument-hint: '<input .stil/.stil.gz file>'
user-invocable: true
disable-model-invocation: false
---

# DVS STIL Preprocessor

Use [the preprocessing script](./scripts/preprocess_dvs_stil.py) to transform a customer DVS STIL body without overwriting the source.

## Required interaction

Before every batch run, ask the user for both values. Never infer them from an earlier run:

1. `freedrivetime`, including its unit, such as `1ms`.
2. `tapperiod`, including its unit, such as `10ns`.

Confirm the input file if multiple plausible DVS STIL body files exist. The script accepts `ns`, `us`, `µs`, `ms`, and `s`.

## Transformation

The input must contain exactly 16 `Ann {* SE_CMD dps_trigger: 0; *}` instructions. For every instruction, the script inserts this sequence while retaining the customer's original vectors after it:

1. Keep `dps_trigger: 0`.
2. Add `label:waiting_after_trigger0_<block-index>`.
3. Add a free-drive Loop with count `(freedrivetime + 0.2ms) / tapperiod`.
4. Copy the complete `V {}` immediately preceding the trigger into that Loop. In only this copy, locate `UART_RXD_DRD` from the `_bidi_` signal-group definition and force its value to `0`; preserve every other vector symbol and assignment.
5. Add `label:start_stress_<block-index>`.
6. Add an empty `V {}` Loop with count `(100ms / 16) / tapperiod`.
7. Add `dps_trigger: 1`.
8. Add `label:waiting_after_trigger1_<block-index>`.
9. Add another empty `V {}` free-drive Loop using the same free-drive count.

All 16 blocks reuse trigger IDs `0` and `1`; do not increment IDs between blocks. Label suffixes must use the zero-based block index `0` through `15`, producing `waiting_after_trigger0_0` through `waiting_after_trigger0_15`, `waiting_after_trigger1_0` through `waiting_after_trigger1_15`, and `start_stress_0` through `start_stress_15`. Loop calculations must be exact integers. The script rejects non-integral values, missing signals/vectors, unexpected trigger counts, already processed input, and attempts to overwrite the source.

## Procedure

1. Configure the Python environment for the workspace before running Python.
2. Perform a dry run first:
   - Run the bundled script with the input path, `--free-drive-time`, `--tap-period`, and `--dry-run`.
3. Check that the report says:
   - `Blocks processed: 16`
   - `Forced signal: UART_RXD_DRD (bidi position 2)`
   - Expected free-drive and stress loop counts.
4. Run again without `--dry-run`. Normally omit `--output` so the result is written beside the source as `*_process.stil` or `*_process.stil.gz`. Use an underscore before `process`; never name it `.process`.
5. Validate the generated file:
   - 16 occurrences each of `dps_trigger: 0` and `dps_trigger: 1`.
   - Exactly one indexed label for each family and block index: `waiting_after_trigger0_0` through `_15`, `waiting_after_trigger1_0` through `_15`, and `start_stress_0` through `_15`.
   - 32 free-drive Loops and 16 stress Loops.
   - Each first copied Loop has `UART_RXD_DRD=0` at `_bidi_` position 2.
   - Customer vectors following each inserted sequence remain byte-for-byte identical to the corresponding input suffix content.
6. Report the output path and all counts. If any validation fails, do not present the output as ready.

## Invocation pattern

Pass arguments directly to the script:

- Positional input path
- `--free-drive-time <duration>`
- `--tap-period <duration>`
- Optional `--output <path>`
- Optional `--dry-run`

Do not modify the compressed input in place.
