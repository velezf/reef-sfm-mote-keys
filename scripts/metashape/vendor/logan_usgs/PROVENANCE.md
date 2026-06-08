# Vendored third-party code — USGS Agisoft Alignment Error Reduction (Logan et al.)

This directory is a **verbatim, pinned copy** of a U.S. Geological Survey software
release, vendored into this repo so the ESM Table S2 *Step 8 error reduction* runs
the published, capped-iterative gradual-selection routine instead of our own
transcription. See ADR-0023 for why (the 2026-06-08 EDR_T1 reduce collapse).

## Source (pinned)

| Field | Value |
|---|---|
| Title | AgisoftAlignmentErrorReduction (`Align_RuPaRe` — Reconstruction-uncertainty / Projection-accuracy / Reprojection-error gradual selection) |
| Authors | Logan, J.B., and others (USGS Pacific Coastal and Marine Science Center) |
| DOI | https://doi.org/10.5066/P9DGS5B9 |
| Canonical repo | https://code.usgs.gov/pcmsc/AgisoftAlignmentErrorReduction |
| Version / tag | **v2.0** |
| Archive URL | https://code.usgs.gov/pcmsc/AgisoftAlignmentErrorReduction/-/archive/v2.0/AgisoftAlignmentErrorReduction-v2.0.zip |
| Retrieved (UTC) | 2026-06-08 |
| Archive sha256 | `f124418878c51a0f756b5495d7c4ce76f5645e49f087e5caced2bdb9565db65f` |
| `Align_RuPaRe_v2_Metashape.py` sha256 | `baaa3c91a8715f54a144b82e79c252b21f6d1b99afafb4980802ad428231ea1b` |

## What is vendored

`Align_RuPaRe_v2_Metashape.py` (the routine we call), plus `LICENSE.md`,
`DISCLAIMER.md`, `Readme.md`, `CHANGELOG.txt`, `code.json` from the release. The
`legacy_scripts/` tree from the archive is intentionally **not** vendored (older
Metashape/PhotoScan 1.4–1.6 variants we do not use).

## How it is used (do NOT edit the vendored file)

`run_pipeline.py` imports this module **by file path** (no `sys.path` mutation) and
calls its `reconstruction_uncertainty()` → `projection_accuracy()` →
`reprojection_error()` functions on the chunk, passing Toth ESM Table S2 thresholds
(RU 30 → PA 3.5 → RE 0.3) with the script's capped per-iteration deletion
(`*_cutoff` 0.5/0.5/0.1) and camera optimization between iterations. The module is
import-safe: every executable statement is inside a `def`/`class` or the
`if __name__ == '__main__'` guard; importing it only requires `import Metashape` to
resolve (true under `metashape.sh`).

**The vendored file is third-party and must stay byte-for-byte as released** — its
sha256 above is the integrity check. All EDR-specific orchestration lives in
`run_pipeline.py` (`_run_logan_reduction`), never in this file. To update, re-pin a
new release tag here with a fresh hash and note it in ADR-0023.

## License

USGS software; see `LICENSE.md` and `DISCLAIMER.md` in this directory (U.S.
Government work / public domain with the standard USGS disclaimer).
