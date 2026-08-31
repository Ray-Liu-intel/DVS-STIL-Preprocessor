# DVS STIL Preprocessor

A GitHub Copilot skill and dependency-free Python CLI for preprocessing DVS STIL body files. It expands 16 DPS trigger points into indexed free-drive and stress sequences while preserving the original customer vectors.

## Highlights

- Reads plain `.stil` and gzip-compressed `.stil.gz` files.
- Preserves the source file and writes `*_process.stil` or `*_process.stil.gz`.
- Calculates Loop counts exactly from free-drive time and TAP period.
- Adds a 20,000-cycle copied Vector before every `dps_trigger: 0` and `dps_trigger: 1` instruction.
- Enforces a minimum of 100,000 cycles for each waiting-after-trigger Loop.
- Generates unique label suffixes from `0` through `15`.
- Supports CCD, IOD, and DRD pattern-specific pin profiles.
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
- An `_bidi_` signal-group definition containing every signal required by the selected pattern type

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
3. Pattern type: `CCD`, `IOD`, or `DRD`.

Supported units are `ns`, `us`, `µs`, `ms`, and `s`.

## CLI usage

Run a validation-only pass first:

```powershell
python .github/skills/dvs-stil-preprocessor/scripts/preprocess_dvs_stil.py `
	path/to/DVS_body.stil.gz `
	--free-drive-time 1ms `
	--tap-period 10ns `
	--pattern-type DRD `
	--dry-run
```

Generate the processed file:

```powershell
python .github/skills/dvs-stil-preprocessor/scripts/preprocess_dvs_stil.py `
	path/to/DVS_body.stil.gz `
	--free-drive-time 1ms `
	--tap-period 10ns `
	--pattern-type DRD
```

For an input named `DVS_body.stil.gz`, the default output is `DVS_body_process.stil.gz`.

An explicit output path can be provided with `--output`:

```powershell
python .github/skills/dvs-stil-preprocessor/scripts/preprocess_dvs_stil.py `
	path/to/DVS_body.stil.gz `
	--output path/to/custom_process.stil.gz `
	--free-drive-time 1ms `
	--tap-period 10ns `
	--pattern-type DRD
```

## Transformation

For each of the 16 original `dps_trigger: 0` instructions, block index $i$ ranges from $0$ to $15$ and the following sequence is produced:

1. Add `label:waiting_before_trigger0_i` and a 20,000-cycle Loop containing a copy of the preceding `V {}` block.
2. In that pre-trigger copy only, force the selected pattern type's pins to `0`; all other values remain unchanged.
3. Keep `dps_trigger: 0`.
4. Add `label:waiting_after_trigger0_i` and an empty free-drive Loop.
5. Add `label:start_stress_i` and an empty stress Loop.
6. Add `label:waiting_before_trigger1_i` and another 20,000-cycle Loop containing the same modified copied Vector.
7. Add `dps_trigger: 1`.
8. Add `label:waiting_after_trigger1_i` and another empty free-drive Loop.
9. Retain the customer's original vectors after the inserted sequence.

Pin profiles:

- `CCD`: `I2C_IPMI_SCL`, `STIMER_CCDNE1`, `UART_RXD_CCD_L_S`, `UART_RXD_CCD_S`
- `IOD`: `UART_RXD_IOD`, `AVSBUS_SDATA0`
- `DRD`: `UART_RXD_DRD`

The trigger IDs remain `0` and `1` in every block. The label suffix identifies the block.

### Loop calculations

$$
N_{free} = \max\left(\frac{freedrivetime + 0.2\,ms}{tapperiod}, 100000\right)
$$

$$
N_{stress} = \frac{100\,ms / 16}{tapperiod}
$$

With `freedrivetime=1ms` and `tapperiod=10ns`:

- Free-drive Loop count: `120000`
- Stress Loop count: `625000`

Both results must be exact integers. The program stops with an error rather than rounding.

With `freedrivetime=1ms` and `tapperiod=20ns`, the calculated waiting count is `60000`, so the enforced waiting count is `100000`; the stress Loop count is `312500`.

## Safety checks

The CLI refuses to generate output when:

- The input does not contain the expected number of trigger blocks.
- A required pin for the selected pattern type cannot be uniquely resolved in `_bidi_`.
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
