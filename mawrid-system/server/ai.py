"""Genuine, sensor-only inference on the two qualified public V9 prefixes.

This adapter does not train, select a threshold, read labels, or operate hardware.
The existing immutable qualification is checked before trusted bundle loading.
"""
from __future__ import annotations

import json
import math
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCES = ("2019_disclosed_test", "2019-04")
EVIDENCE_DIR = ROOT / "output/ml/gecco-stream-fidelity"
RUN = ROOT / "output/ml/gecco-v9-development/run_01"


def finite(value):
    number = float(value)
    return number if math.isfinite(number) else None


class ResearchEngine:
    def __init__(self):
        self._lock = threading.RLock()
        self._engine = self._sensors = self._source = None
        self._position = 0
        self._qualification = None

    def status(self):
        with self._lock:
            return {
                "version": "V9",
                "status": "research_only" if self._engine is not None else "not_loaded",
                "acceptance_passed": False,
                "message": "كشف الشذوذ على بيانات عامة؛ لم يجتز شرط الحفاظ على كل الأحداث عبر الفترات.",
                "qualification": "تطابق عددي لأول 1600 قراءة في مصدرين، على بيئة Mac الحالية فقط.",
                "metrics": {"periods": 19, "events_detected": 113, "events_total": 399,
                            "false_alarm_fragments": 237, "false_alarm_minutes": 478,
                            "reference_events_detected": 115, "reference_false_alarm_fragments": 298},
                "limitations": [
                    "الدرجة ترتيب لشذوذ الحدث، وليست احتمال سلامة الماء أو ثقة كل حساس.",
                    "لم تثبت القدرة على تمييز أعطال الحساسات الخمسة.",
                    "مصادر التقييم سبق استخدامها في التطوير؛ ليست تحققًا ميدانيًا مستقلًا.",
                    "لا يعمم هذا التأهيل على قراءات مورد أو Raspberry Pi.",
                    "دقيقة واحدة بين القراءات، مع استبعاد أول 120 قراءة وفترة تهيئة إضافية.",
                ],
                "source_id": self._source,
                "position": self._position,
                "total": len(self._sensors) if self._sensors is not None else 1600,
                "sample_seconds": 60,
                "provenance": self._qualification,
            }

    def reset(self):
        with self._lock:
            self._engine = self._sensors = self._source = None
            self._position = 0
            self._qualification = None

    def start(self, case_id):
        if case_id not in SOURCES:
            raise ValueError("المصدر غير مؤهل لهذا النموذج")
        with self._lock:
            self.reset()
            from ml.gecco_stream_fidelity import prototype as qualified
            from ml.gecco_v9 import prototype as original
            proof_path = EVIDENCE_DIR / "input_qualification.json"
            proof = json.loads(proof_path.read_text())
            records = [record for record in proof["cases"] if record["case_id"] == case_id]
            if len(records) != 1:
                raise ValueError("تعذر مطابقة مصدر البيانات المؤهل")
            input_path = original.inside(ROOT, records[0]["csv_path"])
            gate = original.verify_run(RUN, case_id, research_preview=True, workspace_root=ROOT)
            qualification = qualified.verify_qualification(
                gate, case_id, EVIDENCE_DIR / "actual_prefix_verification.json", proof_path, input_path)
            sensors = qualified._read_sensors(input_path, qualification)
            bundle, channels = original._load_bundle(gate)
            if channels != qualification["channels"]:
                raise ValueError("ترتيب قنوات النموذج لا يطابق البيانات المؤهلة")
            # Import the exact qualified implementation; never patch frozen code.
            runtime = qualified._runtime()
            expected_runtime = ROOT / "ml/gecco_stream_fidelity/runtime.py"
            if Path(runtime.__file__).resolve() != expected_runtime.resolve():
                raise ValueError("مسار محرك الذكاء لا يطابق النسخة المؤهلة")
            engine = runtime.StreamingPredictor(bundle)
            self._engine, self._sensors, self._source = engine, sensors, case_id
            self._qualification = {
                "input_sha256": qualification["input_sha256"],
                "evidence_sha256": qualification["evidence_sha256"],
                "bundle_sha256": gate["verified_hashes"][case_id + "/bundle.joblib"],
                "first_timestamp": sensors.index[0].isoformat(),
                "last_timestamp": sensors.index[-1].isoformat(),
                "labels_used": False, "fitting_during_inference": False,
                "actual_clock_preserved": True, "qualified_rows": 1600,
            }
            return self.status()

    def step(self, count):
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 25:
            raise ValueError("عدد القراءات يجب أن يكون عددًا صحيحًا بين 1 و25")
        with self._lock:
            if self._engine is None:
                raise ValueError("ابدأ جلسة مؤهلة أولًا")
            start = self._position
            frame = self._sensors.iloc[start:start + count]
            if frame.empty:
                return []
            from threadpoolctl import threadpool_limits
            with threadpool_limits(limits=1):
                scored = self._engine.update_frame(frame)
            records = []
            for offset, (timestamp, values) in enumerate(scored.iterrows()):
                records.append({
                    "source_id": self._source, "timestamp": timestamp.isoformat(),
                    "sample_index": start + offset,
                    "channels": {key: finite(value) for key, value in frame.iloc[offset].items()},
                    "prediction": int(values["prediction"]),
                    "reference_prediction": int(values["reference_prediction"]),
                    "baseline_prediction": int(values["baseline_prediction"]),
                    "score": finite(values["long_context"]),
                    "available": bool(values["available"]),
                    "ignored_gap": bool(values["ignored_gap"]), "model_version": "V9",
                })
            self._position += len(frame)
            return records
