#!/usr/bin/env python3
"""REAL-CHUNK integration smoke for the vendored 2.x USGS Logan routine (ADR-0023).

Proves the vendored Metashape-2.0.x port actually RUNS on our pinned Metashape 2.3.1
build — i.e. its RU/PA/RE gradual-selection filters execute against a REAL
`chunk.tie_points` cloud with no `AttributeError`/API error. This is the gap the
fake-module unit tests (`test_network_health.py`) cannot cover: they exercise the
guard/wrapper logic, not the real vendored↔2.3.1 API surface. It was a wrong-API
artifact (the mislabeled 1.x v2.0-TAG using `chunk.point_cloud`) that crashed the
first live reduce; this smoke is what would have caught it pre-flight.

Run under metashape.sh on a SCRATCH COPY of a real aligned chunk (never a live psx):

    metashape.sh -platform offscreen -r smoke_logan_real_chunk.py <scratch.psx>

Exits 0 + prints "LOGAN-REAL-CHUNK SMOKE: PASS" on success; non-zero on any error.
Does NOT do a full reduce (loose RE threshold + early_stop) and does NOT save — it
only needs to exercise the API the vendored filters touch. The caller supplies a
throwaway copy and discards it.
"""
import sys
from pathlib import Path

import Metashape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_pipeline as rp  # noqa: E402  (Metashape resolves under metashape.sh)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: smoke_logan_real_chunk.py <scratch.psx>")
        return 2
    psx = sys.argv[1]
    assert "backups/" not in psx, "refusing to run on a backup; pass a scratch copy"

    doc = Metashape.Document()
    doc.open(psx, read_only=False)
    assert not doc.read_only, f"{psx} opened read-only (stale lock?) — abort"
    chunk = doc.chunks[0]

    # Loads the vendored module BY PATH and runs the vendor-time IDENTITY check
    # (must declare Metashape 2.0.x + use tie_points, else it raises here).
    mod, src = rp._vendored_logan_module()
    cam_opt = rp._logan_cam_opt()
    print(f"vendored module: {Path(src).name}")

    tp = chunk.tie_points
    n0 = len(tp.points) if tp is not None else 0
    n_aligned = sum(1 for c in chunk.cameras if c.transform is not None)
    print(f"fixture: {n_aligned} aligned cameras, {n0:,} tie points")
    assert tp is not None and n0 > 0, "fixture has no tie-point cloud — not aligned?"

    def _n():
        t = chunk.tie_points
        return len(t.points) if t is not None else 0

    # Exercise the EXACT vendored 2.x filter API the production wrapper calls. RU/PA
    # run-once; RE with a LOOSE threshold + early_stop so the smoke stays fast (this is
    # an API/runs-on-2.3.1 proof, not a real reduce). Any pre-2.0 `point_cloud` access
    # inside these would raise AttributeError exactly as the mislabeled artifact did.
    before = _n()
    mod.reconstruction_uncertainty(chunk, 30, 0.50, 0.1, cam_opt,
                                   ru_iterate_to_ru_level=False, compute_rmse=True)
    print(f"RU ok: {before:,} -> {_n():,} tie points")

    before = _n()
    mod.projection_accuracy(chunk, 3.5, 0.50, 0.1, cam_opt,
                            pa_iterate_to_pa_level=False, compute_rmse=True)
    print(f"PA ok: {before:,} -> {_n():,} tie points")

    before = _n()
    mod.reprojection_error(chunk, 5.0, 0.10, 0.01, cam_opt, True,
                           final_tie_point_accuracy=5.0, compute_rmse=True,
                           early_stop=True)
    print(f"RE ok: {before:,} -> {_n():,} tie points")

    # Deliberately NO doc.save() — the scratch copy is discarded by the caller.
    print(f"LOGAN-REAL-CHUNK SMOKE: PASS (all three 2.x filters executed on a real "
          f"2.3.1 tie_points cloud; {n0:,} -> {_n():,} tie points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
