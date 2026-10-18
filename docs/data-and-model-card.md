# Data and Model Card

> **Current status · 17 October 2026:** `V15 POLICY EXPERIMENT COMPLETE — AUDIT PASS — NO MODEL PROMOTION`. All 19 periods are complete. V15 ultimately preserves V8 without modification and does not meet the joint event-retention/false-alarm goal. The local application still uses separately qualified, limited V9 research replay. Its operational 3D view reads the virtual-plant backend; it is not connected to V14 or V15.

## Public checkout and optional replay assets · 18 October 2026

The public Git checkout preserves research code and selected small reports and
audits. Complete raw benchmark collections, virtual environments, bulk arrays,
and historical fitted checkpoints are excluded. The
[external-source inventory](../data/external-sources.json) records publisher
URLs, licenses and raw-source hashes. References to historical local artifacts
describe the authoring workspace; not every underlying research artifact is a
Git download.

The optional [V9 research asset package](research-assets.md) adds only two fitted
bundles, their qualified first-1,600-row sensor-only inputs, unchanged 19-period
run metadata, immutable source copies, and numerical-qualification records. Its
[member manifest](research-assets-manifest.json) distinguishes packaging checks
from model evaluation. V9 replay requires the exact recorded Darwin arm64
environment, pandas 3.0.6 compiled-kernel hash, and full platform/version checks;
**a standard clone does not enable V9 inference**. The application simulation
uses its separate experimental virtual-plant rules. No result, acceptance
verdict, original audit, or fitted model is changed by this packaging.

## Latest completed experiment: V15 policy alignment

The [V15 Arabic report](../output/ml/gecco-v15/report.html), [status](../output/ml/gecco-v15/status.json), [results](../output/ml/gecco-v15-development/run_01/results.json), [calibration audit](../output/ml/gecco-v15-development/run_01/calibration-audit.json) and [test audit](../output/ml/gecco-v15-development/run_01/audit.json) document one prespecified policy-only experiment. No model was refitted: V14 confidence scores and V6/V8 decisions came from the exact previously audited artifacts. This is a new policy replay on disclosed scores, **not a new raw-sensor/model audit or fresh external validation**.

V15 fixes an objective mismatch in calibration: the actual final merged decision must retain exact V6 **and** V8 confirmed event IDs, paired extra delay ≤120 seconds, availability and nonincreasing false-alarm fragments/minutes. Recovery support requires newly confirmed IDs relative to the suppressed seed, rather than extra positive coverage within an already detected event. The pure seed may experimentally lose an event that the final output restores; final retention is mandatory. The frozen first-two-block grid has at most 64 choices. Later blocks and the all-four check can only veto. Both frozen reference experts already used all four blocks in their own calibration, so this incremental certificate is conditional on them, not an independent pipeline holdout.

**Actual outcome:** all 19 final choices are unchanged V8: seven accepted identity choices and twelve explicit identity fallbacks. V15 therefore detects **117/399 events**, with **235 false-alarm fragments**, **475 false-alarm minutes**, and observed-point F1 **4.55%**. This equals V8 and improves the totals versus V14's 114/283/534, but establishes **no new improvement over V8**. It retains 117 of the 119 V6/V8 historical event identities, still losing V6 event **4** in `2019_disclosed_test` and event **9** in `2018-12`. It does not pass the joint retention/false-alarm goal and is not promoted.

All 19 calibration choices and their hashes were frozen before any V15 outer-test numeric arrays were read. The independent calibration audit repeated the complete finite selection and veto process; the independent test audit repeated scalar decisions and original-axis metrics over **449,431 test rows plus 891,750 calibration rows**, with **25,536,916 numeric comparisons and zero failures**. Sensor/model evidence is inherited explicitly from the hash-bound V8/V14 audits. The [68-test preflight](../output/ml/gecco-v15-design/preflight.json), [frozen protocol](../output/ml/gecco-v15-design/protocol.json), [plan](../output/ml/gecco-v15-development/run_01/plan.json) and [all-policy freeze](../output/ml/gecco-v15-development/run_01/policies-frozen.json) preserve temporal ordering. All test outcomes were previously disclosed and informed the development hypothesis; ordering correctness does not create a fresh holdout.

