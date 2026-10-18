# Data

The repository currently contains **no experimental MAWRID results**.

Data scope follows the [project brief](../docs/project-brief.md): one separate university ablution source and a proposed controlled ornamental-irrigation zone. The [evidence register](../docs/evidence-register.md) defines evidence labels and the requirements for adding a measured result. No confirmed university partner, laboratory commitment, or site approval is documented.

[`sample-telemetry.csv`](sample-telemetry.csv) is a small simulated dataset for dashboard and data-pipeline development. Every row is labeled `SIMULATED`; it must never be cited as prototype evidence.

`VALID` calibration/quality flags in that sample are simulated input states, not calibration certificates. Valve states are illustrative commands, not observed physical positions or measured outlet flow. The sample's cumulative volume is not a field water balance or water-saving result.

Future experimental datasets should include:

- A protocol identifier and version.
- Sample and run identifiers.
- Source, collection time, storage time, and test condition.
- Instrument, calibration, units, method, and detection limit.
- Raw measurements and explicit quality-control flags.
- Any exclusions with reasons.
- A license and data dictionary.
- For impact: the existing irrigation supply source, equivalent demand/period, collection, actual irrigation use, all potable inputs, rejection, backwash, overflow, and storage change, with their meter records.

## Schemas

- [`sensor-data-schema.csv`](sensor-data-schema.csv) defines the minimum online telemetry fields.
- [`laboratory-results-schema.csv`](laboratory-results-schema.csv) supplies a preliminary laboratory-record header and simulated example; it is not yet a complete reproducible comparison record.

The example laboratory row is `SIMULATED`. It demonstrates structure only and is not a MAWRID result.

A `MATCH` value in that example is also simulated. Before reporting a real comparison, retain the linked sensor timestamp/window, hydraulic time/location alignment, paired sensor value and unit, numerical difference, acceptance criterion/version, and calibration/quality-control records. A device identifier alone cannot reproduce the comparison. Add those fields to a versioned schema or attach a referenced record before publishing an actual comparison result. See [sensor and laboratory workflow](../docs/sensor-and-lab-workflow.md).

An external GECCO2018 drinking-water dataset was retained unchanged in the
authoring workspace under `external/gecco2018/`, with source inspection metadata.
Raw benchmark files are excluded from Git. The
[source inventory](external-sources.json) provides publisher links, licenses,
filenames and checksums; the optional [research assets](../docs/research-assets.md)
provide only the two exact qualified sensor prefixes and selected V9 artifacts. On 16 October 2026, an offline Isolation Forest baseline
was trained and evaluated on chronological partitions of it. This is not a
MAWRID treatment result or field validation. See the
[experiment and actual results](../ml/gecco_baseline/README.md) and
[data and model card](../docs/data-and-model-card.md). Predictive maintenance and
five-fault classification remain unvalidated. The independent outlet controller
must not depend on a prediction for release permission.


## Additional chronological comparison

GECCO2019 raw files were retained in the authoring workspace under
`external/gecco2019/`; the [source inventory](external-sources.json) preserves
their publisher URLs and checksums without adding the raw files to Git.
A label-blind audit established actual order TRAIN → VALID (calibration) → TEST
(final); file names alone would give a misleading chronological order. There
were no overlapping timestamps with the 2018 source. The schemas differ: six
channels in 2019 versus nine in 2018, requiring retraining of the method.

Six retrospective expanding periods in 2018 and a later held-out 2019 period
were evaluated in v2/v3. Both positive and negative results, unavailable rows,
and original event denominators are included in the
[comparison report](../output/ml/gecco-comparison/report.html). Improvements in
the additional period did not establish stable gains across the six older
periods. These are external benchmark results, not MAWRID field evidence.

## V4 historical external check

The unchanged [GECCO2017 source](https://zenodo.org/records/3884465) was retained
in the authoring workspace at `external/gecco2017/1_gecco2017_water_quality.csv`
and is excluded from Git: 122,334 rows from
15 February to10 May2016, with the same nine channel names as2018. Its publisher
MD5 was verified. A label-blind audit found no timestamp overlap with2018/2019
and no matching complete60-row sensor sequences with2018. The single forward
wall-clock jump is preserved in acquisition order.

After all2018/2019 outcomes had become development evidence, V4's method and
six-period evaluation were frozen before2017 EVENT access. The method used
only earlier local rows for each fit/calibration, but its design benefited from
historically later datasets; this is a new historical dataset check, not a
simulation of deployment without hindsight. All six outer outcomes were
reviewed together after completion.

V4 lowered false alarms but detected21/55 events versus46/55 for the original
algorithm refitted on matching past data. It failed the joint improvement gate
and was not promoted or connected to3D. See the [V4 report](../output/ml/gecco-v4/report.html),
[source audit](../output/ml/gecco-v4-diagnostics/new_source_audit.json), and
[current model card](../docs/data-and-model-card.md). The2017 outcomes are now
also disclosed; reuse cannot be advertised as another unseen test.

## Current public research availability

The [model card](../docs/data-and-model-card.md) is the current research-status
record. V15 completed all 19 disclosed development periods, selected unchanged
V8 decisions in every period, and was not promoted. Historical results below
retain their own protocols; no benchmark result is a MAWRID field-water result.

The Git checkout includes simulated examples, schemas, source metadata and
selected research reports. Raw collections, virtual environments and bulk model
artifacts are excluded. The optional [V9 asset package](../docs/research-assets.md)
contains two sensor-only prefixes and two fitted bundles, with manifests and
qualification records. It requires the recorded Darwin arm64/pandas 3.0.6 kernel
and does not run in the standard clone environment. The virtual-plant simulation
remains separate and does not load that classifier.
