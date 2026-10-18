var e=`# Optional V9 research assets

The normal MAWRID application is a local software simulation. Its digital twin
reads the virtual-plant backend and uses explicit experimental operating rules.
V9 is a separate, limited public-data research replay. It is not the virtual
plant's classifier and is not field-qualified.

## Distribution and exact scope

Download [mawrid-v9-research-assets.zip — v0.3.0](https://github.com/SultanAlfaifi/mawrid-water-reuse/releases/download/v0.3.0/mawrid-v9-research-assets.zip).

SHA-256: \`e359023288d526396c2e348f75fd8899a5d20acf1e7951c4713e0d170915d0ff\`.

The [Git manifest](research-assets-manifest.json) records the archive SHA-256,
byte size, and every member's digest. The source checkout itself has no raw
benchmark collections, fitted research bundles, or bundled Python environment.
The archive is optional; it does not make V9 portable.

The archive contains **82 files**, **24,797,225 compressed bytes**, and
**36,777,773 uncompressed bytes**:

- The unchanged V9 run plan, full 19-period results, independent batch audit,
  and original failed streaming audit.
- The 63 immutable source copies named by that plan, preserving their original
  paths and hashes.
- Only the \`2019_disclosed_test\` and \`2019-04\` fitted bundles, each with its
  original freeze and result record.
- The later two-prefix numerical verification plan, results, and sensor-input
  qualification record.
- Two exact sensor-only CSVs: the first **1,600 rows** of GECCO2019 and WaterHub
  April, with their actual original/adapted clocks.
- Dataset attribution, the pandas notice, an internal manifest, and a README.

It excludes other periods' weights, bulk prediction/calibration arrays, complete
raw collections, third-party source archives, caches, and virtual environments.
The full historical results remain in the run metadata; their inclusion does
not imply that all 19 fitted bundles or full-period replay inputs are supplied.
Matching research/runtime source in the Git checkout remains required.

## Integrity and extraction

From the repository root, compare the downloaded archive against the manifest
before extraction. This standard-library command verifies all member bytes;
it neither imports ML dependencies nor loads a model:

\`\`\`sh
python3 - path/to/mawrid-v9-research-assets.zip <<'PY'
import hashlib, json, pathlib, sys, zipfile
archive = pathlib.Path(sys.argv[1])
manifest = json.loads(pathlib.Path('docs/research-assets-manifest.json').read_text())
assert archive.stat().st_size == manifest['archive']['bytes']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive']['sha256']
with zipfile.ZipFile(archive) as bundle:
    assert len(bundle.namelist()) == len(set(bundle.namelist()))
    assert set(bundle.namelist()) == {item['path'] for item in manifest['members']}
    for item in manifest['members']:
        name = pathlib.PurePosixPath(item['path'])
        assert not name.is_absolute() and '..' not in name.parts
        data = bundle.read(item['path'])
        assert len(data) == item['bytes']
        assert hashlib.sha256(data).hexdigest() == item['sha256']
print('Archive and all member hashes match; no model was loaded.')
PY
unzip -n path/to/mawrid-v9-research-assets.zip -d .
\`\`\`

Extract into the root of the matching checkout, keeping repository-relative
paths. \`unzip -n\` preserves existing local files. If existing evidence differs,
use a fresh checkout rather than overwriting a frozen record. The internal
manifest hashes every other payload member; its own digest is in the external
Git manifest, avoiding a self-hash dependency.

Joblib is executable serialization. Matching hashes establish consistency with
this manifest, not trust in an arbitrary archive. Review provenance and use only
trusted release assets before allowing the original model loader to run.

## Environment gate and replay

The preserved numerical qualification records:

| Component | Qualified record |
|---|---|
| Platform string | \`macOS-27.0.1-arm64-arm-64bit\` |
| CPU / operating system | Darwin arm64 |
| Python | 3.12.1 |
| NumPy | 2.5.4 |
| pandas | 3.0.6 |
| Thread-pool limit | 1 |
| pandas compiled kernel SHA-256 | \`07cf0f94b1a3b55574aacca4927b52fdcd8821fb5eba10ce2e3f849c276dd3cb\` |

The fitting plan additionally records scikit-learn 1.9.1. An ordinary Python
installation, Linux CI runner, Intel Mac, later macOS version, or Raspberry Pi
has not been qualified for this replay. Version numbers alone do not guarantee
an identical compiled kernel. **V9 is unavailable from a standard clone until
these optional assets and the exact environment pass the retained gates.**
No portable substitute or bypass is supplied.

Only in that qualified environment, with a new output filename, the original
research CLI can replay one of the accepted prefixes:

\`\`\`sh
python -m ml.gecco_stream_fidelity.prototype \\
  --run output/ml/gecco-v9-development/run_01 \\
  --case 2019_disclosed_test \\
  --input output/ml/gecco-stream-fidelity/prototype-demo/2019_disclosed_test_first1600_sensors.csv \\
  --output output/research-replay/gecco2019.csv \\
  --research-preview
\`\`\`

For WaterHub April, change \`--case\` to \`2019-04\` and input to
\`output/ml/gecco-stream-fidelity/prototype-demo/2019-04_first1600_sensors.csv\`.
Keep outputs separate from the immutable release files. The CLI still checks
full-run metadata, frozen/current source hashes, bundle hashes, qualification,
exact input digest, channel order, actual clock, and environment before replay.
It does not accept arbitrary new sensor CSVs. \`--research-preview\` acknowledges
the failed development acceptance; it does not override numerical/input gates.

## What passed, and what did not

V9's batch audit passed on all 19 disclosed periods. Its development result was
**113/399 confirmed events**, **237 false-alarm fragments**, and **478 false-alarm
minutes**. The joint retention/improvement acceptance failed. The original
streaming audit also failed and is retained unchanged. A later, separate
implementation-fidelity check passed only for these two exact initial prefixes;
it does not turn the old streaming result or the all-period quality decision
into a pass. V15 later reproduced V8 decisions and was not promoted either.

These are measured results on public research benchmarks in recorded local
environments. They are not measured MAWRID treatment performance, a sensor-trust
probability, five-fault classification, independent new-site validation,
Raspberry Pi latency, chemical/microbial safety, or permission to open a valve.
The [model card](data-and-model-card.md) preserves full denominators and limits.

Release packaging verified metadata/hash gates for both V9 cases, 63 frozen
source records, 72 current qualified code records, qualification links, and ZIP
CRC/member hashes. Packaging did **not** decode sensor rows, unpickle weights,
rerun inference/training, or requalify the host environment. Those precise checks
are recorded in the [manifest](research-assets-manifest.json).

## Source rights and attribution

- GECCO datasets are published under **CC BY 4.0**: [2017](https://zenodo.org/records/3884465),
  [2018](https://zenodo.org/records/3884398), and [2019](https://zenodo.org/records/4304080).
  Only a sensor-only GECCO2019 prefix is redistributed in this archive. Channel
  order and the actual serialized 2017 timestamps are preserved; event/label
  columns are absent.
- WaterHub/NEST comes from Russo et al., *Data for: The Value of Human Data
  Annotation for Machine Learning based Anomaly Detection in Environmental
  Systems*, Eawag, 2020, version 1.0,
  [DOI 10.25678/0002WJ](https://doi.org/10.25678/0002WJ).
  Retained publisher DataCite metadata declares **CC0-1.0**. The supplied sensor
  prefix derives from the frozen minute-end adapter and retains missing sensor
  values; it contains no label columns.
- The checkout's rolling implementation adapts pandas recurrences under
  **BSD-3-Clause**; retain
  [\`PANDAS_LICENSE\`](../ml/gecco_stream_fidelity/PANDAS_LICENSE).
  This package includes no software copied from the source-data archives.

The [source inventory](../data/external-sources.json) preserves original source
and adapted-source hashes. Dataset rights are separate from software rights.
`;export{e as default};