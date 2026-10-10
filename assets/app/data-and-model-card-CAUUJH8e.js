var e=`# Data and Model Card\r
\r
> **Model status:** \`NOT TRAINED\`. This document defines the intended evidence and evaluation contract for future MAWRID analytics.\r
\r
Scope follows the [project brief](project-brief.md): one separately collected university ablution source and a proposed controlled ornamental-irrigation zone. Evidence status follows the [evidence register](evidence-register.md). No university partnership, field approval, real operating dataset, or model-performance result is documented.\r
\r
## Intended decision\r
\r
Future analytics would support maintenance and inspection decisions by detecting abnormal process behaviour and estimating component condition. Version one uses transparent operating rules; it does not require a trained predictive model. Hydraulic clogging and adsorption exhaustion are different labels/tasks, and adsorption-life prediction applies only if an adsorption stage is justified and tested. The model does not determine water safety, certify an irrigation use, or open or override the independent outlet controller.\r
\r
## Intended users\r
\r
- Prototype engineers and researchers.\r
- Trained facility operators during a monitored pilot.\r
- Reviewers auditing model evidence and operational logs.\r
\r
It is not intended for unattended public deployment or direct consumer interpretation.\r
\r
## Candidate inputs\r
\r
- Flow and cumulative treated volume.\r
- Differential pressure across granular media.\r
- Inlet and outlet turbidity.\r
- pH, temperature, and conductivity.\r
- Disinfection process condition.\r
- Sensor validity, calibration, and missing-data flags.\r
- Maintenance and media-replacement events.\r
- Time-aligned, quality-controlled laboratory results.\r
- Media identity and batch, selected adsorption constituent, and hydraulic/contact conditions when relevant.\r
\r
## Candidate outputs\r
\r
- Anomaly score and contributing signals.\r
- Component-condition category with an explanation, distinguishing hydraulic clogging from target-specific adsorption exhaustion.\r
- Possible sensor-drift flag.\r
- Recommended inspection, cleaning, sampling, or maintenance action.\r
- Remaining-useful-life estimate with uncertainty, only after sufficient validation.\r
\r
## Current data maturity\r
\r
The repository contains simulated telemetry for software and demonstration testing. It contains no experimental MAWRID treatment result and no dataset sufficient to train or validate a predictive model.\r
\r
Sample calibration/quality flags, valve commands, and laboratory \`MATCH\` statuses are simulated cases. They do not prove actual calibration, physical actuation, or a reproduced sensor/laboratory comparison. The missing comparison-evidence fields are described in [data documentation](../data/README.md).\r
\r
## Required training evidence\r
\r
- Multiple independent treatment and media-life runs.\r
- Representative normal variation and declared fault injections.\r
- Complete calibration, maintenance, and laboratory records.\r
- Traceable exclusions and missing-data handling.\r
- Separation of runs and sites between training and evaluation to prevent leakage.\r
- Protocol-defined labels and event boundaries; separate training/evaluation complete runs rather than randomly splitting adjacent readings from the same run.\r
\r
## Evaluation plan\r
\r
| Function | Minimum evaluation |\r
|---|---|\r
| Anomaly detection | Event recall, false alarms per operating day, detection delay |\r
| Sensor-drift flag | Confirmed drift recall, false-positive rate, time to detection |\r
| Filter-health classification | Confusion matrix and calibration against declared condition labels |\r
| Maintenance forecast | Error distribution, uncertainty coverage, and comparison with a rule baseline |\r
\r
Evaluation must be prospective before operational reliance. Define every metric, error denominator, event timing, uncertainty interval, and acceptance criterion before evaluation. Report actual independent-run counts and uncertainty; a small proposed minimum does not establish sufficient validation. Report performance by operating condition, sensor state, source-water range, and site where sample size permits. Targets in the [validation plan](validation.md) are provisional future-study criteria, not achieved scores.\r
\r
## Human oversight\r
\r
Every alert must include its timestamp, model or ruleset version, contributing measurements, confidence or uncertainty, and recommended next action. An operator reviews maintenance and calibration recommendations. Independent local outlet protection remains authoritative. Missing/invalid inputs trigger the declared invalid-data response; prediction must not substitute a reassuring value for a failed critical sensor.\r
\r
## Known limitations\r
\r
- Online sensors do not measure every chemical or microbial hazard.\r
- A model trained on one site may not transfer to another site.\r
- Laboratory and sensor measurements can differ because of sampling time, location, preservation, and method uncertainty.\r
- Simulated faults do not establish field performance.\r
- Drift in source water, hardware, or operating practice can degrade model performance.\r
\r
## Change control\r
\r
Each deployed model must have a version, training-data manifest, evaluation report, approval record, monitoring thresholds, rollback procedure, and retirement criterion.\r
`;export{e as default};