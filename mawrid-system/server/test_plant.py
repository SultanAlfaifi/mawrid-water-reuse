"""Synthetic inventory/interlock tests only; no source, model, DB or HTTP."""
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
import json
import math
import unittest

from .plant import PlantSimulator


class PlantTests(unittest.TestCase):
    def plant(self):
        return PlantSimulator("2026-10-17T00:00:00Z")

    def balanced(self, snap):
        v = snap["volumes"]
        lhs = v["initial_stored_liters"] + v["input_liters"]
        rhs = sum(v[k] for k in ("stored_liters", "reuse_liters", "reject_drain_liters", "overflow_liters", "backwash_liters"))
        self.assertLessEqual(abs(lhs - rhs), 1e-8)
        self.assertLessEqual(abs(v["balance_error_liters"]), 1e-8)
        for tank in snap["tanks"].values():
            self.assertGreaterEqual(tank["liters"], 0)
            self.assertLessEqual(tank["liters"], tank["capacity_liters"])
        for key, value in v.items():
            if key != "balance_error_liters":
                self.assertGreaterEqual(value, 0)
        json.dumps(snap, allow_nan=False)

    def test_initial_contract_explicit_virtual_and_no_model(self):
        s = self.plant().snapshot()
        self.assertEqual((s["source"], s["virtual"], s["hardware"]), ("virtual_plant", True, False))
        self.assertEqual(s["tanks"]["raw"]["liters"], 3000)
        self.assertEqual(s["tanks"]["treated"]["liters"], 2000)
        self.assertTrue(all(t["capacity_liters"] == 5000 for t in s["tanks"].values()))
        self.assertEqual(len(s["chans"]), 9)
        self.assertIsNone(s["design_assumptions"]["model_inference"])
        self.assertFalse(s["design_assumptions"]["ai_controls_valves"])
        self.balanced(s)

    def test_one_hour_feed_recovery_reject_and_reuse(self):
        p = self.plant()
        for _ in range(12): s = p.step(300)
        v = s["volumes"]
        for key, expected in {"input_liters": 1000, "treatment_feed_liters": 1000,
                              "treated_product_liters": 1000, "reject_drain_liters": 0,
                              "reuse_liters": 1000}.items():
            self.assertAlmostEqual(v[key], expected, places=10)
        self.assertEqual(s["tanks"]["raw"]["liters"], 3000)
        self.assertEqual(s["tanks"]["treated"]["liters"], 2000)
        self.assertEqual(s["timestamp"], "2026-10-17T01:00:00Z")
        self.balanced(s)

    def test_hundreds_steps_matched_flows_keep_stable_stocks(self):
        p = self.plant()
        for _ in range(1200): self.balanced(p.step(300))
        s = p.snapshot()
        self.assertEqual(s["tanks"]["raw"]["liters"], 3000)
        self.assertEqual(s["tanks"]["treated"]["liters"], 2000)
        self.assertEqual(s["volumes"]["overflow_liters"], 0)
        self.assertEqual(s["volumes"]["reject_drain_liters"], 0)

    def test_full_tank_boundary_fixture_accounts_overflow_separately(self):
        p = self.plant(); p._raw = p._treated = Decimal(5000); p._initial_stored = Decimal(10000)
        operation = p._operation
        def high_inlet_no_reuse():
            state = operation(); state[2]["inlet"] *= 2; state[2]["reuse"] = Decimal(0)
            return state
        # Boundary fixture for the stock integrator, not a user-facing mode.
        with patch.object(p, "_operation", side_effect=high_inlet_no_reuse): s = p.step(300)
        self.assertEqual(s["tanks"]["raw"]["liters"], 5000)
        self.assertEqual(s["tanks"]["treated"]["liters"], 5000)
        self.assertGreater(s["volumes"]["raw_overflow_liters"], 0)
        self.assertGreater(s["volumes"]["treated_overflow_liters"], 0)
        self.assertAlmostEqual(s["volumes"]["overflow_liters"], s["volumes"]["raw_overflow_liters"] + s["volumes"]["treated_overflow_liters"])
        self.balanced(s)

    def test_empty_tanks_and_overdraw_bounded(self):
        p = self.plant()
        # Boundary fixture only; public constructor always uses3000/2000.
        p._raw = p._treated = p._initial_stored = Decimal(0)
        s = p.step(300)
        self.assertAlmostEqual(s["tanks"]["raw"]["liters"], 0)
        self.assertAlmostEqual(s["tanks"]["treated"]["liters"], 0)
        self.balanced(s)
        p.set_control({"mode": "backwash"})
        s = p.step(300)
        self.assertEqual(s["tanks"]["treated"]["liters"], 0)
        self.assertEqual(s["flow"]["backwash_lpm"], 0)
        self.assertEqual(s["safety"]["state"], "HOLD")
        self.balanced(s)

    def test_backwash_accounts_every_liter_and_stops_at_empty(self):
        p = self.plant(); s = p.set_control({"mode": "backwash"})
        self.assertEqual(s["flow"]["backwash_lpm"], 65)
        self.assertEqual(s["equipment"]["irrigation_valve"], "closed")
        for _ in range(20): self.balanced(p.step(300))
        s = p.snapshot()
        self.assertEqual(s["volumes"]["backwash_liters"], 2000)
        self.assertEqual(s["volumes"]["reuse_liters"], 0)
        self.assertEqual(s["volumes"]["reject_drain_liters"], 0)
        self.assertEqual(s["tanks"]["raw"]["liters"], 3000)
        self.assertEqual(s["equipment"]["drain_valve"], "closed")

    def test_each_fault_immediately_holds_for_observable_reason(self):
        expected = {"turbidity": "TURBIDITY_HIGH", "sensor_dropout": "QUALITY_SENSOR_INVALID",
                    "clogging": "FILTER_DIFFERENTIAL_HIGH", "power_loss": "POWER_LOSS",
                    "valve_stuck": "VALVE_COMMAND_FEEDBACK_MISMATCH"}
        for fault, code in expected.items():
            with self.subTest(fault=fault):
                p = self.plant(); before = p.snapshot(); s = p.set_control({"fault": fault})
                self.assertEqual(s["elapsed_seconds"], before["elapsed_seconds"])
                self.assertEqual(s["volumes"], before["volumes"])
                self.assertEqual(s["safety"]["state"], "HOLD")
                self.assertIn(code, s["safety"]["reason_codes"])
                self.assertFalse(s["safety"]["reuse_permitted"])
                self.assertTrue(all(v == 0 for v in s["flow"].values()))
                self.assertEqual(s["equipment"]["irrigation_valve"], "closed")
                after = p.step(300)
                self.assertEqual(after["volumes"], before["volumes"])
                self.balanced(after)

    def test_pressure_sensor_and_quality_fault_values(self):
        p = self.plant()
        s = p.set_control({"fault": "clogging"})
        self.assertGreater(s["chans"]["p1_bar"] - s["chans"]["p2_bar"], 0.9)
        s = p.set_control({"fault": "turbidity"})
        self.assertGreater(s["chans"]["turbidity"], 2)
        s = p.set_control({"fault": "sensor_dropout"})
        self.assertIsNone(s["chans"]["chlorine"])
        self.assertFalse(s["validity"]["chlorine"])
        self.assertTrue(s["validity"]["orp"])
        self.assertFalse(s["safety"]["reuse_permitted"])

    def test_power_loss_stops_both_nc_valves_and_all_pumps_in_all_modes(self):
        for mode in ("auto", "standby", "backwash"):
            p = self.plant(); s = p.set_control({"mode": mode, "fault": "power_loss"})
            self.assertFalse(s["equipment"]["power"])
            for key, value in s["equipment"].items():
                if key.endswith("pump") or key.endswith("pumps"): self.assertEqual(value, "stopped")
            for key in ("irrigation_valve", "drain_valve", "irrigation_command", "irrigation_feedback"):
                self.assertEqual(s["equipment"][key], "closed")
            self.assertTrue(all(value == 0 for value in s["flow"].values()))
            self.balanced(p.step(300))

    def test_failed_closed_valve_command_and_feedback_trip(self):
        p = self.plant(); s = p.set_control({"fault": "valve_stuck"})
        self.assertEqual(s["equipment"]["irrigation_command"], "open")
        self.assertEqual(s["equipment"]["irrigation_feedback"], "closed")
        self.assertEqual(s["flow"]["reuse_lpm"], 0)
        self.assertEqual(s["equipment"]["feed_pump"], "stopped")
        s = p.set_control({"fault": "none"})
        self.assertTrue(s["safety"]["reuse_permitted"])

    def test_manual_hold_persists_across_fault_clear_and_mode_changes(self):
        p = self.plant(); before = p.snapshot(); p.set_manual_hold(True)
        p.set_control({"fault": "turbidity", "mode": "backwash"})
        s = p.set_control({"fault": "none", "mode": "auto"})
        self.assertFalse(s["safety"]["reuse_permitted"])
        self.assertEqual(s["volumes"], before["volumes"])
        self.assertEqual(s["timestamp"], before["timestamp"])
        s = p.set_manual_hold(False)
        self.assertTrue(s["safety"]["reuse_permitted"])

    def test_standby_has_no_flow_or_inventory_change(self):
        p = self.plant(); old = p.snapshot(); p.set_control({"mode": "standby"})
        s = p.step(300)
        self.assertEqual(s["volumes"], old["volumes"])
        self.assertEqual(s["equipment"]["drain_valve"], "closed")
        self.assertEqual(s["safety"]["state"], "STANDBY")

    def test_no_ai_or_threshold_override_can_open_valve(self):
        p = self.plant(); p.set_control({"fault": "sensor_dropout"})
        for change in ({"prediction": 0}, {"ai_safe": True}, {"irrigation_valve": "open"},
                       {"thresholds": {"chlorine_min": 0}}, {"hardware": True}):
            before = p.snapshot()
            with self.assertRaises(ValueError): p.set_control(change)
            self.assertEqual(p.snapshot(), before)
        self.assertFalse(p.snapshot()["safety"]["reuse_permitted"])

    def test_invalid_inputs_are_atomic(self):
        p = self.plant()
        for dt in (-1, 300.001, 10 ** 1000, math.inf, -math.inf, math.nan, True, None, "1", [], {}):
            before = p.snapshot()
            with self.assertRaises(ValueError): p.step(dt)
            self.assertEqual(p.snapshot(), before)
        for change in (None, [], {"mode": []}, {"fault": 1}, {"speed": True}, {"speed": 10.0},
                       {"fault": "turbidity", "speed": 2}, {"mode": "bad"}):
            before = p.snapshot()
            with self.assertRaises(ValueError): p.set_control(change)
            self.assertEqual(p.snapshot(), before)
        for value in (0, 1, "false", None):
            with self.assertRaises(ValueError): p.set_manual_hold(value)

    def test_timestamp_validation_and_timestamp_overflow_atomic(self):
        for start in (None, 1, "", "2026-10-17", "2026-10-17T00:00:00", "2026-10-17T03:00:00+03:00", "bad"):
            with self.assertRaises(ValueError): PlantSimulator(start)
        p = PlantSimulator("9999-12-31T23:59:59Z"); before = p.snapshot()
        with self.assertRaises(ValueError): p.step(2)
        self.assertEqual(p.snapshot(), before)

    def test_snapshot_and_zero_step_are_detached_and_read_only(self):
        p = self.plant(); before = deepcopy(vars(p)); first = p.snapshot()
        self.assertEqual(p.step(0), first)
        self.assertEqual(vars(p), before)
        first["tanks"]["raw"]["liters"] = -999
        first["design_assumptions"]["thresholds"]["ph_min"] = 0
        first["safety"]["reason_codes"].append("fake")
        self.assertEqual(vars(p), before)
        self.assertNotEqual(first, p.snapshot())

    def test_speed_is_metadata_and_deepcopy_is_transaction_friendly(self):
        p, q = self.plant(), self.plant()
        q.set_control({"speed": 30})
        a, b = p.step(30), q.step(30)
        self.assertEqual(a["volumes"], b["volumes"])
        self.assertEqual(a["elapsed_seconds"], b["elapsed_seconds"])
        clone = deepcopy(p); clone.step(60)
        self.assertEqual(p.snapshot(), a)

    def test_partition_invariant_inventory_and_deterministic_smooth_values(self):
        p, q = self.plant(), self.plant()
        p.step(300)
        for _ in range(300): q.step(1)
        a, b = p.snapshot(), q.snapshot()
        self.assertEqual(a["chans"], b["chans"])
        for key in a["volumes"]: self.assertAlmostEqual(a["volumes"][key], b["volumes"][key], places=10)
        last = q.snapshot()["chans"]
        now = q.step(1)["chans"]
        for key in ("turbidity", "ph", "chlorine", "p1_bar"):
            self.assertLess(abs(now[key] - last[key]), .001)

    def test_mixed_control_sequence_conservation(self):
        p = self.plant()
        faults = ("none", "turbidity", "sensor_dropout", "clogging", "power_loss", "valve_stuck")
        for i in range(600):
            p.set_control({"mode": ("auto", "standby", "backwash")[i % 3], "fault": faults[(i // 3) % len(faults)]})
            p.set_manual_hold(i % 13 == 0)
            self.balanced(p.step((i % 300) + .125))

    def test_reference_design_is_not_an_unimplemented_chemical_or_duty_cycle_claim(self):
        p = self.plant(); s = p.snapshot(); d = s["design_assumptions"]
        self.assertEqual(d["rated_feed_lph"] * d["rated_operating_hours_per_day"], 15000)
        self.assertFalse(d["daily_duty_cycle_enforced"])
        self.assertEqual(d["volumetric_recovery"], 1)
        self.assertEqual(s["flow"]["drain_lpm"], 0)
        self.assertEqual(s["flow"]["recirculation_lpm"], 0)
        self.assertEqual(s["equipment"]["compliance_valve"], "product")
        self.assertIn("UV-C", d["design_only_equipment"])
        self.assertNotIn("uv_intensity", s["chans"])
        self.assertNotIn("ec", s["chans"])
        for fault in ("turbidity", "sensor_dropout", "power_loss"):
            s = p.set_control({"fault": fault})
            self.assertEqual(s["equipment"]["compliance_valve"], "closed")
            self.assertTrue(all(v == 0 for v in s["flow"].values()))


if __name__ == "__main__":
    unittest.main()
