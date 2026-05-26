# 0002 — Pin Metashape Pro to 2.3.1

- **Status:** Accepted
- **Date:** 2026-05-25
- **Chat:** 3 (EC2 bootstrap)

## Context

Agisoft Metashape Professional ships a new Linux build roughly every 3–6
months. As of project start, the current release is 2.3.1 (May 2026).
The Combs et al. 2021 methodology paper was written against Metashape
Pro 1.7.x; Toth et al. 2025 was processed against an unspecified
Metashape Pro 2.x; and the NOAA PIFSC SOP (Torres-Pulliza et al. 2024,
DOI 10.25923/cydj-z260) — used here only as a parameter reference —
documents specific dialog values, sliders, and Gradual Selection
thresholds against Metashape Pro 2.0–2.1.

The parameter values in the PIFSC SOP (Accuracy=High, Key point
limit=40000, Reconstruction uncertainty 10–15, Projection accuracy 2–6,
Reprojection error 0.3–0.5 px, Dense cloud Medium with Mild depth
filtering, DEM at 0.001 m, orthomosaic at 0.0005 m) are tied to a
specific UI generation. Bumping to a future 2.4.x or 3.x release
without re-verifying that the same dialogs, sliders, and parameter
units still exist would invalidate the parameter mapping in Chat 5
silently.

## Decision

Pin Metashape Pro to version 2.3.1 for the entire project. The version
is hardcoded in `02_install_metashape.sh` as `METASHAPE_VERSION=2.3.1`
and the tarball URL is constructed from it.

## Consequences

- If Agisoft retires the 2.3.1 tarball from the download server before
  the project is done, the install script's primary download will 404
  and the operator will need to either find a cached copy or take the
  hit of upgrading and re-verifying parameter values. The mirror URL
  (`s3-eu-west-1.amazonaws.com/download.agisoft.com/...`) tends to
  persist longer than the primary, and the script tries it on
  failure.
- A v2 of this project (multi-site, multi-temporal) might choose to
  bump the pin once. That's a separate decision; this ADR is about
  not bumping it mid-project.
- The Quarto writeup in Chat 8 cites "Metashape Pro 2.3.1" explicitly
  rather than "Metashape Pro 2.x" so the run is reproducible.

## Notebook narrative

> All photogrammetric processing in this project uses Agisoft
> Metashape Professional 2.3.1, pinned for the duration of the run.
> Pinning matters because the parameter reference used here — the
> NOAA PIFSC SOP for SfM coral reef benthic mapping
> (Torres-Pulliza et al. 2024, DOI 10.25923/cydj-z260) — specifies
> Metashape UI values (Gradual Selection thresholds, depth filter
> levels, output resolutions in metres) that are tied to a specific
> Metashape UI generation. Floating the version mid-project would
> mean re-verifying that the same dialogs, sliders, and units still
> exist at each upgrade. The PIFSC SOP is treated here as a parameter
> reference only; the methodological lineage of this work is
> Combs et al. 2021 and Toth et al. 2025 (USGS/Mote), both of which
> processed Florida Keys imagery under broadly equivalent Metashape
> Pro 2.x settings.