The separately completed operational 3D software verification is documented in [application verification v4](../output/mawrid-system/verification-v4.json), [17-snapshot/692-check backend-to-view integration](../output/mawrid-system/plant3d-integration-v4-r3/verification.json) and [browser proof](../output/mawrid-system/plant3d-browser-v4.json). Tank levels, equipment and flows come from the virtual backend; disconnect/unknown values remain visible. These are software and simulated-process results, not physical commissioning, validated hydraulic/chemical behavior, water safety, or permission to actuate hardware.

## Current completed evidence: V14 and comparable development versions

The [V14 Arabic report](../output/ml/gecco-v14/report.html), [machine-readable status](../output/ml/gecco-v14/status.json), [complete results](../output/ml/gecco-v14-development/run_01/results.json), and [independent audit](../output/ml/gecco-v14-development/run_01/audit.json) cover **19 disclosed development periods and 399 labeled events**: 13 GECCO periods and six WaterHub months. All these sources have been consumed for development. This is not fresh external validation, zero-shot transfer of one fitted checkpoint, or a MAWRID field-water experiment. Each period uses its declared chronological past for fitting and calibration; scoring does not use inference labels.

The following figures use the same original evaluation axes and available rows. Known-normal observed exposure is **281.925 days**. Event recall requires a prediction transition from 0 to 1 inside an original primary event; events beginning at the axis start or immediately after unknown labels are censored under the fixed accounting. This is not accuracy; point F1 remains unadjusted. Known-normal means label 0 with an available prediction, not demonstrated water safety. False-alarm duration is sample-count × cadence, not proof of continuous physical duration.

| Completed development metric | V6 reference | V8 | V12 | V13 | V14 |
|---|---:|---:|---:|---:|---:|
| Confirmed event starts / original events | 115/399 | 117/399 | 114/399 | 113/399 | 114/399 |
| Confirmed event recall | 28.82% | 29.32% | 28.57% | 28.32% | 28.57% |
| Observed-point F1 | 4.32% | 4.55% | 4.29% | 4.50% | 4.31% |
| False-alarm runs | 298 | 235 | 282 | 278 | 283 |
| False-alarm runs / observed known-normal day | 1.0570 | 0.8336 | 1.0003 | 0.9861 | 1.0038 |
| Known-normal minutes under alarm | 560 | 475 | 529 | 523 | 534 |

**Decision:** V14 is not promoted. It retains **114 of the 119 distinct event identities detected by the prior comparators** across these periods; 119 is a historical-retention set, not a replacement for the 399-event recall denominator. It still misses December event **9** detected by V6 and December events **2, 5, 11 and 50** detected by V8. IDs are local to the named periods, not interchangeable with pooled-source IDs. The largest paired additional delay versus V8 remains **6,720 seconds**, above the unchanged 120-second allowance. False-alarm runs increase from **235 for V8 to 283 for V14**, and false-alarm minutes from 475 to 534. Lower totals than V6 do not establish every-period retention and improvement. The [post-test diagnosis](../output/ml/gecco-v14-development/run_01/post_test_diagnosis.json) is exploratory, not new validation evidence.

In April, V14 retains V6 event IDs **6, 7 and 14**, meaning **3 of 21 labeled events**, and reduces false alarms from 39 to 28 runs and from 72 to 50 minutes. Recovery of IDs 6 and 7 relative to V13 is useful development evidence; it does not prove that delayed confidence has been causally fixed or that the result generalizes. The prior [V13 report](../output/ml/gecco-v13/report.html), [status](../output/ml/gecco-v13/status.json), and [audit](../output/ml/gecco-v13-development/run_01/audit.json) remain preserved: V13 was also not promoted, with 113/399 detections and April IDs 6 and 7 lost.

The V14 audit replayed **449,431 test rows and 891,750 calibration rows** across all 19 cases, with **1,318,302,396 numeric comparisons and zero failed checks**. It verified source/code/artifact lineage, original event identities, IF preservation, pulse-training weights, temporal decisions and historical comparisons. **Audit PASS establishes reproducibility and numerical consistency, not model-quality PASS.** The [protocol](../output/ml/gecco-v14-design/protocol.json) and [83-test synthetic preflight](../output/ml/gecco-v14-design/preflight-final.json) remain the pre-run evidence; they do not substitute for these completed outcomes.

