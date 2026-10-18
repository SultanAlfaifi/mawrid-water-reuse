"""Reproducible calibration-only choice between two already frozen versions.

The original choice was written with these same rules before either 2019
final test was opened. This helper refuses to replace it or choose after test.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(v2, v3, destination):
    assert not destination.exists(), "A release choice is already frozen"
    selections, freezes = {}, {}
    for version, folder in [("v2", v2), ("v3", v3)]:
        assert not (folder / "test_results.json").exists(), "Cannot select after final test"
        f = json.loads((folder / "freeze.json").read_text())
        for role, digest in f["model_sha256"].items():
            assert sha(folder / f"{role}_model.joblib") == digest
        selections[version] = f["selected"]
        freezes[version] = sha(folder / "freeze.json")
    selected = max(selections, key=lambda v: (
        selections[v]["confirmed_new_alarm_inside_event_recall"] or 0,
        selections[v]["f1"] or 0, -selections[v]["fp"], v == "v2"))
    folder = v2 if selected == "v2" else v3
    model = folder / f"{selected}_model.joblib"
    record = {"chosen_at_utc": datetime.now(timezone.utc).isoformat(),
              "selection_rule": "Calibration only: confirmed event-start recall, then raw point F1, then fewer FP minutes, then v2 on exact tie. No final-test information used.",
              "selected_version": selected, "selected_family": selections[selected]["family"],
              "selected_model_path": str(model.resolve()), "selected_model_sha256": sha(model),
              "calibration_candidates": selections, "freeze_sha256": freezes,
              "final_test_opened_before_choice": False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2)+"\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2-folder", type=Path, required=True)
    parser.add_argument("--v3-folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.v2_folder, args.v3_folder, args.output), indent=2))
