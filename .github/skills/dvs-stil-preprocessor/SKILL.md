---
name: dvs-stil-preprocessor
description: 'Preprocess CCD, IOD, or DRD customer DVS STIL body files by expanding 16 SE_CMD dps_trigger blocks with pre-trigger, free-drive, and stress loops. Supports .stil and .stil.gz.'
argument-hint: '<input .stil/.stil.gz file>'
user-invocable: true
disable-model-invocation: false
---

# DVS STIL Preprocessor

Use [the preprocessing script](./scripts/preprocess_dvs_stil.py) to transform a customer DVS STIL body without overwriting the source.

## Required interaction

Before every batch run, ask the user for all three values. Never infer them from an earlier run:

1. `freedrivetime`, including its unit, such as `1ms`.
2. `tapperiod`, including its unit, such as `10ns`.
3. Pattern type: `CCD`, `IOD`, or `DRD`.

Confirm the input file if multiple plausible DVS STIL body files exist. The script accepts `ns`, `us`, `µs`, `ms`, and `s`.

## Transformation

The input must contain exactly 16 `Ann {* SE_CMD dps_trigger: 0; *}` instructions. For every instruction, the script inserts this sequence while retaining the customer's original vectors after it:

1. Copy the complete `V {}` immediately preceding the trigger into a 20,000-cycle Loop under `label:waiting_before_trigger0_<block-index>`. In only this copy, force the pattern-specific `_bidi_` signals to `0`; preserve every other vector symbol and assignment.
2. Keep `dps_trigger: 0`.
3. Add `label:waiting_after_trigger0_<block-index>`.
4. Add an empty free-drive Loop with count `max((freedrivetime + 0.2ms) / tapperiod, 100000)`.
5. Add `label:start_stress_<block-index>` and an empty `V {}` Loop with count `(100ms / 16) / tapperiod`.
6. Add `label:waiting_before_trigger1_<block-index>` and an empty 20,000-cycle `V {}` Loop. Do not copy the preceding Vector into this Loop.
7. Add `dps_trigger: 1`.
8. Add `label:waiting_after_trigger1_<block-index>` and another empty `V {}` free-drive Loop using the same minimum-adjusted count.

Pattern-specific signals forced to `0` in each pre-trigger copy:

- `CCD`: `I2C_IPMI_SCL`, `STIMER_CCDNE1`, `UART_RXD_CCD_L_S`, `UART_RXD_CCD_S`
- `IOD`: `UART_RXD_IOD`, `AVSBUS_SDATA0`
- `DRD`: `UART_RXD_DRD`

All 16 blocks reuse trigger IDs `0` and `1`; do not increment IDs between blocks. Label suffixes must use the zero-based block index `0` through `15`, including both `waiting_before_trigger0_0` through `_15` and `waiting_before_trigger1_0` through `_15`. Loop calculations must be exact integers before applying the 100,000-cycle minimum. The script rejects non-integral values, missing signals/vectors, unexpected trigger counts, already processed input, and attempts to overwrite the source.

## Procedure

1. Configure the Python environment for the workspace before running Python.
2. Perform a dry run first:
   - Run the bundled script with the input path, `--free-drive-time`, `--tap-period`, `--pattern-type`, and `--dry-run`.
3. Check that the report says:
   - `Blocks processed: 16`
   - `Pre-trigger loop count: 20000`
   - `Forced signal: UART_RXD_DRD (bidi position 2)`
   - Expected free-drive and stress loop counts.
4. Run again without `--dry-run`. Normally omit `--output` so the result is written beside the source as `*_process.stil` or `*_process.stil.gz`. Use an underscore before `process`; never name it `.process`.
5. Validate the generated file:
   - 16 occurrences each of `dps_trigger: 0` and `dps_trigger: 1`.
   - Exactly one indexed label for each family and block index, including both waiting-before label families.
   - 32 pre-trigger Loops, 32 free-drive Loops, and 16 stress Loops.
   - Each `waiting_before_trigger0` copied Loop has every signal for the selected pattern type set to `0`.
   - Every `waiting_before_trigger1` Loop contains an empty `V {}`.
   - Customer vectors following each inserted sequence remain byte-for-byte identical to the corresponding input suffix content.
6. Report the output path and all counts. If any validation fails, do not present the output as ready.

## Invocation pattern

Pass arguments directly to the script:

- Positional input path
- `--free-drive-time <duration>`
- `--tap-period <duration>`
- `--pattern-type <CCD|IOD|DRD>`
- Optional `--output <path>`
- Optional `--dry-run`

Do not modify the compressed input in place.