Relative to V12, V14 replaces a positive label-onset weight bonus with a bonus for all confirmed training IF-tail pulse windows. Features and the decision policy remain unchanged, and the original IF is not refitted. V13's normal-tail reweighting is a prior comparison, not combined with V14. The source and model artifacts are preserved; no new threshold selection is implied by this documentation.

A [bounded public-source metadata review](../output/ml/gecco-v14-source-qualification/review.json) examined the Water Pump Dataset for a Water Supply System. It did **not** establish sufficiently precise event timing or known-normal coverage for the current 120-second/false-alarm evaluation contract, so that source is not qualified for this test. No measurement CSV or row-label array was read; a previously exposed published calendar-day event snippet is explicitly recorded, so this is not a wholly label-unseen claim. This finding applies to the inspected evidence and does not assert that no suitable public source exists globally.

No completed version establishes a calibrated sensor-trust probability, five-fault field classification, chemical or microbial water safety, Raspberry Pi latency, or permission to actuate an outlet. V14's audit is batch evidence; it does not qualify its live stream or its integration into 3D. The separate operational virtual-viewer software verification is documented above and does not change that model limitation. The original project-level field-evidence requirements below remain outstanding.

## Historical benchmark archive — preserve each protocol's own denominator

The V4, v2/v3 and v1 sections below preserve what was established at the time. Their statements about a then-unused or held-out source are historical only: those sources are now disclosed development data. Their geometry, warmups, available-row masks, refitted baselines and event counts differ from the current 19-period comparison and must not be pooled with its figures.

## Archived comparison: V4 diagnosis and its historical external check

The [V4 Arabic report](../output/ml/gecco-v4/report.html) contains the root-cause diagnosis, all development attempts, six new external periods, frozen protocols and per-period failures. The executable method was frozen before any GECCO2017 EVENT values were loaded. Each fitted model and threshold used only the local chronological past. GECCO2017 is earlier in calendar time than the 2018/2019 development sources: this is a previously unused historical dataset check, **not** a historical deployment without hindsight or a new-site claim.

| Same available rows, all original events retained | Original algorithm, refitted on matching past data | V4 |
|---|---:|---:|
| 2018 disclosed development — confirmed event starts | 21/37 | 31/37 |
| 2018 disclosed development — point F1 | 24.59% | 42.42% |
| 2018 disclosed development — false-alarm runs / normal day | 0.817 | 0.302 |
| 2018 disclosed development — normal minutes under alarm | 0.1554% | 0.1862% |
| 2017 new historical external check — confirmed event starts | 46/55 | 21/55 |
| 2017 new historical external check — point F1 | 39.74% | 32.61% |
| 2017 new historical external check — false-alarm runs / normal day | 2.181 | 0.306 |
| 2017 new historical external check — normal minutes under alarm | 0.2477% | 0.1840% |

**Decision:** V4 is not promoted. Lower false alarms do not compensate for the external loss of sensitivity: the first two external periods detected only 0/17 and 1/18 events, versus 15/17 and 14/18 for the matching original algorithm. Only two of six external periods were jointly noninferior under the declared event-count, false-run and false-duration criteria. All six met the provisional false-alarm budget, which alone is insufficient for release. No 3D integration was performed.

The independent audit reproduced 343,625 checks and preserved 239 earlier artifacts. Its [failure diagnosis](../output/ml/gecco-v4/external_failure_diagnosis.json) found a completely missing 6,117-row calibration block before the first external period: the frozen fallback selected a high threshold despite the absence of feasible operating points. Before the second period, every feasible choice missed all events in at least one calibration block. These are failures of calibration adequacy as well as generalization; an arithmetic audit pass is not a model-quality pass.

A separate [calibration guard](../ml/gecco_v4/checked_predict.py) was added after review. For future offline inference it reports unavailable when calibration constraints were not established or a past event-bearing calibration block had zero recall. It verifies the original model hash and calibration record. This guard has three synthetic tests; it does not retune V4, rewrite the external results, or constitute a new independently validated model.

