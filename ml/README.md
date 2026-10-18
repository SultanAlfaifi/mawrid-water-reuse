# MAWRID anomaly-detection research

This directory preserves the experiment source, tests, protocols, report builders,
and audit tools. It does not contain a field-qualified MAWRID model. The local
plant simulation uses transparent experimental rules; the separate V9 research
replay consumes only two exact qualified public-data prefixes.

Start with the [data and model card](../docs/data-and-model-card.md), then the
[research-asset guide](../docs/research-assets.md). The
[external-source inventory](../data/external-sources.json) records origin,
licenses, source hashes, and data availability.

## What the evidence establishes

| Evidence | Meaning |
|---|---|
| [Original baseline](gecco_baseline/README.md) | Chronological Isolation Forest experiment; its held-out test had only one labeled event. |
| [V8 report](../output/ml/gecco-v8/report.html) | Completed 19-period disclosed development comparison: 117/399 confirmed events; 235 false-alarm fragments. |
| [V9 report](../output/ml/gecco-v9/report.html) | 113/399 confirmed events; 237 false-alarm fragments. Numerical batch audit passed, but the acceptance gate failed. |
| [V15 report](../output/ml/gecco-v15/report.html) | Completed policy experiment; all final decisions equal V8, with no new improvement or model promotion. |
| [Qualified V9 prefixes](../docs/research-assets.md) | Numerical implementation fidelity for the first 1,600 rows of GECCO2019 and WaterHub April only. |

Counts belong to their declared protocols and evaluation masks; an audit PASS
means reproducibility/consistency, not acceptable detection quality. All current
benchmark sources were disclosed during development. None is MAWRID field water
or a fresh holdout for another model revision. Five-fault sensor classification,
calibrated sensor-trust probability, water safety, and Raspberry Pi timing remain
unvalidated. A prediction never grants outlet-opening permission.

## Checkout versus optional research assets

The Git checkout includes research source and selected small reports/audits. It
excludes virtual environments, raw benchmark collections, bulk arrays, and the
hundreds of historical fitted checkpoints. The optional V9 release archive adds
only two fitted bundles, their two sensor-only prefixes, run metadata, immutable
source copies, and qualification evidence. It is **not** a complete re-training
archive for every version.

V9 replay **does not run in a standard clone/environment**. Its retained gate
requires Darwin arm64, the exact recorded Python/NumPy/pandas environment, and a
specific pandas 3.0.6 compiled numerical-kernel digest. The verification record
also compares the full platform string. Installing dependencies with matching
version names alone does not establish that qualification. No wheels, environment,
or `.venv` are distributed. Keep the gates intact; use the normal local simulation
when the research environment is unavailable.

## Published report archive

[`scripts/ml-publication-files.json`](../scripts/ml-publication-files.json) is
the explicit publication inventory: 217 files (178,188,445 bytes before Git
compression), including all 15 current main HTML reports, 10 status records,
9 metric CSVs, their figures, and the linked core protocols, results, freezes,
and audits. These are distinct experiment/case records; bulk source snapshots
and model/prediction collections are not copied into the report archive.
Negative outcomes and interrupted/failing attempts remain visible.

The original HTML reports are preserved unchanged. Their relative links to
core metadata and figures are included by the inventory. Some historical
download links intentionally point outside the published archive: fitted
weights, per-row prediction CSV.gz files, the old V4 evaluation ZIP, and the
public-source-search archive. Those links describe files retained in the
authoring workspace, not files supplied by this checkout. Directory links
open the published subset rather than the complete historical directory.
No original report has been rewritten to imply that these omitted assets
are available or that a failed result passed.

The optional V9 release assets described below are separately scoped to two
exact prefixes; they do not supply every historical model linked by the reports.

## Reading and reproducing experiments

Version directories retain their original procedure and history. See
[`gecco_baseline/README.md`](gecco_baseline/README.md),
[`gecco_v3/USAGE.txt`](gecco_v3/USAGE.txt), and
[`gecco_v4/USAGE.txt`](gecco_v4/USAGE.txt) for historical entry points. Their input
and output paths assume the original repository layout, and their pinned versions
record the measured environment rather than promise availability on every package
index. Download data from the publisher and verify the recorded hashes before
attempting a reproduction in a separate working/output directory. Do not overwrite
frozen evidence or call a retest on disclosed outcomes a new independent test.

The V9 archive guide provides the narrower replay procedure. Joblib files are
executable serialization: use trusted artifacts and the existing hash/metadata
gates before loading them. The release packaging check itself performs no model
loading, numerical inference, fitting, or sensor-row decoding.

## Third-party material

`gecco_stream_fidelity/rolling.py` adapts pandas numerical recurrences; retain
[`PANDAS_LICENSE`](gecco_stream_fidelity/PANDAS_LICENSE) and its upstream attribution.
Dataset licenses are recorded separately and do not license unrelated archive
software. Raw third-party project archives are not part of this checkout or the
optional replay package.
