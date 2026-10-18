# MAWRID GECCO anomaly baseline v1

This is a reproducible offline anomaly-detection experiment, completed on
16 October 2026. It is not a water-safety classifier, a calibrated sensor-trust
probability, or a classifier of the five sensor-fault types. No 3D integration
or Raspberry Pi measurement is included.

## Actual outcome

The held-out period contains **one labeled event lasting 77 minutes**. The model
alarmed during 42 of those minutes and missed 35. It also alarmed during 65
normal minutes, forming 37 false-positive runs.

| Metric | Validation | Held-out test |
|---|---:|---:|
| Point precision | 3.33% | 39.25% |
| Point recall | 0.57% | 54.55% |
| Unadjusted point F1 | 0.98% | 45.65% |
| Labeled events covered | 1 / 6 | 1 / 1 |
| Confirmed new alarm starts inside events | 1 / 6 | 1 / 1 |
| False-positive runs per eligible normal day | 0.936 | 1.922 |
| Normal minutes under alarm | 0.105% | 0.234% |

The test exceeds the predeclared target of at most one false-positive run per
normal day. The small event count and poor validation sensitivity prevent a
claim of reliable generalization. These are measured baseline results, not
estimates or simulated model scores.

## Reproduce in a fresh checkout/output directory

Keep the repository layout, including the original CSV under
`data/external/gecco2018/1_gecco2018_water_quality.csv`. From the repository root:

```sh
python3 -m venv ml/gecco_baseline/.venv
ml/gecco_baseline/.venv/bin/python -m pip install -r ml/gecco_baseline/requirements.txt
ml/gecco_baseline/.venv/bin/python -m unittest discover -s ml/gecco_baseline -p 'test_*.py' -v
ml/gecco_baseline/.venv/bin/python ml/gecco_baseline/run_baseline.py prepare
ml/gecco_baseline/.venv/bin/python ml/gecco_baseline/run_baseline.py train
ml/gecco_baseline/.venv/bin/python ml/gecco_baseline/run_baseline.py test
ml/gecco_baseline/.venv/bin/python ml/gecco_baseline/make_report.py
```

The existing v1 outputs are intentionally protected from overwrite. Use a fresh
copy to reproduce; do not delete the frozen evidence. A bit-identical raw input
is checked by SHA-256. ZIP/NPZ serialization timestamps and timing measurements
can differ between reproductions; compare split contents and predictions.

## Fixed protocol

- Original row order, consecutive identifiers 1–139566. Do not sort the local
  timestamps: the raw file repeats an hour on 30 October 2016. No timezone is
  inferred. Elapsed time is nominal minutes in acquisition order.
- First 60% for training; next 20% for validation; last 20% for test. Exclude a
  30-row gap after each boundary and reset feature history for each partition.
- Nine channels, four causal feature groups each: current value, absolute
  one-minute change, residual from the trailing 15-minute mean, and trailing
  15-minute standard deviation. Each window includes the current sample.
- No imputation or scaling. Missing inputs make the full affected 15-row window
  unavailable. Preserve those rows and original labels in the evaluation.
- Train Isolation Forest (200 trees, 256 samples/tree, seed 20261016) on 80,621
  fully valid windows containing no original EVENT in their 15-row histories.
- Select only the threshold on validation: maximize unadjusted point F1 under
  at most one false-positive run per eligible normal day and at most 1% of
  normal minutes under alarm. These are provisional experiment targets.
- Frozen threshold: **0.5694626578501852** on `-model.score_samples(X)`.
- No smoothing, point adjustment, future interpolation, label-derived feature,
  fault augmentation, hyperparameter search, or tuning on the test result.

The protocol, source/split hashes, package versions, model hash, code hashes,
and threshold are preserved in `protocol.json`, `data_manifest.json`, and
`freeze.json`. The training stage does not load the prepared test arrays.

## Definitions and limitations

Point precision/recall/F1 use only scorable rows and original current-minute
EVENT labels. Missing predictions are -1, normal is 0, anomaly is 1. The test
has 27,796 scorable rows out of 27,884; all 77 event minutes are scorable.

An event is a contiguous run of original EVENT=True. Coverage means any alarm
inside it; confirmed new detection requires an observed 0→1 transition inside
it. Starts after unavailable readings do not count as confirmed. Event recall
retains even fully unscorable events. Boundary-censored events are marked;
neither validation nor test has one in this split. No point adjustment expands
one hit to credit the whole event.

False-positive runs are contiguous alarmed minutes with EVENT=False, including
normal tails around real events. The denominator is eligible normal minutes /
1440. Count and duration are both reported to expose long or stuck alarms.

GECCO has real drinking-water readings but binary challenge events include
simulated events and sensor inspection/replacement. Its Cl/Cl_2 channels measure
chlorine dioxide, not the free residual chlorine intended for MAWRID. The
training data are not MAWRID greywater field data. An anomaly score is not a
calibrated probability that an individual sensor is trustworthy.

The single test event triggered at its first labeled minute; this establishes
no sub-minute response time. Local single-row model inference was about 4.96 ms
median on an ARM Mac, excluding feature construction and physical sensing or
actuation. The compressed model is 535,960 bytes. Raspberry Pi runtime and
end-to-end device timing remain unmeasured.

## Next experiment

The v1 test is now observed. Preserve it as a benchmark; do not repeatedly tune
against it while calling it unseen. For v2, predeclare changes, use chronological
development folds, and seek a genuinely untouched evaluation period/site with
more independent events. Study channel-specific residuals and operational
regime changes on development data; test synthetic sensor faults separately.
No result here authorizes a valve to open.

## Sources

- [GECCO source record](https://zenodo.org/records/3884398)
- [Original challenge rules and channel meanings](https://www.spotseven.de/wp-content/uploads/2018/03/rulesGeccoIc2018.pdf)
- [Isolation Forest documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)
- [Avoiding preprocessing leakage](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)
