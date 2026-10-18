"""Pure deterministic water-plant demonstrator; no I/O, ML or real actuation.

This is an explicitly VIRTUAL fluid inventory model, not a calibrated process
model or a water-safety assessment. 15 m3/day denotes treatment FEED at
1 m3/hour for15 operating hours. The filters have no assumed continuous reject:
normal feed passes volumetrically to product. Quality signals are deterministic
illustrations, not a chemical-removal model. Fixed experimental interlocks may
open only the virtual reuse valve. Public-source AI is completely separate.

``step(dt)`` advances relative simulated seconds; speed is metadata for the
owner's clock and is never applied here. Snapshots are detached JSON values.
The owner can deepcopy the simulator before a database transaction. There are
no threads, wall-clock calls, random generators, hardware or model dependencies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math


FAULTS = frozenset(("none", "turbidity", "sensor_dropout", "clogging", "power_loss", "valve_stuck"))
MODES = frozenset(("auto", "standby", "backwash"))
SPEEDS = frozenset((1, 10, 30))
_ZERO = Decimal(0)
_CAPACITY = Decimal(5000)
_FEED = Decimal(1000) / Decimal(60)
_INLET = _FEED
_RECOVERY = Decimal(1)
_REUSE = _FEED
_BACKWASH = Decimal(65)
_THRESHOLDS = {
    "turbidity_max_ntu": 2.0,
    "ph_min": 6.5, "ph_max": 8.5,
    "chlorine_min_mg_l": 0.2, "chlorine_max_mg_l": 0.5,
    "outlet_pressure_min_bar": 0.8, "outlet_pressure_max_bar": 3.5,
    "line_pressure_max_bar": 5.0, "filter_differential_max_bar": 0.9,
}


class PlantSimulator:
    """In-memory, deterministic simulator with conservative virtual interlocks."""

    def __init__(self, start_timestamp: str):
        if not isinstance(start_timestamp, str):
            raise ValueError("start_timestamp must be an ISO timestamp in UTC")
        try:
            start = datetime.fromisoformat(start_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("start_timestamp must be an ISO timestamp in UTC") from exc
        if start.tzinfo is None or start.utcoffset() != timedelta(0):
            raise ValueError("start_timestamp must explicitly specify UTC")
        self._start = start.astimezone(timezone.utc)
        self._elapsed = _ZERO
        self._raw = Decimal(3000)
        self._treated = Decimal(2000)
        self._initial_stored = self._raw + self._treated
        self._volumes = {key: _ZERO for key in (
            "input_liters", "reuse_liters", "reject_drain_liters",
            "overflow_liters", "backwash_liters", "treatment_feed_liters",
            "treated_product_liters", "raw_overflow_liters", "treated_overflow_liters")}
        self._mode = "auto"
        self._fault = "none"
        self._speed = 1
        self._manual_hold = False

    def set_control(self, control: dict) -> dict:
        """Validate atomically; changes are immediate without advancing time.

        Clearing a fault clears its virtual trip when all current interlocks
        pass; manual hold remains until explicitly reset. Speed never scales dt.
        """
        if not isinstance(control, dict) or set(control) - {"fault", "mode", "speed"}:
            raise ValueError("control supports only fault, mode and speed")
        fault = control.get("fault", self._fault)
        mode = control.get("mode", self._mode)
        speed = control.get("speed", self._speed)
        if not isinstance(fault, str) or fault not in FAULTS:
            raise ValueError("unknown virtual fault")
        if not isinstance(mode, str) or mode not in MODES:
            raise ValueError("unknown virtual mode")
        if type(speed) is not int or speed not in SPEEDS:
            raise ValueError("speed must be 1, 10 or 30")
        self._fault, self._mode, self._speed = fault, mode, speed
        return self.snapshot()

    def set_manual_hold(self, hold: bool) -> dict:
        if type(hold) is not bool:
            raise ValueError("manual hold must be a Boolean")
        self._manual_hold = hold
        return self.snapshot()

    def _signals(self) -> dict:
        t = float(self._elapsed)
        wave = math.sin(t / 600.0)
        signals = {
            "turbidity": 0.65 + 0.08 * wave,
            "ph": 7.2 + 0.05 * math.sin(t / 900.0),
            "chlorine": 0.35 + 0.02 * math.sin(t / 720.0),
            "orp": 680.0 + 8.0 * math.sin(t / 800.0),
            "p1_bar": 2.8 + 0.03 * wave,
            "p2_bar": 2.55 + 0.03 * wave,
            "p3_bar": 2.3 + 0.03 * wave,
            "p4_bar": 1.85 + 0.03 * wave,
        }
        if self._fault == "turbidity":
            signals["turbidity"] = 8.0 + 0.2 * wave
        if self._fault == "sensor_dropout":
            signals["chlorine"] = None
        if self._fault == "clogging":
            signals.update(p1_bar=2.9, p2_bar=1.5, p3_bar=0.9, p4_bar=0.35)
        if self._fault == "power_loss" or self._manual_hold or self._mode == "standby":
            for key in ("p1_bar", "p2_bar", "p3_bar", "p4_bar"):
                signals[key] = 0.0
        return signals

    def _operation(self):
        """Derive current interlocks and requested rates without any mutation."""
        channels = self._signals()
        valid = {key: value is not None and math.isfinite(value) for key, value in channels.items()}
        power = self._fault != "power_loss"
        codes, reasons = [], []

        def reason(code, text):
            codes.append(code)
            reasons.append(text)

        rates = {key: _ZERO for key in ("inlet", "treatment", "reuse", "drain", "backwash", "product")}
        command = feedback = "closed"
        if not power:
            reason("POWER_LOSS", "انقطاع التغذية الافتراضية؛ المضخات متوقفة والصمامان مغلقان.")
        if self._manual_hold:
            reason("MANUAL_HOLD", "إيقاف يدوي افتراضي مفعّل.")
        if not power or self._manual_hold:
            state = "HOLD"
        elif self._mode == "standby":
            state = "STANDBY"
            reason("STANDBY_MODE", "وضع الاستعداد؛ لا معالجة أو ري افتراضي.")
        elif self._mode == "backwash":
            if self._treated > 0:
                rates["backwash"] = _BACKWASH
                state = "BACKWASH"
                reason("BACKWASH_MODE", "غسيل عكسي افتراضي من الخزان المعالج إلى مصرف الغسيل؛ الري مغلق.")
            else:
                state = "HOLD"
                reason("TREATED_TANK_EMPTY", "الخزان المعالج فارغ؛ مضخة الغسيل متوقفة.")
        else:
            if not all(valid[key] for key in ("turbidity", "ph", "chlorine")):
                reason("QUALITY_SENSOR_INVALID", "قراءة جودة مفقودة أو غير صالحة؛ لا سماح بالري الافتراضي.")
            else:
                if channels["turbidity"] > _THRESHOLDS["turbidity_max_ntu"]:
                    reason("TURBIDITY_HIGH", "العكارة تتجاوز الحد التجريبي الثابت 2 NTU.")
                if not _THRESHOLDS["ph_min"] <= channels["ph"] <= _THRESHOLDS["ph_max"]:
                    reason("PH_OUT_OF_RANGE", "الأس الهيدروجيني خارج النطاق التجريبي 6.5–8.5.")
                if not _THRESHOLDS["chlorine_min_mg_l"] <= channels["chlorine"] <= _THRESHOLDS["chlorine_max_mg_l"]:
                    reason("CHLORINE_OUT_OF_RANGE", "الكلور المتبقي خارج النطاق التجريبي 0.2–0.5 mg/L.")
            pressure_keys = ("p1_bar", "p2_bar", "p3_bar", "p4_bar")
            if not all(valid[key] for key in pressure_keys):
                reason("PRESSURE_SENSOR_INVALID", "قراءة ضغط غير صالحة.")
            else:
                if not _THRESHOLDS["outlet_pressure_min_bar"] <= channels["p4_bar"] <= _THRESHOLDS["outlet_pressure_max_bar"]:
                    reason("OUTLET_PRESSURE_OUT_OF_RANGE", "ضغط المخرج خارج النطاق التجريبي 0.8–3.5 bar.")
                if any(not 0 <= channels[key] <= _THRESHOLDS["line_pressure_max_bar"] for key in pressure_keys):
                    reason("LINE_PRESSURE_OUT_OF_RANGE", "ضغط خط خارج نطاق 0–5 bar التجريبي.")
                if channels["p1_bar"] - channels["p2_bar"] > _THRESHOLDS["filter_differential_max_bar"]:
                    reason("FILTER_DIFFERENTIAL_HIGH", "فرق الضغط عبر المرشح يتجاوز 0.9 bar؛ حجز افتراضي.")
            if not codes:
                command = "open"
                feedback = "closed" if self._fault == "valve_stuck" else "open"
                if feedback != command:
                    reason("VALVE_COMMAND_FEEDBACK_MISMATCH", "طلب فتح افتراضي مع تأكيد بقاء صمام الري مغلقًا؛ إيقاف المضخات وحجز التدفق.")
            if codes:
                state = "HOLD"
            else:
                rates.update(inlet=_INLET, treatment=_FEED, product=_FEED * _RECOVERY,
                             drain=_FEED * (1 - _RECOVERY), reuse=_REUSE)
                state = "REUSE"
        # The demonstrator's matched inlet/feed/reuse demand is1000L/hour.
        # It may transfer concurrent incoming water through an empty inventory;
        # there is no claimed hydraulic residence or chemical removal model.
        # Inventory limits for every finite step are enforced in step().
        return channels, valid, rates, command, feedback, power, state, codes, reasons

    def step(self, elapsed_seconds: float) -> dict:
        """Advance by dt in [0,300] seconds; dt=0 is exactly read-only."""
        if (isinstance(elapsed_seconds, bool) or not isinstance(elapsed_seconds, (int, float))
                or not 0 <= elapsed_seconds <= 300 or not math.isfinite(elapsed_seconds)):
            raise ValueError("step duration must be finite seconds between 0 and 300")
        if elapsed_seconds == 0:
            return self.snapshot()
        dt = Decimal(str(elapsed_seconds))
        new_elapsed = self._elapsed + dt
        try:
            self._start + timedelta(seconds=float(new_elapsed))
        except (OverflowError, ValueError) as exc:
            raise ValueError("virtual timestamp exceeds supported range") from exc
        rates = self._operation()[2]
        minutes = dt / Decimal(60)
        incoming = rates["inlet"] * minutes
        feed = min(rates["treatment"] * minutes, self._raw + incoming)
        product = feed * _RECOVERY
        reject = feed - product
        backwash = min(rates["backwash"] * minutes, self._treated)
        reuse = min(rates["reuse"] * minutes, self._treated + product - backwash)
        raw = self._raw + incoming - feed
        treated = self._treated + product - reuse - backwash
        raw_overflow = max(_ZERO, raw - _CAPACITY)
        treated_overflow = max(_ZERO, treated - _CAPACITY)
        raw -= raw_overflow
        treated -= treated_overflow
        increments = {
            "input_liters": incoming, "reuse_liters": reuse,
            "reject_drain_liters": reject, "backwash_liters": backwash,
            "overflow_liters": raw_overflow + treated_overflow,
            "raw_overflow_liters": raw_overflow, "treated_overflow_liters": treated_overflow,
            "treatment_feed_liters": feed, "treated_product_liters": product,
        }
        volumes = {key: self._volumes[key] + value for key, value in increments.items()}
        balance = (self._initial_stored + volumes["input_liters"] - raw - treated
                   - volumes["reuse_liters"] - volumes["reject_drain_liters"]
                   - volumes["overflow_liters"] - volumes["backwash_liters"])
        if min(raw, treated, *volumes.values()) < 0 or max(raw, treated) > _CAPACITY or abs(balance) > Decimal("1e-8"):
            raise ArithmeticError("virtual fluid inventory invariant failed")
        self._raw, self._treated, self._volumes, self._elapsed = raw, treated, volumes, new_elapsed
        return self.snapshot()

    def snapshot(self) -> dict:
        channels, valid, rates, command, feedback, power, state, codes, reasons = self._operation()
        channels["flow_lpm"] = float(rates["reuse"])
        valid["flow_lpm"] = True
        raw_overflow = max(_ZERO, rates["inlet"] - rates["treatment"]) if self._raw == _CAPACITY else _ZERO
        treated_overflow = max(_ZERO, rates["product"] - rates["reuse"]) if self._treated == _CAPACITY else _ZERO
        stored = self._raw + self._treated
        v = self._volumes
        error = (self._initial_stored + v["input_liters"] - stored - v["reuse_liters"]
                 - v["reject_drain_liters"] - v["overflow_liters"] - v["backwash_liters"])
        return {
            "source": "virtual_plant", "virtual": True, "hardware": False,
            "timestamp": (self._start + timedelta(seconds=float(self._elapsed))).isoformat().replace("+00:00", "Z"),
            "elapsed_seconds": float(self._elapsed), "mode": self._mode, "fault": self._fault,
            "speed": self._speed, "manual_hold": self._manual_hold,
            "chans": channels, "validity": valid,
            "tanks": {name: {"liters": float(amount), "capacity_liters": float(_CAPACITY),
                              "level_percent": float(amount / _CAPACITY * 100)}
                      for name, amount in (("raw", self._raw), ("treated", self._treated))},
            "flow": {"inlet_lpm": float(rates["inlet"]), "treatment_lpm": float(rates["treatment"]),
                     "reuse_lpm": float(rates["reuse"]), "drain_lpm": float(rates["drain"]),
                     "backwash_lpm": float(rates["backwash"]), "overflow_lpm": float(raw_overflow + treated_overflow),
                     "product_lpm": float(rates["product"]),
                     "recirculation_lpm": 0.0},
            "volumes": {**{key: float(value) for key, value in v.items()},
                        "initial_stored_liters": float(self._initial_stored), "stored_liters": float(stored),
                        "balance_error_liters": float(error)},
            "equipment": {"feed_pump": "running" if rates["treatment"] > 0 else "stopped",
                          "dosing_pumps": "running" if rates["treatment"] > 0 else "stopped",
                          "inlet_pump": "running" if rates["inlet"] > 0 else "stopped",
                          "reuse_pump": "running" if rates["reuse"] > 0 else "stopped",
                          "backwash_pump": "running" if rates["backwash"] > 0 else "stopped",
                          "irrigation_valve": feedback,
                          "drain_valve": "open" if rates["drain"] + rates["backwash"] > 0 else "closed",
                          "power": power, "irrigation_command": command, "irrigation_feedback": feedback,
                          "compliance_valve": "product" if rates["product"] > 0 else "closed"},
            "safety": {"state": state, "reuse_permitted": state == "REUSE" and rates["reuse"] > 0,
                       "reasons": reasons, "reason_codes": codes},
            "design_assumptions": {
                "rated_m3_per_day": 15, "rated_capacity_basis": "treatment feed; not reuse delivery",
                "rated_feed_lph": 1000, "rated_operating_hours_per_day": 15,
                "daily_duty_cycle_enforced": False,
                "volumetric_recovery": 1.0, "theoretical_product_m3_per_day": 15,
                "inlet_lpm": float(_INLET), "reuse_demand_lpm": float(_REUSE),
                "matched_flow_assumption": "Inlet and irrigation demand equal feed; this is a steady-flow illustration, not measured building demand.",
                "continuous_reject_assumption": "None. No membrane/RO rejection stage is specified; drain remains a compatibility key with zero normal reject.",
                "backwash_lpm": 65, "backwash_source": "treated tank; no treatment or reuse during backwash",
                "backwash_basis": "Illustrative reference3.9m3/hour; stock-bounded, not a validated pump/filter specification.",
                "recirculation_model": "Design-only return branch; zero simulated flow. HOLD stops all normal transfers; no automatic diversion is inferred.",
                "design_only_equipment": ["S-100", "DP-101", "DP-102", "DP-103", "DP-104", "CF-101", "UV-C", "TC-101", "CP-01"],
                "dosing_model": "Aggregate running/stopped indicator only; no individual chemical inventory, dosing rate, reaction, UV dose or carbon adsorption model.",
                "experimental_thresholds": True, "thresholds": dict(_THRESHOLDS),
                "channel_units": {"turbidity": "NTU", "ph": "pH", "chlorine": "mg/L", "orp": "mV",
                                  "p1_bar": "bar", "p2_bar": "bar", "p3_bar": "bar", "p4_bar": "bar", "flow_lpm": "L/min"},
                "quality_model": "Bounded illustrative signals; no chemical treatment, tank mixing or field validation claim.",
                "pressure_model": "Illustrative line-pressure readings; not a validated hydraulic transient model.",
                "orp_is_chlorine": False, "ai_controls_valves": False, "model_inference": None,
                "actuation": "Virtual only. Both valves normally closed; loss of power stops every flow. No gravity diversion.",
                "overflow": "Explicit unretained tank excess; discharged separately from reject and backwash.",
                "flow_basis": "Instantaneous virtual rates; cumulative volumes integrate actual stock-bounded transfers.",
                "balance": "initial_stored + input = stored + reuse + reject_drain + overflow + backwash",
            },
        }
