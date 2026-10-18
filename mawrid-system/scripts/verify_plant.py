"""Isolated HTTP/SQLite integration evidence for the explicitly virtual plant.

No operator database, ML model, public measurement file, hardware or external
service is opened. The deterministic phase calls only Application._plant_tick
directly to stimulate its disabled clock; every user operation and observation
uses the real loopback LocalServer. A separate phase enables the real worker.
Previous evidence is never overwritten. Failed evidence is retained as failed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

SYSTEM = Path(__file__).resolve().parents[1]
ROOT = SYSTEM.parent
sys.path.insert(0, str(SYSTEM))
from server.app import Application
from server.main import LocalServer


class FakeEngine:
    """Sentinel: virtual sessions must never request model loading or scoring."""
    def __init__(self):
        self.start_calls = self.step_calls = self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1

    def status(self):
        return {"version": "synthetic_sentinel", "status": "not_loaded", "acceptance_passed": False,
                "message": "Synthetic integration sentinel; no ML loaded.", "metrics": {},
                "limitations": ["No model exists in this verification engine."]}

    def start(self, source):
        self.start_calls += 1
        raise AssertionError("Virtual-source test attempted to load a model")

    def step(self, count):
        self.step_calls += 1
        raise AssertionError("Virtual-source test attempted model inference")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_hashes():
    paths = [SYSTEM / "server" / name for name in ("__init__.py", "app.py", "main.py", "store.py", "plant.py")]
    paths += [SYSTEM / "CONTRACT.json", Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


@contextmanager
def http_application(database, *, worker):
    engine = FakeEngine()
    app = Application(database, engine=engine, start_plant_worker=worker)
    server = LocalServer(0, app)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, body=None, *, expected=200, method=None, raw=False, timeout=3):
        payload = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=payload, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status, content = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, content = error.code, error.read()
        if status != expected:
            raise AssertionError(f"{path}: expected HTTP{expected}, got{status}: {content[:300]!r}")
        return content if raw else json.loads(content)

    try:
        yield app, engine, request
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def close_to(actual, expected, tolerance=1e-8):
    if not math.isfinite(actual) or abs(actual - expected) > tolerance:
        raise AssertionError(f"Expected {expected}, observed {actual}, tolerance {tolerance}")


def check_inventory(snapshot):
    assert snapshot["source"] == "virtual_plant"
    assert snapshot["virtual"] is True and snapshot["hardware"] is False
    v = snapshot["volumes"]
    close_to(v["initial_stored_liters"] + v["input_liters"],
             sum(v[key] for key in ("stored_liters", "reuse_liters", "reject_drain_liters", "overflow_liters", "backwash_liters")))
    close_to(v["balance_error_liters"], 0)
    close_to(v["stored_liters"], sum(tank["liters"] for tank in snapshot["tanks"].values()))
    for tank in snapshot["tanks"].values():
        close_to(tank["capacity_liters"], 5000)
        assert 0 <= tank["liters"] <= tank["capacity_liters"]
    close_to(snapshot["flow"]["recirculation_lpm"], 0)
    close_to(snapshot["flow"]["drain_lpm"], 0)
    close_to(v["reject_drain_liters"], 0)
    assert snapshot["equipment"]["compliance_valve"] == ("product" if snapshot["flow"]["product_lpm"] > 0 else "closed")
    design = snapshot["design_assumptions"]
    assert design["rated_feed_lph"] == 1000 and design["rated_operating_hours_per_day"] == 15
    assert design["rated_m3_per_day"] == design["theoretical_product_m3_per_day"] == 15
    assert design["volumetric_recovery"] == 1 and design["backwash_lpm"] == 65
    assert design["daily_duty_cycle_enforced"] is False
    assert all(value >= 0 for key, value in v.items() if key != "balance_error_liters")
    assert snapshot["design_assumptions"]["ai_controls_valves"] is False
    assert snapshot["design_assumptions"]["model_inference"] is None
    json.dumps(snapshot, allow_nan=False)


def check_state(state):
    assert state["app"]["hardware_connected"] is False
    assert state["overview"]["valve_state"] == "closed"
    assert state["overview"]["measured_irrigation_liters"] is None
    assert state["model"]["status"] == "unavailable"
    assert state["model"]["acceptance_passed"] is False
    check_inventory(state["virtual_plant"])
    if state["latest"] is not None:
        reading = state["latest"]
        assert reading["source_id"] == "virtual_plant"
        assert reading["prediction"] == reading["reference_prediction"] == reading["baseline_prediction"] == -1
        assert reading["score"] is None and reading["available"] is False
        assert reading["model_version"] == "unavailable"
        assert reading["provenance_mode"] == "digital_twin"


def frozen_inventory(snapshot):
    return snapshot["timestamp"], snapshot["elapsed_seconds"], snapshot["volumes"], snapshot["tanks"]


def deterministic_phase(database, evidence):
    assertions = evidence["assertions"]
    with http_application(database, worker=False) as (app, engine, request):
        sources = request("/api/sources")["sources"]
        source = next(item for item in sources if item["id"] == "virtual_plant")
        assert source["kind"] == "digital_twin" and source["rows"] is None
        assert len(source["channels"]) == 9
        assert next(c for c in source["channels"] if c["key"] == "flow_lpm")["name"] == "تدفق الري الافتراضي"
        assertions.append("HTTP sources explicitly distinguish virtual plant and correctly label reuse flow")
        request("/api/sessions", {"source_id": "virtual_plant"}, expected=400)
        request("/api/plant/control", {"running": True}, expected=409)
        request("/api/control/open", {}, expected=404)
        state = request("/api/sessions", {"source_id": "virtual_plant", "research_ack": True})
        session = state["session"]["id"]
        check_state(state)
        assert state["session"]["position"] == 0
        initial = state["virtual_plant"]
        for _ in range(4):
            assert request("/api/state")["virtual_plant"] == initial
        request("/api/plant/control", {"speed": 2}, expected=400)
        request("/api/plant/control", {"fault": "unknown"}, expected=400)
        request("/api/plant/control", {"prediction": 0}, expected=400)
        assert request("/api/state")["virtual_plant"] == initial
        assertions.append("GET never advances time; invalid controls and AI-like inputs cannot mutate the plant")

        state = request("/api/plant/control", {"speed": 30})
        assert frozen_inventory(state["virtual_plant"]) == frozen_inventory(initial)
        for i in range(120):
            app._plant_tick()  # Only direct call: deterministic stimulation of the disabled test clock.
            if (i + 1) % 30 == 0:
                check_state(request("/api/state"))
        state = request("/api/state")
        check_state(state)
        hour = state["virtual_plant"]
        assert state["session"]["position"] == 120
        close_to(hour["elapsed_seconds"], 3600)
        start_time = datetime.fromisoformat(initial["timestamp"].replace("Z", "+00:00"))
        hour_time = datetime.fromisoformat(hour["timestamp"].replace("Z", "+00:00"))
        close_to((hour_time - start_time).total_seconds(), 3600)
        expected_hour = {"input_liters": 1000, "reuse_liters": 1000, "reject_drain_liters": 0,
                         "initial_stored_liters": 5000, "stored_liters": 5000,
                         "treatment_feed_liters": 1000, "treated_product_liters": 1000,
                         "overflow_liters": 0, "backwash_liters": 0}
        for key, value in expected_hour.items(): close_to(hour["volumes"][key], value)
        close_to(hour["tanks"]["raw"]["liters"], 3000)
        close_to(hour["tanks"]["treated"]["liters"], 2000)
        for key in ("inlet_lpm", "treatment_lpm", "product_lpm", "reuse_lpm"):
            close_to(hour["flow"][key], 1000 / 60)
        evidence["deterministic_hour"] = {"ticks": 120, "seconds_per_tick": 30,
            "elapsed_seconds": hour["elapsed_seconds"], "volumes": hour["volumes"],
            "expected_volumes": expected_hour, "clock_advanced_by_test_ticks_only": True}
        assertions.append("120 deterministic worker ticks at30s produce the independently calculated one-hour water balance")

        faults = {"turbidity": "TURBIDITY_HIGH", "sensor_dropout": "QUALITY_SENSOR_INVALID",
                  "clogging": "FILTER_DIFFERENTIAL_HIGH", "power_loss": "POWER_LOSS",
                  "valve_stuck": "VALVE_COMMAND_FEEDBACK_MISMATCH"}
        evidence["faults"] = []
        for fault, reason in faults.items():
            before = request("/api/state")["virtual_plant"]
            state = request("/api/plant/control", {"fault": fault, "mode": "auto"})
            check_state(state)
            plant = state["virtual_plant"]
            assert frozen_inventory(plant) == frozen_inventory(before)
            assert plant["safety"]["state"] == "HOLD" and not plant["safety"]["reuse_permitted"]
            assert reason in plant["safety"]["reason_codes"]
            assert all(value == 0 for value in plant["flow"].values())
            assert plant["equipment"]["irrigation_valve"] == "closed"
            if fault == "turbidity": assert plant["chans"]["turbidity"] > 2
            elif fault == "sensor_dropout":
                assert plant["chans"]["chlorine"] is None and plant["validity"]["chlorine"] is False
            elif fault == "clogging":
                assert plant["chans"]["p1_bar"] - plant["chans"]["p2_bar"] > .9
            elif fault == "power_loss":
                assert plant["equipment"]["power"] is False
                assert plant["equipment"]["drain_valve"] == "closed"
                assert all(value == "stopped" for key, value in plant["equipment"].items() if "pump" in key)
            elif fault == "valve_stuck":
                assert plant["equipment"]["irrigation_command"] == "open"
                assert plant["equipment"]["irrigation_feedback"] == "closed"
            app._plant_tick()
            state = request("/api/state"); check_state(state)
            assert state["virtual_plant"]["volumes"] == before["volumes"]
            cleared = request("/api/plant/control", {"fault": "none"})
            assert cleared["virtual_plant"]["safety"]["reuse_permitted"]
            assert cleared["virtual_plant"]["equipment"]["irrigation_valve"] == "open"
            app._plant_tick()
            recovered = request("/api/state"); check_state(recovered)
            assert recovered["virtual_plant"]["volumes"]["reuse_liters"] > before["volumes"]["reuse_liters"]
            evidence["faults"].append({"fault": fault, "reason": reason, "immediate_hold": True,
                                      "zero_flow_and_no_volume_change": True, "clear_recovers": True})
        assertions.append("All five faults hold immediately for observable values/feedback; clear restores virtual reuse")

        state = request("/api/plant/control", {"mode": "standby"})
        before = state["virtual_plant"]
        assert before["safety"]["state"] == "STANDBY" and all(v == 0 for v in before["flow"].values())
        app._plant_tick()
        state = request("/api/state"); check_state(state)
        assert state["virtual_plant"]["volumes"] == before["volumes"]
        assertions.append("Standby closes virtual flow without changing inventories")
        state = request("/api/plant/control", {"mode": "backwash"})
        before = state["virtual_plant"]
        assert before["safety"]["state"] == "BACKWASH"
        close_to(before["flow"]["backwash_lpm"], 65)
        assert all(before["flow"][key] == 0 for key in ("reuse_lpm", "treatment_lpm", "inlet_lpm", "drain_lpm"))
        assert before["equipment"]["irrigation_valve"] == "closed"
        assert before["equipment"]["drain_valve"] == "open"
        app._plant_tick()
        state = request("/api/state"); check_state(state); after = state["virtual_plant"]
        close_to(after["volumes"]["backwash_liters"] - before["volumes"]["backwash_liters"], 32.5)
        close_to(before["volumes"]["stored_liters"] - after["volumes"]["stored_liters"], 32.5)
        assert after["volumes"]["reject_drain_liters"] == before["volumes"]["reject_drain_liters"]
        assert after["volumes"]["reuse_liters"] == before["volumes"]["reuse_liters"]
        assertions.append("Backwash withdraws65L/min from treated storage, separately from zero normal reject and reuse")

        state = request("/api/plant/control", {"running": False})
        paused = state["virtual_plant"]
        assert state["session"]["status"] == "paused" and paused["running"] is False
        for _ in range(3):
            app._plant_tick()
            assert request("/api/state")["virtual_plant"] == paused
        state = request("/api/plant/control", {"mode": "auto", "running": True})
        assert state["session"]["status"] == "ready"
        state = request("/api/control/stop", {"note": "Synthetic virtual-plant verification"})
        held = state["virtual_plant"]
        assert state["session"]["status"] == "paused" and held["manual_hold"] is True
        assert held["safety"]["state"] == "HOLD" and all(v == 0 for v in held["flow"].values())
        request("/api/plant/control", {"running": True}, expected=409)
        app._plant_tick()
        assert request("/api/state")["virtual_plant"] == held
        state = request("/api/control/reset", {})
        assert state["session"]["status"] == "paused"
        assert state["virtual_plant"]["manual_hold"] is False
        assert frozen_inventory(state["virtual_plant"]) == frozen_inventory(held)
        state = request("/api/plant/control", {"running": True})
        assert state["session"]["status"] == "ready"
        app._plant_tick()
        state = request("/api/replay/pause", {})
        assert state["session"]["status"] == "paused"
        assertions.append("Pause/GET do not advance; manual hold prevents resume until explicit reset then resume")

        query = urlencode({"limit": 1000, "session_id": session})
        history = request("/api/readings?" + query)["readings"]
        assert len(history) == state["session"]["position"] == 133
        assert [row["sample_index"] for row in history] == list(range(len(history)))
        readings_csv = request("/api/export/readings.csv", raw=True)
        csv_rows = list(csv.DictReader(io.StringIO(readings_csv.decode("utf-8-sig"))))
        assert len(csv_rows) == len(history)
        for actual, row in zip(csv_rows, history):
            assert actual["source_id"] == "virtual_plant" and actual["session_id"] == session
            assert actual["provenance_mode"] == "digital_twin" and actual["hardware_connected"] == "False"
            assert actual["model_acceptance_passed"] == "False" and actual["model_version"] == "unavailable"
            assert actual["score"] == "" and actual["available"] == "False"
            assert int(actual["prediction"]) == int(actual["reference_prediction"]) == int(actual["baseline_prediction"]) == -1
            snapshot = json.loads(actual["virtual_plant"])
            assert snapshot == row["virtual_plant"]
            check_inventory(snapshot)
            for channel, value in row["channels"].items():
                exported = actual["sensor_" + channel]
                assert exported == "" if value is None else float(exported) == value
            assert datetime.fromisoformat(actual["timestamp"]) == datetime.fromisoformat(snapshot["timestamp"].replace("Z", "+00:00"))
        evidence["persisted_virtual_readings"] = len(history)
        evidence["full_snapshots_checked"] = len(csv_rows)
        assertions.append("All133 persisted/CSV rows retain exact full plant snapshots, sensors, source/session and unavailable-ML provenance")

        report = request("/api/report")
        assert report["hardware_connected"] is False and report["valve_state"] == "closed"
        assert report["measured_irrigation_liters"] is None
        assert report["virtual_plant"]["volumes"] == state["virtual_plant"]["volumes"]
        assert report["totals"]["readings"] == len(history)
        check_inventory(report["virtual_plant"])
        alarms = request("/api/alarms?limit=1000")["alarms"]
        simulation_events = [alarm for alarm in alarms if alarm["kind"] == "simulation"]
        assert simulation_events and all(alarm["details"]["virtual"] is True for alarm in simulation_events)
        alarm = simulation_events[0]
        request(f"/api/alarms/{alarm['id']}/ack", {"note": "Verified virtual event"})
        alarms = request("/api/alarms?limit=1000")["alarms"]
        assert next(a for a in alarms if a["id"] == alarm["id"])["acknowledged_at"] is not None
        events_csv = request("/api/export/events.csv", raw=True)
        assert len(list(csv.DictReader(io.StringIO(events_csv.decode("utf-8-sig"))))) == len(alarms)
        assert engine.start_calls == engine.step_calls == 0
        evidence["sentinel_model_calls"] = {"start": engine.start_calls, "step": engine.step_calls}
        evidence["records_before_restart"] = request("/api/report")["totals"]
        assertions.append("HTTP report and event CSV preserve virtual provenance; acknowledgement persists; no model load/inference occurs")

    with http_application(database, worker=False) as (app, engine, request):
        state = request("/api/state")
        assert state["session"]["status"] == "idle" and state["session"]["id"] is None
        assert state["virtual_plant"] is None and state["latest"] is None
        assert state["overview"]["valve_state"] == "closed"
        assert request("/api/readings?limit=1000")["readings"] == history
        assert request("/api/alarms?limit=1000")["alarms"] == alarms
        assert request("/api/export/readings.csv", raw=True) == readings_csv
        assert request("/api/export/events.csv", raw=True) == events_csv
        request("/api/plant/control", {"running": True}, expected=409)
        app._plant_tick()
        assert request("/api/state")["session"]["status"] == "idle"
        assert request("/api/report")["totals"] == evidence["records_before_restart"]
        assert engine.start_calls == engine.step_calls == 0
        evidence["restart"] = {"idle_requires_explicit_new_session": True, "history_exact": True,
            "alarms_and_acknowledgement_exact": True, "readings_csv_sha256": hashlib.sha256(readings_csv).hexdigest(),
            "events_csv_sha256": hashlib.sha256(events_csv).hexdigest(), "csv_bytes_identical": True}
        assertions.append("Process restart preserves every reading/event/acknowledgement and byte-identical exports while leaving the simulator idle")


def background_phase(database, evidence):
    with http_application(database, worker=True) as (app, engine, request):
        state = request("/api/sessions", {"source_id": "virtual_plant", "research_ack": True})
        initial_position = state["session"]["position"]
        assert initial_position == 0
        started = time.monotonic()
        deadline = started + 4.5
        polls = 0
        while state["session"]["position"] == 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("Real background worker did not produce a tick within4.5seconds")
            state = request("/api/state", timeout=min(1, remaining))
            polls += 1
            if state["session"]["position"] == 0:
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
        elapsed = time.monotonic() - started
        assert elapsed < 5
        check_state(state)
        observed_position = state["session"]["position"]
        close_to(state["virtual_plant"]["elapsed_seconds"], observed_position)
        state = request("/api/plant/control", {"running": False})
        paused = state["virtual_plant"]
        time.sleep(.1)
        assert request("/api/state")["virtual_plant"] == paused
        assert engine.start_calls == engine.step_calls == 0
        evidence["background_worker"] = {"enabled": True, "manual_tick_calls": 0,
            "first_observed_tick_wall_seconds": elapsed, "polls": polls,
            "first_observed_position": observed_position, "sample_speed": 1,
            "virtual_elapsed_seconds": paused["elapsed_seconds"], "pause_stops_clock": True,
            "model_start_calls": engine.start_calls, "model_step_calls": engine.step_calls}
        evidence["assertions"].append("Real background worker advances via its own thread within5s; HTTP GET merely observes, and pause stops the clock")


def verify(output):
    if output.exists():
        raise FileExistsError("Preserve previous evidence; choose a new output path")
    started = time.perf_counter()
    evidence = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": False, "scope": "Actual loopback HTTP and SQLite integration of an explicitly virtual deterministic plant.",
        "limitations": ["Synthetic plant values are not field measurements, hydraulic validation or chemical treatment validation.",
                        "No ML model or public-source measurement data was opened. Model non-use is checked by a rejecting sentinel.",
                        "No operator database or hardware was connected. This is functional integration evidence only."],
        "temporary_database_only": True, "hardware_connected": False, "ml_loaded": False,
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "assertions": [], "code_sha256": code_hashes()}
    failure = None
    try:
        with tempfile.TemporaryDirectory(prefix="mawrid-plant-http-verification-") as directory:
            deterministic_phase(Path(directory) / "deterministic.sqlite3", evidence)
            background_phase(Path(directory) / "background.sqlite3", evidence)
        evidence["code_sha256_after"] = code_hashes()
        assert evidence["code_sha256"] == evidence["code_sha256_after"], "Code/contract changed during verification"
        evidence["assertions"].append("All exercised production code, contract and verifier hashes were unchanged throughout the run")
        evidence["passed"] = True
    except Exception as error:
        failure = error
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)}
        evidence["code_sha256_after"] = code_hashes()
    evidence["elapsed_seconds"] = time.perf_counter() - started
    evidence["assertion_groups_passed"] = len(evidence["assertions"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": evidence["passed"], "assertion_groups": len(evidence["assertions"]),
                      "output": str(output)}, ensure_ascii=False), flush=True)
    if failure is not None:
        raise failure
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    verify(arguments.output.resolve())
