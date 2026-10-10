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

Predictive analytics are a later study; no trained or evaluated MAWRID model exists. See the [data and model card](../docs/data-and-model-card.md). The independent outlet controller must not depend on a prediction for release permission.
