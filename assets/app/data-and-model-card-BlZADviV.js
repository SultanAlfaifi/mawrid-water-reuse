var e=`# Data and Model Card

> **Model status:** \`NOT TRAINED\`. This document defines the intended evidence and evaluation contract for future MAWRID analytics.

Scope follows the [project brief](project-brief.md): one separately collected university ablution source and a proposed controlled ornamental-irrigation zone. Evidence status follows the [evidence register](evidence-register.md). No university partnership, field approval, real operating dataset, or model-performance result is documented.

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

The repository contains simulated telemetry for software and demonstration testing. It contains no experimental MAWRID treatment result and no dataset sufficient to train or validate a predictive model.

Sample calibration/quality flags, valve commands, and laboratory \`MATCH\` statuses are simulated cases. They do not prove actual calibration, physical actuation, or a reproduced sensor/laboratory comparison. The missing comparison-evidence fields are described in [data documentation](../data/README.md).

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
`;export{e as default};