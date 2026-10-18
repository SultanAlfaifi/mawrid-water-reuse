"""Measure local end-to-end inference only after the corresponding test exists."""
import json
import argparse
import platform
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
from predict import predict_frame


def main(variant="v2"):
    out = ROOT / f"output/ml/gecco-{variant}"
    results = []
    for name, raw, start, label in [
        ("fold_6", ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv", 139566*9//10, "EVENT"),
        ("external_2019", ROOT / "data/external/gecco2019/6_gecco2019_test_water_quality.csv", 0, "Event")]:
        folder = out / name
        assert (folder / "test_results.json").exists(), "Never benchmark before final evaluation"
        saved = pd.read_csv(folder / "test_predictions.csv.gz")
        for role in ["baseline", variant]:
            path = folder / f"{role}_model.joblib"
            bundle = joblib.load(path)
            data = pd.read_csv(raw, usecols=bundle["channels"]).iloc[start+120:].reset_index(drop=True)
            started = time.perf_counter()
            with threadpool_limits(limits=1):
                batch = predict_frame(bundle, data)
            batch_seconds = time.perf_counter()-started
            expected = saved[f"{role}_prediction"].to_numpy()[120:]
            np.testing.assert_array_equal(batch.prediction, expected)
            np.testing.assert_allclose(batch.score, saved[f"{role}_score"].to_numpy()[120:], rtol=1e-12, atol=1e-12, equal_nan=True)
            available = np.flatnonzero(batch.prediction.to_numpy() >= 0)
            examples = available[available >= 64][:100]
            durations = []
            for i in examples:
                # 65 rows cover the largest 61-row feature history + 5-row policy.
                prefix = data.iloc[i-64:i+1].reset_index(drop=True)
                started = time.perf_counter()
                with threadpool_limits(limits=1):
                    one = predict_frame(bundle, prefix)
                durations.append((time.perf_counter()-started)*1000)
                assert int(one.prediction.iloc[-1]) == int(batch.prediction.iloc[i])
            results.append({"partition": name, "role": role, "family": bundle["family"],
                            "model_bytes": path.stat().st_size, "model_mebibytes": path.stat().st_size/1024**2,
                            "sample_count": len(examples), "median_end_to_end_ms": float(np.median(durations)),
                            "p95_end_to_end_ms": float(np.quantile(durations, .95)),
                            "batch_seconds": batch_seconds, "batch_rows": len(data),
                            "batch_matches_frozen_evaluation": True,
                            "fixed_history_online_predictions_match_batch": True})
    report = {"platform": platform.platform(), "architecture": platform.machine(),
              "python": platform.python_version(), "raspberry_pi_measured": False,
              "includes": "DataFrame preparation, causal features, score and alarm policy over a 65-row bounded history; excludes sensor I/O, disk loading and 3D rendering",
              "results": results}
    (out / "runtime.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["v2", "v3"], default="v2")
    main(parser.parse_args().variant)
