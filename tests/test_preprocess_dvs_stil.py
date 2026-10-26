import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / ".github"
    / "skills"
    / "dvs-stil-preprocessor"
    / "scripts"
    / "preprocess_dvs_stil.py"
)
SPEC = importlib.util.spec_from_file_location("preprocess_dvs_stil", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PreprocessorTests(unittest.TestCase):
    def test_min_period_per_cycle_cli_and_legacy_alias(self):
        parser = MODULE.build_parser()
        for flag in ("--min-period-per-cycle", "--tap-period"):
            with self.subTest(flag=flag):
                args = parser.parse_args([
                    "sample.stil.gz", "--free-drive-time", "1ms", flag, "10ns",
                    "--pattern-type", "IOD", "--dry-run",
                ])
                self.assertEqual(args.min_period_per_cycle, "10ns")

    def test_duration_and_loop_calculation(self):
        tap = MODULE.parse_duration_ns("10ns")
        free = MODULE.parse_duration_ns("1ms") + MODULE.parse_duration_ns("0.2ms")
        self.assertEqual(MODULE.exact_loop_count(free, tap, "free"), 120000)
        self.assertEqual(
            MODULE.exact_loop_count(MODULE.parse_duration_ns("100ms") / 16, tap, "stress"),
            625000,
        )

    def test_wait_loop_uses_minimum_of_100000(self):
        tap = MODULE.parse_duration_ns("20ns")
        free = MODULE.parse_duration_ns("1ms") + MODULE.parse_duration_ns("0.2ms")
        calculated = MODULE.exact_loop_count(free, tap, "free")
        self.assertEqual(calculated, 60000)
        self.assertEqual(max(calculated, 100000), 100000)

    def test_insertion_adds_indexed_pre_trigger_loop(self):
        insertion = MODULE.build_insertion(
            "Ann {* SE_CMD dps_trigger: 0; *}\n",
            "V {  _bidi_=X;\n}",
            20000,
            100000,
            312500,
            3,
            "",
            "\n",
        )
        self.assertIn("label:waiting_before_trigger0_3;", insertion)
        self.assertLess(
            insertion.index("label:waiting_before_trigger0_3;"),
            insertion.index("dps_trigger: 0;"),
        )
        self.assertLess(
            insertion.index("label:waiting_before_trigger1_3;"),
            insertion.index("dps_trigger: 1;"),
        )
        self.assertEqual(insertion.count("Loop 20000 {"), 2)
        self.assertEqual(insertion.count("_bidi_=X;"), 1)
        self.assertLess(insertion.index("_bidi_=X;"), insertion.index("dps_trigger: 0;"))
        before_trigger1 = insertion[
            insertion.index("label:waiting_before_trigger1_3;") : insertion.index("dps_trigger: 1;")
        ]
        self.assertIn("Loop 20000 {\n  V {\n  }\n}", before_trigger1)
        self.assertNotIn("_bidi_", before_trigger1)
        self.assertEqual(insertion.count("Loop 100000 {"), 2)

    def test_pattern_signal_profiles(self):
        self.assertEqual(MODULE.PATTERN_SIGNALS["DRD"], ("UART_RXD_DRD",))
        self.assertEqual(
            MODULE.PATTERN_SIGNALS["IOD"],
            ("UART_RXD_IOD", "AVSBUS_SDATA0"),
        )
        self.assertEqual(
            MODULE.PATTERN_SIGNALS["CCD"],
            ("I2C_IPMI_SCL", "STIMER_CCDNE1", "UART_RXD_CCD_L_S", "UART_RXD_CCD_S"),
        )

    def test_force_multiple_bidi_signals(self):
        block = "V {  _bidi_=X11X1;\n}"
        self.assertEqual(
            MODULE.force_bidi_signals(block, (1, 3), "0"),
            "V {  _bidi_=X0101;\n}",
        )

    def test_mask_bidi_high_low_including_run_lengths(self):
        block = "V { _bidi_=HL01X \\r3 H \\r2 L \\r4 1; _po_=01; }"
        self.assertEqual(
            MODULE.mask_bidi_high_low(block),
            "V { _bidi_=XX01X \\r3 X \\r2 X \\r4 1; _po_=01; }",
        )

    def test_mask_bidi_then_force_zero_takes_precedence(self):
        block = "V { _bidi_=H \\r2 L; _po_=01; }"
        masked = MODULE.mask_bidi_high_low(block)
        self.assertIn("_bidi_=X \\r2 X;", masked)
        self.assertIn("_bidi_=0 \\r1 X 0;", MODULE.force_bidi_signals(masked, (0, 2), "0"))

    def test_mask_bidi_rejects_invalid_run_lengths_and_duplicates(self):
        for block in ("V { _bidi_=\\r0 H; }", "V { _bidi_=\\q2 L; }",
                      "V { _bidi_=HL; _bidi_=10; }"):
            with self.subTest(block=block), self.assertRaises(ValueError):
                MODULE.mask_bidi_high_low(block)

    def test_forced_pin_resolves_to_pi_when_not_in_bidi(self):
        text = '_bidi_ = "OTHER";\n_pi_ = "UART_RXD_DRD" + "ANOTHER";\n'
        self.assertEqual(MODULE.find_signal_location(text, "UART_RXD_DRD"), ("_pi_", 0))
        for definitions in ('_bidi_ = "OTHER";\n_pi_ = "OTHER_PI";\n',
                            '_bidi_ = "UART_RXD_DRD";\n_pi_ = "UART_RXD_DRD";\n',
                            '_pi_ = "UART_RXD_DRD" + "UART_RXD_DRD";\n'):
            with self.subTest(definitions=definitions), self.assertRaises(ValueError):
                MODULE.find_signal_location(definitions, "UART_RXD_DRD")

    def test_transform_mixed_ccd_groups_and_rle(self):
        definitions = (
            '_bidi_ = "I2C_IPMI_SCL" + "OTHER" + "STIMER_CCDNE1";\n'
            '_pi_ = "UART_RXD_CCD_L_S" + "OTHER_PI" + "UART_RXD_CCD_S";\n'
        )
        original = "V {\n _bidi_=H \\r2 L;\n _pi_=\\r3 H;\n _po_=0L;\n}\n"
        text = definitions + (original + "Ann {* SE_CMD dps_trigger: 0; *}\n") * 16
        result = MODULE.transform(text, "1ms", "10ns", pattern_type="CCD")
        self.assertEqual(result.signal_groups, ("_bidi_", "_bidi_", "_pi_", "_pi_"))
        self.assertEqual(result.bidi_positions, (1, 3, 1, 3))
        self.assertEqual(result.text.count("_bidi_=0 \\r1 X 0;"), 16)
        self.assertEqual(result.text.count("_pi_=0 \\r1 H 0;"), 16)
        self.assertEqual(result.text.count("_po_=XX;"), 16)
        self.assertEqual(result.text.count(original), 16)

    def test_transform_drd_pi_only_and_missing_pi_assignment(self):
        definitions = '_pi_ = "UART_RXD_DRD";\n'
        original = "V {\n _pi_=H;\n _po_=L;\n}\n"
        text = definitions + (original + "Ann {* SE_CMD dps_trigger: 0; *}\n") * 16
        result = MODULE.transform(text, "1ms", "10ns", pattern_type="DRD")
        self.assertEqual(result.signal_groups, ("_pi_",))
        self.assertEqual(result.text.count("_pi_=0;"), 16)
        self.assertEqual(result.text.count(original), 16)
        with self.assertRaisesRegex(ValueError, "_pi_ assignment"):
            MODULE.transform(text.replace(" _pi_=H;", ""), "1ms", "10ns", pattern_type="DRD")

    def test_min_period_per_cycle_keyword_calculates_loop_counts(self):
        text = '_pi_ = "UART_RXD_DRD";\n' + (
            "V {\n _pi_=H;\n _po_=L;\n}\n"
            "Ann {* SE_CMD dps_trigger: 0; *}\n"
        ) * 16
        result = MODULE.transform(text, "1ms", min_period_per_cycle="20ns", pattern_type="DRD")
        self.assertEqual(result.free_drive_loops, 100000)
        self.assertEqual(result.stress_loops, 312500)

    def test_mask_po_plain_and_run_length_preserves_layout(self):
        block = "V {\n  _pi_=01;\n  _po_=0 1\\r3 H\n X;\n  _bidi_=X11;\n}"
        self.assertEqual(
            MODULE.mask_po_signals(block),
            "V {\n  _pi_=01;\n  _po_=X X\\r3 X\n X;\n  _bidi_=X11;\n}",
        )

    def test_mask_po_rejects_missing_empty_and_invalid_data(self):
        for expression in (None, "  ", r"\r0 1", r"\q3 1"):
            block = "V { _bidi_=11; " + (
                "" if expression is None else f"_po_={expression};"
            ) + " }"
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                MODULE.mask_po_signals(block)

    def test_transform_masks_only_pre_trigger_copy_in_all_16_blocks(self):
        original = "V {\n  _pi_=01;\n  _bidi_=X1X;\n  _po_=01\\r3 1;\n}\n"
        text = '_bidi_ = "A" + "UART_RXD_DRD" + "B";\n' + (
            original + "Ann {* SE_CMD dps_trigger: 0; *}\n"
        ) * 16
        result = MODULE.transform(text, "1ms", "10ns", pattern_type="DRD")
        self.assertEqual(result.block_count, 16)
        self.assertEqual(result.text.count("_po_=XX\\r3 X;"), 16)
        self.assertEqual(result.text.count("_bidi_=X0X;"), 16)
        self.assertEqual(result.text.count(original), 16)
        self.assertEqual(result.text.count("_po_=01\\r3 1;"), 16)
        self.assertEqual(result.text.count("_pi_=01;"), 32)

    def test_default_output_uses_process_suffix(self):
        self.assertEqual(
            MODULE.default_output_path(Path("sample.stil.gz")),
            Path("sample_process.stil.gz"),
        )
        self.assertEqual(
            MODULE.default_output_path(Path("sample.stil")),
            Path("sample_process.stil"),
        )

    def test_replace_plain_vector_symbol(self):
        self.assertEqual(MODULE.replace_vector_symbol("X11X", 1, "0"), "X01X")

    def test_replace_run_length_encoded_symbol(self):
        self.assertEqual(
            MODULE.replace_vector_symbol(r"X \r3 1 X", 2, "0"),
            r"X \r1 1 0 \r1 1 X",
        )


if __name__ == "__main__":
    unittest.main()
