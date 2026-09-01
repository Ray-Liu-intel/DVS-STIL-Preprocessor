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