The diagnosis identified calibration using very few events or none, changes in normal operating levels, different sensor signatures across event groups, and alarms triggered by returning from an event toward normal. V4 learns symmetric per-channel change scales from normal training windows, compares current measurements with past reference values, reduces outward-change evidence when a reading returns toward its reference, and takes a causal five-row median per channel. Threshold and alarm policy are selected across four past calibration blocks. Missing current measurements remain unavailable; past gaps do not automatically invalidate an entire hour.

Six adaptive recipes and three supervised recipes were retained, including unsuccessful and stopped experiments. The selected method is `return_gated_channel_median5`, with 184 predecessors and 94 initial warmup rows after each 120-row exclusion. The normal-only scales are fitted before calibration; no EVENT values, row IDs or timestamps enter scoring. Every original event remains in test denominators, including one fully unscorable event in the 2017 comparison. Shared external decision coverage is 98.23%. The benchmark still does not establish five-fault classification or a calibrated sensor-trust probability.

This protocol reserves 20% past history in four calibration blocks, so its refitted original-model scores differ from the earlier single-calibration-decile v2/v3 comparison below. Do not mix their baseline figures. All 2018/2019 results are now disclosed development evidence for V4. The 2017 outcomes were reviewed only after all six periods completed; they are now disclosed too and cannot become a fresh test for a later revision.

See [reproduction and inference instructions](../ml/gecco_v4/USAGE.txt), [pre-external selection](../output/ml/gecco-v4/pre_external_choice.json), [frozen method](../output/ml/gecco-v4/protocol.json), and [source overlap audit](../output/ml/gecco-v4-diagnostics/new_source_audit.json). A subsequent candidate needs a new evaluation plan and further untouched data or prospective site data before a claim of stable generalization.

## Earlier comparison: chronological v2 and v3 experiments

The complete [Arabic comparison report](../output/ml/gecco-comparison/report.html) preserves both attempts, their frozen protocols, and all six temporal periods. The comparison below uses the same available-minute intersection for all three methods; original events remain in the denominators.

| Period and metric | Original baseline, refitted | V2 | V3 |
|---|---:|---:|---:|
| 2018 retrospective six periods — confirmed event starts | 20/37 | 4/37 | 18/37 |
| 2018 retrospective six periods — unadjusted point F1 | 42.30% | 23.34% | 47.79% |
| 2018 retrospective six periods — false-alarm runs / normal day | 1.524 | 1.365 | 2.251 |
| 2019 later final period — confirmed event starts | 5/12 | 9/12 | 9/12 |
| 2019 later final period — unadjusted point F1 | 19.31% | 76.55% | 71.65% |
| 2019 later final period — false-alarm runs / normal day | 3.827 | 0.797 | 0.266 |

**Conclusion:** the final-period improvement does not establish stable performance across time. V2 missed more events in the six 2018 periods, and V3 improved point F1 there but produced more false alarms and fewer confirmed event detections than the baseline. The desired general improvement in both detection and false alarms has not been demonstrated.

V2 HistGradientBoosting with a causal 2-of-3 alarm was selected from 2019 calibration **before either final test was opened**. On the later final period, F1 was 76.55%, precision 84.09%, recall 70.25%, and confirmed detections 9/12. The shared prediction coverage was 86.09%; three events were fully unscorable and remain in the denominator. **V4 diagnostic clarification:** all three fall within the deliberately excluded first120 rows, not sensor-missing event rows. There are no raw missing EVENT minutes in that final file. Median detection delay was 2 nominal minutes among detected events. The final period contains only 12 events.

The six 2018 periods used expanding past-only training, a preceding calibration decile, 120-row gaps, reset feature history, and frozen model/threshold/persistence choices. V3 was developed after observing weak V2 results, so 2018 is explicitly retrospective; it is not an independent fresh validation of architectural choices. No random splitting, future imputation, label expansion, or point adjustment was used.

