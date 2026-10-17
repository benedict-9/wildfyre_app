# Fire-persistence model

WildFyre serves the accepted **wf08-rf-v1** Random Forest through a validated
portable export. The original joblib and historical datasets remain private
release assets; only the reviewed serving forest is bundled in Git.

## Target and preparation

For an already-active approximate 5 km cell, inputs aggregate one six-hour
window [t,t+6h). Target 1 means another qualifying FIRMS detection occurs in
the same cell during [t+6h,t+30h); otherwise target 0. This predicts detection
persistence, not spread, arrival time, animal danger or evacuation need.

Training uses 2022+2023 (8,549 rows), with 2024 held out for evaluation
(4,467 rows). The corrected preparation reproduces 65,072 qualifying detections
and 13,016 modelling windows with explicit horizon censoring. The pipeline is
a median imputer and a 300-tree Random Forest, random seed 42, balanced class
weights and 13 ordered features. Counts, FRP, brightness, confidence/day-night
counts, month and UTC hour are defined in the authoritative
[model.json](../models/fire-persistence/model.json).

## Evaluation

| Metric | Majority baseline | Accepted forest |
| --- | ---: | ---: |
| Accuracy | 0.5551824491 | 0.7318110589 |
| Balanced accuracy | 0.5000000000 | 0.7292544686 |
| Positive precision | 0 | 0.6955875062 |
| Positive recall | 0 | 0.7060895823 |
| Positive F1 | 0 | 0.7007992008 |
| ROC AUC | 0.5000000000 | 0.7930981825 |

Confusion matrix: [[1866,614],[584,1403]]. Independent local verification
reproduced these results and unchanged predictions/probabilities after reload.
See the [source-model evidence](evidence/fire-persistence-verification.json).

Training-runtime metadata reports s390x Python 3.12.15, sklearn 1.9.0,
joblib 1.6.0 and NumPy 2.0.2. Independent verification used Windows AMD64,
Python 3.12.14, sklearn 1.9.0, joblib 1.6.0, NumPy 2.0.2, SciPy 1.13.1 and
pandas 3.0.6. Runtime metadata is provenance, not a new remote execution claim.

## Portable serving artifact

[forest.json.gz](../models/fire-persistence/forest.json.gz) contains 300 trees,
979,094 nodes, finite imputer medians and exact feature/class metadata.
Its size is 7,742,804 bytes and SHA-256 is
cca817222abb5c59a4d7e218a73b22c80d1efb17d3caab9d2f9c84e3f8425a49.

The standard-library scorer reproduces the original forest's probabilities and
classes exactly on all 4,467 held-out rows plus 149 missing-value/threshold cases.
Live aggregation matches all 13,016 historical cell-windows within a maximum
absolute error of 5.684e-14.
[Portable verification](evidence/fire-persistence-portable-verification.json)
records the comparison.

Startup verifies the bundle, prepares its cache atomically, and loads/self-checks
the forest once. Input conversion follows float32 tree semantics. Integrity,
schema, feature order, tree bounds and finite output are checked. Serving never
deserializes pickle and has no scientific runtime dependency.

## Reproduce offline verification

The canonical [notebook](../notebooks/fire_persistence.ipynb) keeps downloads
and training off by default. In an isolated environment using
[the scientific requirements](../notebooks/requirements-fire-persistence.txt),
download the three essential source assets with authenticated GitHub CLI:

```bash
gh release download wf08-rf-v1 --repo benedict-9/wildfyre --dir artifacts/fire-persistence-source --pattern fire_persistence_random_forest.joblib --pattern firms_california_2022_2024_vegetation_fire.csv --pattern fire_persistence_windows_2022_2024.csv
python notebooks/verify_fire_persistence.py --artifact-dir artifacts/fire-persistence-source
python notebooks/export_fire_persistence.py --artifact-dir artifacts/fire-persistence-source --output-dir artifacts/portable-export
```

The verifier checks source hashes before loading the trusted joblib, rebuilds
prepared features/labels and repeats evaluation without retraining. The exporter
also checks live-feature parity and writes deterministic gzip/parity evidence.
The identical serving export is archived in
[wf09-rf-portable-v1](https://github.com/benedict-9/wildfyre/releases/tag/wf09-rf-portable-v1);
this private release requires authentication, while application startup uses the bundled file from the checkout.

## Live limitations and acceptance

Live VIIRS_SNPP_NRT transfer remains experimental. Training used historical
SP vegetation detections; missing type must not be inferred as vegetation.
Missing classification/header inputs or malformed contributing rows stay
unavailable; only genuine numeric missingness uses medians. A clock-closed
window does not prove complete satellite delivery.

Inherited historical collection coverage, regional/seasonal scope, satellite
revisit/cloud effects, serial correlation, exploratory use of 2024 and
unverified calibration limit interpretation. No new retraining or ablation
is claimed.

WF08 was accepted with a remote-inference waiver. On 2026-10-18 SGT the user
also requested WF09 closeout after local acceptance, without another server
check. Actual LinuxONE inference remains unverified; issue closure is not
a remote test result.
