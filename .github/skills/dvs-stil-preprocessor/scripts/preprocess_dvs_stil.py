#!/usr/bin/env python3
"""Insert DVS trigger wait/stress sequences into a STIL body file."""

from __future__ import annotations

import argparse
import gzip
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


TRIGGER_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)Ann\s*\{\*\s*SE_CMD\s+dps_trigger:\s*0;\s*\*\}(?P<eol>\r?\n|$)"
)
V_BLOCK_RE = re.compile(r"(?ms)^[ \t]*V\s*\{.*?^[ \t]*\}")
BIDI_ASSIGN_RE = re.compile(r"(?s)(\b_bidi_\s*=\s*)(.*?)(;)")
BIDI_GROUP_RE = re.compile(r"(?s)\b_bidi_\s*=\s*(.*?);")
SIGNAL_RE = re.compile(r'"([^"\r\n]+)"(?:\s*\[\s*(\d+)\s*\])?')
RLE_RE = re.compile(r"\\r(\d+)\s+(\S)")
DURATION_RE = re.compile(
    r"^\s*(?P<number>(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<unit>ns|us|µs|ms|s)\s*$",
    re.IGNORECASE,
)
UNIT_TO_NS = {
    "ns": Decimal("1"),
    "us": Decimal("1000"),
    "µs": Decimal("1000"),
    "ms": Decimal("1000000"),
    "s": Decimal("1000000000"),
}
PATTERN_SIGNALS = {
    "CCD": (
        "I2C_IPMI_SCL",
        "STIMER_CCDNE1",
        "UART_RXD_CCD_L_S",
        "UART_RXD_CCD_S",
    ),
    "IOD": (
        "UART_RXD_IOD",
        "AVSBUS_SDATA0",
    ),
    "DRD": ("UART_RXD_DRD",),
}


@dataclass(frozen=True)
class TransformResult:
    text: str
    block_count: int
    pre_trigger_loops: int
    free_drive_loops: int
    stress_loops: int
    pattern_type: str
    bidi_signals: tuple[str, ...]
    bidi_positions: tuple[int, ...]


def parse_duration_ns(value: str) -> Decimal:
    match = DURATION_RE.fullmatch(value)
    if not match:
        raise ValueError(
            f"Invalid duration {value!r}; use a value with ns, us, ms, or s (for example: 10ns or 1ms)."
        )
    try:
        number = Decimal(match.group("number"))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric duration {value!r}.") from exc
    if number <= 0:
        raise ValueError(f"Duration must be greater than zero: {value!r}.")
    return number * UNIT_TO_NS[match.group("unit").lower()]


def exact_loop_count(duration_ns: Decimal, tap_period_ns: Decimal, name: str) -> int:
    quotient = duration_ns / tap_period_ns
    integral = quotient.to_integral_value()
    if quotient != integral:
        raise ValueError(
            f"{name} does not produce an integer loop count: {duration_ns}ns / "
            f"{tap_period_ns}ns = {quotient}."
        )
    if integral <= 0:
        raise ValueError(f"{name} loop count must be greater than zero.")
    return int(integral)


def read_text(path: Path) -> str:
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        return stream.read()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="") as stream:
        stream.write(text)


def default_output_path(input_path: Path) -> Path:
    name = input_path.name
    if name.lower().endswith(".stil.gz"):
        name = f"{name[:-8]}_process.stil.gz"
    elif name.lower().endswith(".stil"):
        name = f"{name[:-5]}_process.stil"
    else:
        name = f"{name}_process"
    return input_path.with_name(name)


def find_signal_position(text: str, signal_name: str) -> int:
    group_match = BIDI_GROUP_RE.search(text)
    if not group_match:
        raise ValueError("Could not find the _bidi_ signal-group definition.")
    signals = [match.group(1) for match in SIGNAL_RE.finditer(group_match.group(1))]
    matches = [index for index, name in enumerate(signals) if name == signal_name]
    if not matches:
        raise ValueError(f"Signal {signal_name!r} is not present in the _bidi_ group.")
    if len(matches) != 1:
        raise ValueError(f"Signal {signal_name!r} occurs more than once in the _bidi_ group.")
    return matches[0]


