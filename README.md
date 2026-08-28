# DVS STIL Preprocessor

A GitHub Copilot skill and dependency-free Python CLI for preprocessing DVS STIL body files. It expands 16 DPS trigger points into indexed free-drive and stress sequences while preserving the original customer vectors.

## Highlights

- Reads plain `.stil` and gzip-compressed `.stil.gz` files.
- Preserves the source file and writes `*_process.stil` or `*_process.stil.gz`.
- Calculates Loop counts exactly from free-drive time and TAP period.
- Generates unique label suffixes from `0` through `15`.
- Copies the Vector immediately before each trigger and forces only `UART_RXD_DRD` low.
- Supports STIL run-length notation such as `\r285 X`.
- Rejects malformed, already processed, or unexpected input instead of silently producing a partial result.
- Uses only the Python standard library.

## Repository layout

```text
.github/skills/dvs-stil-preprocessor/
├── SKILL.md
└── scripts/
		└── preprocess_dvs_stil.py
tests/
└── test_preprocess_dvs_stil.py
```

## Requirements

- Python 3.9 or newer
- A DVS STIL body containing exactly 16 `SE_CMD dps_trigger: 0` instructions
- An `_bidi_` signal-group definition containing `UART_RXD_DRD`

No third-party packages are required.

## Install as a GitHub Copilot skill

### Workspace installation

Copy the skill folder into the target repository:

```text
.github/skills/dvs-stil-preprocessor/
```

### Personal installation

Copy the same folder to:

```text
~/.copilot/skills/dvs-stil-preprocessor/
```

The skill can then be invoked as `/dvs-stil-preprocessor` or discovered automatically from requests to preprocess a DVS STIL body.

Before each run, the skill asks for:

1. `freedrivetime`, including units, for example `1ms`.
2. `tapperiod`, including units, for example `10ns`.

Supported units are `ns`, `us`, `µs`, `ms`, and `s`.

## CLI usage

Run a validation-only pass first:

```powershell
python .github/skills/dvs-stil-preprocessor/scripts/preprocess_dvs_stil.py `
	path/to/DVS_body.stil.gz `
	--free-drive-time 1ms `
	--tap-period 10ns `
	--dry-run
```

Generate the processed file:

```powershell
python .github/skills/dvs-stil-preprocessor/scripts/preprocess_dvs_stil.py `
	path/to/DVS_body.stil.gz `
	--free-drive-time 1ms `
	--tap-period 10ns
```

For an input named `DVS_body.stil.gz`, the default output is `DVS_body_process.stil.gz`.

An explicit output path can be provided with `--output`:

```powershell
python .github/skills/dvs-stil-preprocessor/scripts/preprocess_dvs_stil.py `
	path/to/DVS_body.stil.gz `
	--output path/to/custom_process.stil.gz `
	--free-drive-time 1ms `
	--tap-period 10ns
```

## Transformation

For each of the 16 original `dps_trigger: 0` instructions, block index $i$ ranges from $0$ to $15$ and the following sequence is produced:

1. Keep `dps_trigger: 0`.
2. Add `label:waiting_after_trigger0_i`.
3. Add a free-drive Loop containing a copy of the preceding `V {}` block.
4. In that copy only, force `UART_RXD_DRD` to `0`; all other values remain unchanged.
5. Add `label:start_stress_i` and an empty stress Loop.
6. Add `dps_trigger: 1`.
7. Add `label:waiting_after_trigger1_i` and another empty free-drive Loop.
8. Retain the customer's original vectors after the inserted sequence.

The trigger IDs remain `0` and `1` in every block. The label suffix identifies the block.

### Loop calculations

$$
N_{free} = \frac{freedrivetime + 0.2\,ms}{tapperiod}
$$

$$
N_{stress} = \frac{100\,ms / 16}{tapperiod}
$$

With `freedrivetime=1ms` and `tapperiod=10ns`:

- Free-drive Loop count: `120000`
- Stress Loop count: `625000`

Both results must be exact integers. The program stops with an error rather than rounding.

## Safety checks

The CLI refuses to generate output when:

- The input does not contain the expected number of trigger blocks.
- `UART_RXD_DRD` cannot be uniquely resolved in `_bidi_`.
- A trigger has no preceding complete `V {}` block.
- A Loop count is not an exact positive integer.
- The input already contains generated waiting labels.
- The requested output path would overwrite the source.

Customer STIL files and generated `*_process.stil*` files are intentionally excluded from this repository.

## Tests

Run the standard-library unit tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

The tests cover duration calculations, output naming, plain vector replacement, and run-length encoded vector replacement.