2019 actual timestamps determine the order: TRAIN (July–September 2017), VALID for calibration (October–8 November), then TEST for final evaluation (8–29 November). These data have six channels, versus nine in 2018. Models were retrained for that schema: this is a method evaluation, not transfer of a fixed checkpoint or demonstrated transfer to another site.

The selected six-channel artifact is 170,960 bytes. End-to-end inference over 65 history rows took a median 6.75 ms on the local ARM Mac, excluding sensor I/O and rendering. Raspberry Pi performance has not been measured. The interface returns alarm/no-alarm/unavailable and never grants valve-opening permission. No 3D integration has been performed.

See [reproduction and inference instructions](../ml/gecco_v3/USAGE.txt), [pre-test selection](../output/ml/gecco-comparison/release_choice.json), and the independent [V2 audit](../output/ml/gecco-v2/final_audit.json) and [V3 audit](../output/ml/gecco-v3/final_audit.json). Five-fault diagnosis, a calibrated sensor-trust score, and MAWRID field performance remain unproven.

## Completed experiment: GECCO baseline v1

See the [reproducible experiment](../ml/gecco_baseline/README.md),
[predeclared protocol](../ml/gecco_baseline/protocol.json), and
[actual results](../output/ml/gecco-baseline-v1/test_results.json).

Isolation Forest was trained on **80,621 clean normal windows**, using nine
channels and 36 causal features. Original acquisition order was divided
60%/20%/20%, with 30-minute gaps and independent feature warmups. Missing
measurements were retained as unavailable, not filled with apparently normal
values. The operating threshold was chosen on validation alone and frozen
before the held-out test.

| Metric | Validation | Held-out test |
|---|---:|---:|
| Point precision | 3.33% | 39.25% |
| Point recall | 0.57% | 54.55% |
| Unadjusted point F1 | 0.98% | 45.65% |
| Events with alarms / labeled events | 1 / 6 | 1 / 1 |
| Confirmed new alarm starts inside events | 1 / 6 | 1 / 1 |
| False-positive runs / eligible normal day | 0.936 | 1.922 |

**Interpretation:** the test contains only one event (77 minutes), of which 42
minutes were flagged and 35 missed. There were 65 false-positive minutes in 37
runs. The test failed the provisional target of at most one false-positive run
per normal day, although false-positive time remained below 1%. Poor validation
recall and the small test event count prevent a claim of reliable generalization.
The model is an offline baseline, not a calibrated sensor-trust score, a
five-fault classifier, or proof of water quality. GECCO chlorine channels are
chlorine dioxide; they are not interchangeable with free residual chlorine.

The following sections specify future field evidence requirements; their
candidate maintenance outputs have not been implemented by this baseline.

## Intended decision

Future analytics would support maintenance and inspection decisions by detecting abnormal process behaviour and estimating component condition. Version one uses transparent operating rules; it does not require a trained predictive model. Hydraulic clogging and adsorption exhaustion are different labels/tasks, and adsorption-life prediction applies only if an adsorption stage is justified and tested. The model does not determine water safety, certify an irrigation use, or open or override the independent outlet controller.

## Intended users

- Prototype engineers and researchers.
- Trained facility operators during a monitored pilot.
- Reviewers auditing model evidence and operational logs.

It is not intended for unattended public deployment or direct consumer interpretation.

## Candidate inputs

- Flow and cumulative treated volume.
- Differential pressure across granular media.
- Inlet and outlet turbidity.
- pH, temperature, and conductivity.
- Disinfection process condition.
- Sensor validity, calibration, and missing-data flags.
- Maintenance and media-replacement events.
- Time-aligned, quality-controlled laboratory results.
- Media identity and batch, selected adsorption constituent, and hydraulic/contact conditions when relevant.

## Candidate outputs

- Anomaly score and contributing signals.
- Component-condition category with an explanation, distinguishing hydraulic clogging from target-specific adsorption exhaustion.
- Possible sensor-drift flag.
- Recommended inspection, cleaning, sampling, or maintenance action.
- Remaining-useful-life estimate with uncertainty, only after sufficient validation.

## Current data maturity

