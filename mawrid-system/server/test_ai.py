import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("mawrid_ai", Path(__file__).with_name("ai.py"))
ai = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai)


class AdapterTests(unittest.TestCase):
    def test_reject_arbitrary_source_before_import_or_io(self):
        engine = ai.ResearchEngine()
        with patch.object(Path, "read_text", side_effect=AssertionError("no IO")):
            for source in ("telemetry", "../../bundle", "V12", None):
                with self.assertRaises(ValueError):
                    engine.start(source)

    def test_step_requires_ready_session_and_valid_bounded_count(self):
        engine = ai.ResearchEngine()
        for count in (True, 0, -1, 26, 1.5, "5"):
            with self.assertRaises(ValueError):
                engine.step(count)
        with self.assertRaises(ValueError):
            engine.step(1)

    def test_no_claim_of_acceptance_or_safe_water(self):
        state = ai.ResearchEngine().status()
        self.assertIs(state["acceptance_passed"], False)
        self.assertIsNone(state["provenance"])
        self.assertEqual(state["metrics"]["events_detected"], 113)

    def test_finite_json_null(self):
        self.assertEqual(ai.finite(0), 0)
        self.assertIsNone(ai.finite(float("nan")))
        self.assertIsNone(ai.finite(float("inf")))


if __name__ == "__main__":
    unittest.main()