def replace_vector_symbol(expression: str, zero_based_index: int, new_symbol: str) -> str:
    position = 0
    cursor = 0
    while cursor < len(expression):
        if expression[cursor].isspace():
            cursor += 1
            continue

        rle = RLE_RE.match(expression, cursor)
        if rle:
            count = int(rle.group(1))
            if zero_based_index < position + count:
                offset = zero_based_index - position
                parts: list[str] = []
                if offset:
                    parts.append(f"\\r{offset} {rle.group(2)}")
                parts.append(new_symbol)
                remaining = count - offset - 1
                if remaining:
                    parts.append(f"\\r{remaining} {rle.group(2)}")
                return expression[:cursor] + " ".join(parts) + expression[rle.end():]
            position += count
            cursor = rle.end()
            continue

        if position == zero_based_index:
            return expression[:cursor] + new_symbol + expression[cursor + 1 :]
        position += 1
        cursor += 1

    raise ValueError(
        f"_bidi_ vector has only {position} expanded symbols; cannot set position {zero_based_index + 1}."
    )


def force_bidi_signals(v_block: str, signal_positions: tuple[int, ...], value: str) -> str:
    match = BIDI_ASSIGN_RE.search(v_block)
    if not match:
        raise ValueError("The Vector copied before a trigger has no _bidi_ assignment.")
    changed = match.group(2)
    for signal_position in signal_positions:
        changed = replace_vector_symbol(changed, signal_position, value)
    return v_block[: match.start(2)] + changed + v_block[match.end(2) :]


def indent_block(block: str, prefix: str) -> str:
    return "\n".join(prefix + line if line else line for line in block.splitlines())


def previous_v_block(text: str, before: int) -> str:
    previous = None
    for match in V_BLOCK_RE.finditer(text, 0, before):
        previous = match
    if previous is None:
        raise ValueError("No complete V block exists before a dps_trigger: 0 instruction.")
    return previous.group(0)


def build_insertion(
    trigger_line: str,
    copied_v: str,
    pre_trigger_loops: int,
    free_drive_loops: int,
    stress_loops: int,
    block_index: int,
    indent: str,
    newline: str,
) -> str:
    copied_lines = indent_block(copied_v.lstrip(" \t"), indent + "  ").replace("\n", newline)
    lines = [
        f"{indent}Ann {{* SE_CMD label:waiting_before_trigger0_{block_index}; *}}",
        f"{indent}Loop {pre_trigger_loops} {{",
        copied_lines,
        f"{indent}}}  // end loop",
        trigger_line.rstrip("\r\n"),
        f"{indent}Ann {{* SE_CMD label:waiting_after_trigger0_{block_index}; *}}",
        f"{indent}Loop {free_drive_loops} {{",
        f"{indent}  V {{",
        f"{indent}  }}",
        f"{indent}}}  // end loop",
        f"{indent}Ann {{* SE_CMD label:start_stress_{block_index}; *}}",
        f"{indent}Loop {stress_loops} {{",
        f"{indent}  V {{",
        f"{indent}  }}",
        f"{indent}}}  // end loop",
        f"{indent}Ann {{* SE_CMD label:waiting_before_trigger1_{block_index}; *}}",
        f"{indent}Loop {pre_trigger_loops} {{",
        f"{indent}  V {{",
        f"{indent}  }}",
        f"{indent}}}  // end loop",
        f"{indent}Ann {{* SE_CMD dps_trigger: 1; *}}",
        f"{indent}Ann {{* SE_CMD label:waiting_after_trigger1_{block_index}; *}}",
        f"{indent}Loop {free_drive_loops} {{",
        f"{indent}  V {{",
        f"{indent}  }}",
        f"{indent}}}  // end loop",
    ]
    return newline.join(lines) + newline