The Git repository contains simulated telemetry for software demonstrations,
research code and selected evidence. The authoring workspace retained an unchanged
external GECCO2018 benchmark used for the completed offline experiment above; raw
benchmark files are excluded from Git and documented in the
[source inventory](../data/external-sources.json). It still contains no experimental MAWRID treatment result or field dataset
sufficient to validate operational predictions for MAWRID.

Sample calibration/quality flags, valve commands, and laboratory `MATCH` statuses are simulated cases. They do not prove actual calibration, physical actuation, or a reproduced sensor/laboratory comparison. The missing comparison-evidence fields are described in [data documentation](../data/README.md).

## Required training evidence

- Multiple independent treatment and media-life runs.
- Representative normal variation and declared fault injections.
- Complete calibration, maintenance, and laboratory records.
- Traceable exclusions and missing-data handling.
- Separation of runs and sites between training and evaluation to prevent leakage.
- Protocol-defined labels and event boundaries; separate training/evaluation complete runs rather than randomly splitting adjacent readings from the same run.

## Evaluation plan

| Function | Minimum evaluation |
|---|---|
| Anomaly detection | Event recall, false alarms per operating day, detection delay |
| Sensor-drift flag | Confirmed drift recall, false-positive rate, time to detection |
| Filter-health classification | Confusion matrix and calibration against declared condition labels |
| Maintenance forecast | Error distribution, uncertainty coverage, and comparison with a rule baseline |

Evaluation must be prospective before operational reliance. Define every metric, error denominator, event timing, uncertainty interval, and acceptance criterion before evaluation. Report actual independent-run counts and uncertainty; a small proposed minimum does not establish sufficient validation. Report performance by operating condition, sensor state, source-water range, and site where sample size permits. Targets in the [validation plan](validation.md) are provisional future-study criteria, not achieved scores.

## Human oversight

Every alert must include its timestamp, model or ruleset version, contributing measurements, confidence or uncertainty, and recommended next action. An operator reviews maintenance and calibration recommendations. Independent local outlet protection remains authoritative. Missing/invalid inputs trigger the declared invalid-data response; prediction must not substitute a reassuring value for a failed critical sensor.

## Known limitations

- Online sensors do not measure every chemical or microbial hazard.
- A model trained on one site may not transfer to another site.
- Laboratory and sensor measurements can differ because of sampling time, location, preservation, and method uncertainty.
- Simulated faults do not establish field performance.
- Drift in source water, hardware, or operating practice can degrade model performance.

## Change control

Each deployed model must have a version, training-data manifest, evaluation report, approval record, monitoring thresholds, rollback procedure, and retirement criterion.


## Current local-software evidence · 17 October 2026

The [local application verification](../output/mawrid-system/verification-v3.json) records 114 passing software tests and browser checks. Its [actual HTTP/SQLite inference integration](../output/mawrid-system/integration-v3.json) verifies the exact qualified **first 1,600 rows of GECCO2019 and first 1,600 rows of WaterHub April**, using genuine V9 inference with exact saved-batch sensor, clock and prediction parity and zero score error on those prefixes. Records persist after restart, while a fresh explicit session is required. This is a limited research replay on the qualified local environment, not arbitrary live-sensor readiness, all-period streaming qualification, an improved-model acceptance test, or Raspberry Pi performance evidence.

The [virtual-plant integration](../output/mawrid-system/plant-integration-v3.json) passes 12 assertion groups and preserves 133 full simulated snapshots. It tests fixed experimental rules, virtual balances, pause, faults, persistence and the background worker. No classifier is loaded for the virtual plant; its volumes and actuator states are simulated. The engineering 3D viewer remains a separate reference view, with no live control linkage in this evidence.

The [edge integration](../output/mawrid-system/edge-integration-v3.json) passes 55 checks using synthetic fixtures over isolated real loopback HTTP and SQLite. It covers a committed reading followed by a lost reply, durable retry without duplicate insertion, FIFO, restart receipts and a session-pinned request blocked after a session switch. It does not establish real-sensor acquisition, water treatment or hardware actuation; durability starts at successful queue commit, not unread stdin. These software results leave field-AI claim **C09 `NOT TESTED`** in the [evidence register](evidence-register.md).
