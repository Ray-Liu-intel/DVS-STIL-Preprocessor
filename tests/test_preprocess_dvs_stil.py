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
