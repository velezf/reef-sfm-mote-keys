# Provenance — USGS Metashape Alignment Helper (ESM Step 11)

Vendored third-party tool for ESM Step 11 (coordinate-frame placement: local
zero-point center + midline refinement). Not authored by this project.

## Chosen artifact (installed)

- **File:** `vendor/usgs/AlignmentHelper_v1.py`
- **Upstream tag:** `v1.0.1` (released 2025-09-12), commit `02c59678`
- **Upstream raw path:**
  `https://code.usgs.gov/spcmsc/metashape-alignment-helper/-/raw/v1.0.1/AlignmentHelper_v1.py`
- **sha256:** `ba860a6aa985232d3008a1e804e66e31ad79b7eb564fbd40e4ed34625a2819d3`
- **`python -m py_compile`:** PASS
- **Menu registration:** `Metashape.app.addMenuItem("Helpers/Alignment Helper v1.0.1", main)`
- **Retrieved-at (UTC):** 2026-06-02T12:35:34Z

## Identity / citation

- **DOI:** 10.5066/P9YN4KDX
- **Cite:** Jenkins, C.M., and Johnson, S.A., 2024, *Agisoft Metashape Alignment
  Helper Version 1.0*: U.S. Geological Survey software release,
  https://doi.org/10.5066/P9YN4KDX
- Referred to in our docs as "Jenkins & Kupfner Johnson 2024 v1.0" (ADR-0010).
- **DOI resolution note:** 10.5066/P9YN4KDX now redirects to the USGS GitLab repo
  `https://code.usgs.gov/spcmsc/metashape-alignment-helper` (not a ScienceBase
  landing page).

## License

- **CC0 1.0 Universal** / U.S. public domain (USGS software release; see upstream
  `LICENSE.md` and `DISCLAIMER.md`). Permissive — vendoring into this repo is
  allowed. USGS disclaims all warranty.

## REJECTED artifact (do NOT use / do NOT install)

- **File:** `AlignmentHelper_v1.1.0.py` on branch `main`, HEAD `ce555cb7`
- **Raw path:**
  `https://code.usgs.gov/spcmsc/metashape-alignment-helper/-/raw/main/AlignmentHelper_v1.1.0.py`
- **sha256:** `620670d4fb90c065fa45c88668f6b0d0cdb667926353eb5904da42b408e0d603`
- **`python -m py_compile`:** FAIL — **non-importable**.
- **Reason:** two unresolved Git merge-conflict markers committed into the file
  (`<<<<<<< HEAD` / `=======` / `>>>>>>>` at **lines 89 and 695**), introduced by
  a botched dev→main merge on **2026-05-11** (conflict side `c1b925dd`, "remove
  exampleWalkthrough.mp4"). Both conflicts are tooltip-only (cosmetic), but the
  markers alone make the file fail to parse, so Metashape would refuse to load it.
- The original install path requested (`main/AlignmentHelper.py`) **404s** — the
  file was renamed upstream to `AlignmentHelper_v1.1.0.py`.

## Metashape version compatibility

- **Declared (v1.0.1 README):** developed with Metashape 1.8.3, "known to be
  compatible with Metashape versions up to **2.1.0**."
- **Our runtime:** Metashape Professional **2.3.1** build 22446 (pinned per
  ADR-0002).
- ⚠️ **Above the declared compat ceiling.** The live GUI load-test on 2.3.1 is the
  next step (in DCV); compatibility on 2.3.1 is unverified at vendor time.

## Install location

- GUI auto-load dir: `~/.local/share/Agisoft/Metashape Pro/scripts/AlignmentHelper_v1.py`
  (Linux equivalent of the README's Windows
  `%LOCALAPPDATA%\Agisoft\Metashape Pro\scripts`). Appears under the **Helpers**
  menu on next GUI launch.
