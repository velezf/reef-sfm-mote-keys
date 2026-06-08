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
import tempfile
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

    tp = chunk.tie_points
    n0 = len(tp.points) if tp is not None else 0
    n_aligned = sum(1 for c in chunk.cameras if c.transform is not None)
    n_unaligned = sum(1 for c in chunk.cameras if c.transform is None)
    print(f"fixture: {n_aligned} aligned + {n_unaligned} unaligned cameras, "
          f"{n0:,} tie points")
    assert tp is not None and n0 > 0, "fixture has no tie-point cloud — not aligned?"

    # Run the EXACT production reduce path: rp._run_logan_reduction drives the real
    # vendored 2.x RU->PA->RE filters with the production cam_opt and compute_rmse=False
    # (the documented Logan mode that avoids compute_RMSE's camera.error-None crash on
    # 2.3.1). It also runs the vendor-time identity check (via _vendored_logan_module)
    # and the 3a per-pass backstop. Any API drift (pre-2.0 accessor, or compute_RMSE
    # via a regressed compute_rmse=True) would raise here. The pre-reduce RMSE is read
    # via our own None-safe _reprojection_rms.
    rms_pre, _ = rp._reprojection_rms(chunk)
    out_root = Path(tempfile.mkdtemp(prefix="logan_smoke_out_"))
    path = rp._run_logan_reduction(chunk, out_root, rp.HealthConfig(),
                                   ignore_sanity=False, logan_module=None)
    rms_post, _ = rp._reprojection_rms(chunk)

    def _n():
        t = chunk.tie_points
        return len(t.points) if t is not None else 0

    # Deliberately NO doc.save() — the scratch copy is discarded by the caller.
    print(f"reduction_path: {path}")
    print(f"reproj RMSE (filter units): {rms_pre} -> {rms_post}")
    print(f"LOGAN-REAL-CHUNK SMOKE: PASS (production _run_logan_reduction ran the 2.x "
          f"RU/PA/RE on a real 2.3.1 tie_points cloud; {n0:,} -> {_n():,} tie points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
