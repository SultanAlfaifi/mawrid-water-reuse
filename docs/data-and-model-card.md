# Data and Model Card

> **Model status:** `NOT TRAINED`. This document defines the intended evidence and evaluation contract for future MAWRID analytics.

## Intended decision

The proposed model supports maintenance and inspection decisions by detecting abnormal process behaviour and estimating filter condition. It does not determine that water is safe and does not authorize reuse.

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

## Candidate outputs

- Anomaly score and contributing signals.
- Filter-health category with an explanation.
- Possible sensor-drift flag.
- Recommended inspection, cleaning, sampling, or maintenance action.
- Remaining-useful-life estimate with uncertainty, only after sufficient validation.

## Current data maturity

The repository contains simulated telemetry for software and demonstration testing. It contains no experimental MAWRID treatment result and no dataset sufficient to train or validate a predictive model.

## Required training evidence

- Multiple independent treatment and media-life runs.
- Representative normal variation and declared fault injections.
- Complete calibration, maintenance, and laboratory records.
- Traceable exclusions and missing-data handling.
- Separation of runs and sites between training and evaluation to prevent leakage.

## Evaluation plan

| Function | Minimum evaluation |
|---|---|
| Anomaly detection | Event recall, false alarms per operating day, detection delay |
| Sensor-drift flag | Confirmed drift recall, false-positive rate, time to detection |
| Filter-health classification | Confusion matrix and calibration against declared condition labels |
| Maintenance forecast | Error distribution, uncertainty coverage, and comparison with a rule baseline |

Evaluation must be prospective before operational reliance. Report performance by operating condition, sensor state, source-water range, and site where sample size permits.

## Human oversight

Every alert must include its timestamp, model or ruleset version, contributing measurements, confidence or uncertainty, and recommended next action. An operator reviews maintenance and calibration recommendations. Safety rules remain authoritative.

## Known limitations

- Online sensors do not measure every chemical or microbial hazard.
- A model trained on one site may not transfer to another site.
- Laboratory and sensor measurements can differ because of sampling time, location, preservation, and method uncertainty.
- Simulated faults do not establish field performance.
- Drift in source water, hardware, or operating practice can degrade model performance.

## Change control

Each deployed model must have a version, training-data manifest, evaluation report, approval record, monitoring thresholds, rollback procedure, and retirement criterion.
