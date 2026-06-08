# Vendored third-party code — USGS Agisoft Alignment Error Reduction (Logan et al.)

This directory is a **verbatim, commit-pinned copy** of a U.S. Geological Survey
software release, vendored into this repo so the ESM Table S2 *Step 8 error reduction*
runs the published, capped-iterative gradual-selection routine instead of our own
transcription. See ADR-0023 for why (the 2026-06-08 EDR_T1 reduce collapse).

## ⚠ Why this is pinned to a COMMIT, not the v2.0 tag (read this)

The DOI-cited **v2.0 *tagged* release** (`v2.0`, 2023-01-13; DOI 10.5066/P9DGS5B9)
targets **Agisoft Metashape 1.6–1.8** and uses the pre-2.0 sparse-cloud API
(`chunk.point_cloud` / `Metashape.PointCloud.Filter`). On our pinned **Metashape
2.3.1** that API was renamed (`chunk.point_cloud` → `chunk.tie_points`;
`point_cloud` now means the *dense* cloud) so the tagged release **crashes**
(`AttributeError: 'NoneType' object has no attribute 'points'`).

The USGS authors ported the **same v2.0 workflow** to the Metashape 2.0 API on
`master` but **never cut a new release tag**. We verified (read-only, by download +
hash + diff) that `master`'s file differs from the v2.0-tag file by **only**:
(1) the `point_cloud`→`tie_points` / `PointCloud.Filter`→`TiePoints.Filter` accessor
rename (20 sites), and (2) the header Metashape-version string — i.e. the RU→PA→RE
thresholds, the capped-iterative loop, the optimize-between, and the final
fit-additional optimize are **byte-for-byte the cited v2.0 algorithm**. So we vendor
that 2.x-native commit: **same algorithm as the DOI v2.0, the API our build needs.**

Reproducibility is the **commit SHA + file sha256** below (there is no 2.x tag to
cite). The first vendoring (repo commit `3ec2789`) pinned the v2.0-tag archive — the
faithful-but-1.x artifact — which is what surfaced this; corrected here.

## Source (pinned)

| Field | Value |
|---|---|
| Title | AgisoftAlignmentErrorReduction (`Align_RuPaRe` — Reconstruction-uncertainty / Projection-accuracy / Reprojection-error gradual selection) |
| Authors | Logan, J.B., Wernette, P.A., and Ritchie, A.C. (USGS Pacific Coastal and Marine Science Center) |
| DOI (workflow v2.0) | https://doi.org/10.5066/P9DGS5B9 |
| Canonical repo | https://code.usgs.gov/pcmsc/AgisoftAlignmentErrorReduction |
| **Pinned commit** | **`aaee35f55096f17b612fa616aa8d91c21a05f8bf`** (J. Logan/USGS, 2024-03-20, *"update readme for Metashape 2.0"*) |
| Workflow version | **v2.0** (the cited workflow), **target Agisoft Metashape 2.0.x** |
| Commit-pinned raw base | `https://code.usgs.gov/pcmsc/AgisoftAlignmentErrorReduction/-/raw/aaee35f55096f17b612fa616aa8d91c21a05f8bf/` |
| Retrieved (UTC) | 2026-06-08 |

### File integrity (sha256, as vendored)

| File | sha256 |
|---|---|
| `Align_RuPaRe_v2_Metashape.py` | `69b0972628daf88ba6451fe9629eb82c10b183d41d580b45a88ef47932028aab` |
| `Readme.md` | `6260d13d0535302fe2c2dd2f4d1c369ece4bd1b80e570307d01929ab323a4910` |
| `CHANGELOG.txt` | `bfd5e68c1001818d371fc3dfdfffe00d83bf72769960f15d515e7163f0c8b5d0` |
| `code.json` | `803fc9643d04d89e076f022e8563da6a4462f84995d3d8717dfe55f465eb7ebf` |
| `LICENSE.md` | `b6ace2788425c3c0688ae6d87d1264f373b184767608e9a16462763b55f197d6` |
| `DISCLAIMER.md` | `0f047fb337cf96f01e79e93fd1366031279001da60b910194ad3271a90ead057` |

For reference, the **superseded** v2.0-tag artifact (do NOT re-vendor — it is 1.x):
archive `…/-/archive/v2.0/AgisoftAlignmentErrorReduction-v2.0.zip` sha256
`f124418878c51a0f756b5495d7c4ce76f5645e49f087e5caced2bdb9565db65f`; its
`Align_RuPaRe_v2_Metashape.py` sha256
`baaa3c91a8715f54a144b82e79c252b21f6d1b99afafb4980802ad428231ea1b`.

## What is vendored

`Align_RuPaRe_v2_Metashape.py` (the routine we call), plus `LICENSE.md`,
`DISCLAIMER.md`, `Readme.md`, `CHANGELOG.txt`, `code.json` from the same commit. The
`legacy_scripts/` tree (older Metashape/PhotoScan 1.4–1.8 variants) is intentionally
**not** vendored.

## How it is used (do NOT edit the vendored file)

`run_pipeline.py` imports this module **by file path** (no `sys.path` mutation) and
calls its `reconstruction_uncertainty()` → `projection_accuracy()` →
`reprojection_error()` functions on the chunk, passing Toth ESM Table S2 thresholds
(RU 30 → PA 3.5 → RE 0.3) with the script's capped per-iteration deletion
(`*_cutoff` 0.5/0.5/0.1) and camera optimization between iterations. The module is
import-safe: every executable statement is inside a `def`/`class` or the
`if __name__ == '__main__'` guard; importing it only requires `import Metashape` to
resolve (true under `metashape.sh`).

A **vendor-time identity check** (`run_pipeline.py::_vendored_logan_module`) asserts
the file declares **Metashape 2.0.x** and uses the **`tie_points`** API (not
`point_cloud`) before use — so a future mislabeled-artifact swap is caught at load
time, not during a live reduce (the failure mode this whole episode was).

**The vendored file is third-party and must stay byte-for-byte as released** — its
sha256 above is the integrity check. All EDR-specific orchestration lives in
`run_pipeline.py` (`_run_logan_reduction`), never in this file. To re-pin a newer
release/commit, drop in the new files, update the commit ref + hashes here, and note
it in ADR-0023.

## License

USGS software; see `LICENSE.md` and `DISCLAIMER.md` in this directory (U.S.
Government work / public domain with the standard USGS disclaimer).