def transform(
    text: str,
    free_drive_time: str,
    tap_period: str,
    *,
    expected_blocks: int = 16,
    total_stress_time: str = "100ms",
    release_offset: str = "0.2ms",
    pre_trigger_loops: int = 20000,
    minimum_wait_loops: int = 100000,
    pattern_type: str = "DRD",
) -> TransformResult:
    if "SE_CMD label:waiting_after_trigger0" in text:
        raise ValueError("Input appears to be already preprocessed; refusing to insert duplicate sequences.")

    trigger_matches = list(TRIGGER_RE.finditer(text))
    if len(trigger_matches) != expected_blocks:
        raise ValueError(
            f"Expected {expected_blocks} dps_trigger: 0 blocks, but found {len(trigger_matches)}."
        )
    if pre_trigger_loops <= 0:
        raise ValueError("Pre-trigger loop count must be greater than zero.")
    if minimum_wait_loops <= 0:
        raise ValueError("Minimum waiting loop count must be greater than zero.")
    pattern_type = pattern_type.upper()
    if pattern_type not in PATTERN_SIGNALS:
        raise ValueError(
            f"Unsupported pattern type {pattern_type!r}; choose CCD, IOD, or DRD."
        )

    tap_ns = parse_duration_ns(tap_period)
    free_ns = parse_duration_ns(free_drive_time) + parse_duration_ns(release_offset)
    total_stress_ns = parse_duration_ns(total_stress_time)
    calculated_free_drive_loops = exact_loop_count(free_ns, tap_ns, "free-drive time")
    free_drive_loops = max(calculated_free_drive_loops, minimum_wait_loops)
    stress_loops = exact_loop_count(
        total_stress_ns / Decimal(expected_blocks), tap_ns, "per-block stress time"
    )
    bidi_signals = PATTERN_SIGNALS[pattern_type]
    signal_positions = tuple(find_signal_position(text, signal) for signal in bidi_signals)

    chunks: list[str] = []
    cursor = 0
    for block_index, trigger in enumerate(trigger_matches):
        copied_v = force_bidi_signals(
            previous_v_block(text, trigger.start()), signal_positions, "0"
        )
        newline = "\r\n" if trigger.group("eol") == "\r\n" else "\n"
        chunks.append(text[cursor : trigger.start()])
        chunks.append(
            build_insertion(
                trigger.group(0),
                copied_v,
                pre_trigger_loops,
                free_drive_loops,
                stress_loops,
                block_index,
                trigger.group("indent"),
                newline,
            )
        )
        cursor = trigger.end()
    chunks.append(text[cursor:])

    return TransformResult(
        text="".join(chunks),
        block_count=len(trigger_matches),
        pre_trigger_loops=pre_trigger_loops,
        free_drive_loops=free_drive_loops,
        stress_loops=stress_loops,
        pattern_type=pattern_type,
        bidi_signals=bidi_signals,
        bidi_positions=tuple(position + 1 for position in signal_positions),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preprocess a DVS STIL body by expanding each dps_trigger: 0 block."
    )
    parser.add_argument("input", type=Path, help="Input .stil or .stil.gz file")
    parser.add_argument("--output", "-o", type=Path, help="Output path (default: *_process.stil[.gz])")
    parser.add_argument("--free-drive-time", required=True, help="Free-drive duration, e.g. 1ms")
    parser.add_argument("--tap-period", required=True, help="TAP period, e.g. 10ns")
    parser.add_argument("--expected-blocks", type=int, default=16)
    parser.add_argument("--total-stress-time", default="100ms")
    parser.add_argument("--release-offset", default="0.2ms")
    parser.add_argument("--pre-trigger-loops", type=int, default=20000)
    parser.add_argument("--minimum-wait-loops", type=int, default=100000)
    parser.add_argument("--pattern-type", required=True, choices=tuple(PATTERN_SIGNALS))
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.input.is_file():
            raise ValueError(f"Input file does not exist: {args.input}")
        if args.expected_blocks <= 0:
            raise ValueError("--expected-blocks must be greater than zero.")
        text = read_text(args.input)
        result = transform(
            text,
            args.free_drive_time,
            args.tap_period,
            expected_blocks=args.expected_blocks,
            total_stress_time=args.total_stress_time,
            release_offset=args.release_offset,
            pre_trigger_loops=args.pre_trigger_loops,
            minimum_wait_loops=args.minimum_wait_loops,
            pattern_type=args.pattern_type,
        )
        output = args.output or default_output_path(args.input)
        if not args.dry_run:
            if output.resolve() == args.input.resolve():
                raise ValueError("Output must differ from input; the source file is never overwritten.")
            write_text(output, result.text)
        print(f"Blocks processed: {result.block_count}")
        print(f"Pre-trigger loop count: {result.pre_trigger_loops}")
        print(f"Free-drive loop count: {result.free_drive_loops}")
        print(f"Stress loop count: {result.stress_loops}")
        print(f"Pattern type: {result.pattern_type}")
        for signal, position in zip(result.bidi_signals, result.bidi_positions):
            print(f"Forced signal: {signal} (bidi position {position})")
        print("Output: not written (dry run)" if args.dry_run else f"Output: {output}")
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
