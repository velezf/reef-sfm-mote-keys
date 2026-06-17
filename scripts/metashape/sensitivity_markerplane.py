"""Sensitivity measurement: marker-plane leveling on T1_R2 (TRANSIENT).

Applies the same marker-PLANE leveling used by stage_level (ADR-0021) to the
T1_R2 WORK COPY (reset to master rotation = chunk.zip 43547ec5), builds a DSM
from the existing filtered cloud, exports, then RESTORES the chunk.zip from the
master in a finally block so the work copy is left in its original state.

NEVER opens or modifies:
  - edr_r2.psx (foil Q050)
  - edr_r2_q030.psx (master source)

TRANSIENT workflow:
  1. Pre-flight: verify work copy chunk.zip sha == 43547ec5 (master rotation)
  2. Open work copy (read/write)
  3. Verify pre-level along-pitch ~4.11 deg (sanity guard)
  4. Fit marker plane; report spread_ratio (collinear guard value)
  5. Apply LEFT-multiply world rotation (same as _apply_world_rotation in pipeline)
  6. buildDem from existing filtered cloud; export to OUT_DSM
  7. FINALLY: restore work copy chunk.zip from master (file copy, not Metashape save)
  8. Post-flight: verify master chunk.zip sha == 43547ec5 + open master read_only,
     print pitch to confirm master is clean

Usage (EC2, headless):
  /usr/local/bin/metashape -platform offscreen -r sensitivity_markerplane.py
"""

import math
import shutil
import sys
from pathlib import Path

import Metashape  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MASTER_PSX     = Path("/data/edr_work/edr_r2_q030.psx")
MASTER_CHUNK   = Path("/data/edr_work/edr_r2_q030.files/0/chunk.zip")
FOIL_PSX       = Path("/data/edr_work/edr_r2.psx")          # NEVER OPEN
WORK_PSX       = Path("/data/edr_work/edr_r2_q030_zeropitch_20260617.psx")
WORK_CHUNK     = Path("/data/edr_work/edr_r2_q030_zeropitch_20260617.files/0/chunk.zip")
OUT_DSM        = Path("/data/edr_work/edr_r2_q030_markerplane_dsm_20260617.tif")

MASTER_CHUNK_EXPECTED_SHA = "43547ec5a7cc06da47e2204ebd1381f630f949037aeab53f799885aa9fc019c6"
COLLINEAR_THRESHOLD = 0.25   # from run_pipeline.py LEVEL_COLLINEAR_THRESHOLD

_LOCAL_CS_WKT = (
    'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],'
    'UNIT["metre",1]]'
)


def log(msg: str) -> None:
    print(f"[mkplane] {msg}", flush=True)


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Pure-python plane-fit + Rodrigues — copied from run_pipeline.py (no numpy)
# ---------------------------------------------------------------------------

def _jacobi_eig_sym3(A):
    a = [row[:] for row in A]
    V = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(100):
        p, q = 0, 1
        if abs(a[0][2]) > abs(a[p][q]):
            p, q = 0, 2
        if abs(a[1][2]) > abs(a[p][q]):
            p, q = 1, 2
        if abs(a[p][q]) < 1e-18:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        phi = (0.5 * math.atan2(2 * apq, aqq - app)
               if (aqq - app) != 0 else math.pi / 4)
        c, s = math.cos(phi), math.sin(phi)
        for k in range(3):
            akp, akq = a[k][p], a[k][q]
            a[k][p] = c * akp - s * akq
            a[k][q] = s * akp + c * akq
        for k in range(3):
            apk, aqk = a[p][k], a[q][k]
            a[p][k] = c * apk - s * aqk
            a[q][k] = s * apk + c * aqk
        for k in range(3):
            vkp, vkq = V[k][p], V[k][q]
            V[k][p] = c * vkp - s * vkq
            V[k][q] = s * vkp + c * vkq
    eig = [a[i][i] for i in range(3)]
    vecs = [[V[r][c] for r in range(3)] for c in range(3)]
    return eig, vecs


def _fit_plane_normal(points):
    n = len(points)
    cen = [sum(p[i] for p in points) / n for i in range(3)]
    C = [[0.0] * 3 for _ in range(3)]
    for p in points:
        d = [p[i] - cen[i] for i in range(3)]
        for i in range(3):
            for j in range(3):
                C[i][j] += d[i] * d[j]
    eig, vecs = _jacobi_eig_sym3(C)
    k = min(range(3), key=lambda i: eig[i])
    nrm = vecs[k]
    L = math.sqrt(sum(x * x for x in nrm)) or 1.0
    nrm = [x / L for x in nrm]
    if nrm[2] < 0:
        nrm = [-x for x in nrm]
    return nrm, cen, sorted(eig, reverse=True)


def _rot_normal_to_z(n):
    z = [0.0, 0.0, 1.0]
    axis = [n[1]*z[2]-n[2]*z[1], n[2]*z[0]-n[0]*z[2], n[0]*z[1]-n[1]*z[0]]
    s = math.sqrt(sum(a*a for a in axis))
    c = sum(n[i]*z[i] for i in range(3))
    if s < 1e-15:
        return (Metashape.Matrix.Diag([1, 1, 1]) if c > 0
                else Metashape.Matrix([[1, 0, 0], [0, -1, 0], [0, 0, -1]]))
    ux, uy, uz = (a / s for a in axis)
    ang = math.atan2(s, c)
    C, S, t = math.cos(ang), math.sin(ang), 1 - math.cos(ang)
    return Metashape.Matrix([
        [C+ux*ux*t,    ux*uy*t-uz*S, ux*uz*t+uy*S],
        [uy*ux*t+uz*S, C+uy*uy*t,    uy*uz*t-ux*S],
        [uz*ux*t-uy*S, uz*uy*t+ux*S, C+uz*uz*t]])


def _apply_world_rotation(chunk, R):
    R4 = Metashape.Matrix([
        [R[i, j] if (i < 3 and j < 3) else (1.0 if i == j else 0.0)
         for j in range(4)] for i in range(4)])
    chunk.transform.matrix = R4 * chunk.transform.matrix


def _along_pitch(M, m26_pos, m16_pos):
    diff = M.mulp(m26_pos) - M.mulp(m16_pos)
    return math.degrees(math.atan(diff[2] / diff[0]))


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

log("=== PRE-FLIGHT ===")
log(f"Verifying work copy chunk.zip sha == {MASTER_CHUNK_EXPECTED_SHA[:8]}...")
work_sha = _sha256(WORK_CHUNK)
master_sha_pf = _sha256(MASTER_CHUNK)
log(f"  MASTER chunk.zip sha: {master_sha_pf[:16]}...")
log(f"  WORK   chunk.zip sha: {work_sha[:16]}...")
if work_sha != MASTER_CHUNK_EXPECTED_SHA:
    sys.exit(f"ABORT: work copy chunk.zip sha {work_sha[:8]} != expected "
             f"{MASTER_CHUNK_EXPECTED_SHA[:8]}. Reset first.")
if master_sha_pf != MASTER_CHUNK_EXPECTED_SHA:
    sys.exit(f"ABORT: master chunk.zip sha {master_sha_pf[:8]} != expected "
             f"{MASTER_CHUNK_EXPECTED_SHA[:8]}. Master was modified!")
log("  Both shas match — master rotation confirmed in work copy.")

# ---------------------------------------------------------------------------
# Open WORK copy
# ---------------------------------------------------------------------------
log(f"\nOpening WORK copy: {WORK_PSX}")
doc = Metashape.Document()
doc.open(str(WORK_PSX), read_only=False)
if doc.read_only:
    sys.exit("ABORT: document opened read-only (stale lock?). Refusing to proceed.")
chunk = doc.chunk

# Locate midline markers for pre/post pitch check
mk26 = next((m for m in chunk.markers if m.label == "Marker 26"), None)
mk16 = next((m for m in chunk.markers if m.label == "Marker 16"), None)
if mk26 is None or mk16 is None or mk26.position is None or mk16.position is None:
    sys.exit("ABORT: midline markers Marker 26 / Marker 16 not found or have no position.")

M0 = chunk.transform.matrix
pre_pitch = _along_pitch(M0, mk26.position, mk16.position)
log(f"Pre-level along-pitch (Marker 26->16): {pre_pitch:.4f} deg  (expected ~4.11)")
if abs(pre_pitch) < 1.0:
    sys.exit(f"ABORT: pre-pitch {pre_pitch:.4f} deg is near 0 — work copy may have been "
             "left in a zero-pitched state. Restore chunk.zip from master first.")

# ---------------------------------------------------------------------------
# Collect marker world positions
# ---------------------------------------------------------------------------
log("\n=== MARKER WORLD POSITIONS ===")
pts = []
valid_labels = []
for mk in chunk.markers:
    if mk.position is None:
        log(f"  {mk.label}: NO POSITION — skipped")
        continue
    wp = M0.mulp(mk.position)
    pts.append([wp.x, wp.y, wp.z])
    valid_labels.append(mk.label)
    log(f"  {mk.label:16s}  ({wp.x:+.4f}, {wp.y:+.4f}, {wp.z:+.4f})")

if len(pts) < 3:
    sys.exit(f"ABORT: need ≥3 marker positions for plane fit, got {len(pts)}")

# ---------------------------------------------------------------------------
# Plane fit + collinearity report
# ---------------------------------------------------------------------------
log("\n=== PLANE FIT ===")
normal, centroid, eig_sorted = _fit_plane_normal(pts)
spread_ratio = eig_sorted[1] / eig_sorted[0] if eig_sorted[0] > 0 else 0.0
tilt_deg = math.degrees(math.acos(max(-1.0, min(1.0, abs(normal[2])))))

log(f"  Plane normal (world): ({normal[0]:+.6f}, {normal[1]:+.6f}, {normal[2]:+.6f})")
log(f"  Centroid:             ({centroid[0]:+.4f}, {centroid[1]:+.4f}, {centroid[2]:+.4f})")
log(f"  Scatter eigenvalues (sorted desc): {[round(e,4) for e in eig_sorted]}")
log(f"  Spread ratio (eig[1]/eig[0]):  {spread_ratio:.5f}  (threshold {COLLINEAR_THRESHOLD})")
log(f"  Collinear guard {'FIRES' if spread_ratio < COLLINEAR_THRESHOLD else 'does NOT fire'} "
    f"-> pipeline would use {'camera-nadir' if spread_ratio < COLLINEAR_THRESHOLD else 'marker-plane'}")
log(f"  Marker-plane tilt from horizontal: {tilt_deg:.4f} deg")
log(f"  Markers used ({len(pts)}): {valid_labels}")

# ---------------------------------------------------------------------------
# Apply marker-plane rotation (transient — RESTORE in finally)
# ---------------------------------------------------------------------------
original_chunk_zip_backup = WORK_CHUNK.parent / "chunk.zip.bak"
shutil.copy2(WORK_CHUNK, original_chunk_zip_backup)
log(f"\n  Backed up chunk.zip to {original_chunk_zip_backup.name}")

try:
    log("\n=== APPLY MARKER-PLANE ROTATION ===")
    R = _rot_normal_to_z(normal)
    _apply_world_rotation(chunk, R)

    M_new = chunk.transform.matrix
    post_pitch = _along_pitch(M_new, mk26.position, mk16.position)
    log(f"  Post-level along-pitch (Marker 26->16): {post_pitch:.4f} deg  (expected ~0)")

    # Cross-axis: world Y direction (perpendicular to transect)
    # Use a synthetic cross-axis vector perpendicular to the midline
    diff_mid = M_new.mulp(mk26.position) - M_new.mulp(mk16.position)
    # cross_y = dip in Y direction (use centroid marker as cross reference)
    # Approximate cross-axis: mean Y extent across pairs
    mk_ys = [pts[i][1] for i in range(len(pts))]
    mid_y = sum(mk_ys) / len(mk_ys)
    # Use plane normal in new frame as a check
    new_normal_w = [
        R[0,0]*normal[0]+R[0,1]*normal[1]+R[0,2]*normal[2],
        R[1,0]*normal[0]+R[1,1]*normal[1]+R[1,2]*normal[2],
        R[2,0]*normal[0]+R[2,1]*normal[1]+R[2,2]*normal[2],
    ]
    log(f"  World diff Marker 26->16 in new frame: "
        f"({diff_mid[0]:+.4f}, {diff_mid[1]:+.4f}, {diff_mid[2]:+.4f})")

    doc.save()
    log("  Saved work copy with marker-plane rotation")

    # -----------------------------------------------------------------------
    # buildDem from existing filtered dense cloud
    # -----------------------------------------------------------------------
    if chunk.point_cloud is None:
        sys.exit("ABORT: no filtered dense cloud in work copy. Cannot build DSM.")

    log(f"\n=== BUILD DSM ===  ({chunk.point_cloud.point_count:,} pts)")
    chunk.crs = Metashape.CoordinateSystem(_LOCAL_CS_WKT)
    top_xy = Metashape.Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    origin = chunk.transform.matrix.mulp(Metashape.Vector([0, 0, 0]))
    lf = chunk.crs.localframe(origin)
    proj = Metashape.OrthoProjection()
    proj.crs = chunk.crs
    proj.type = Metashape.OrthoProjection.Type.Planar
    proj.matrix = (Metashape.Matrix.Rotation(top_xy)
                   * Metashape.Matrix.Rotation(lf.rotation()))

    R_reg = chunk.region
    T_tr  = chunk.transform
    s = T_tr.scale or 1.0
    res = 0.01
    pcols = (R_reg.size.x * s) / res
    prows = (R_reg.size.y * s) / res
    log(f"  Predicted DEM: {pcols:.0f} x {prows:.0f} cells")
    if pcols * prows > 2_000_000:
        sys.exit(f"ABORT: OOM tripwire {pcols*prows:.3e} cells.")

    import time
    t0 = time.time()
    chunk.buildDem(
        source_data=Metashape.PointCloudData,
        interpolation=Metashape.EnabledInterpolation,
        projection=proj,
        resolution=res,
    )
    log(f"  buildDem done in {time.time()-t0:.1f} s  dims: {chunk.elevation.width} x {chunk.elevation.height}")

    log(f"\nExporting -> {OUT_DSM}")
    chunk.exportRaster(
        str(OUT_DSM),
        source_data=Metashape.ElevationData,
        resolution=res,
        image_format=Metashape.ImageFormat.ImageFormatTIFF,
        save_alpha=False,
    )
    log(f"  Exported {OUT_DSM.stat().st_size/1024:.1f} KB")

finally:
    # -----------------------------------------------------------------------
    # RESTORE: file-copy chunk.zip from master — no Metashape save needed
    # -----------------------------------------------------------------------
    log("\n=== FINALLY: RESTORE chunk.zip from master ===")
    shutil.copy2(MASTER_CHUNK, WORK_CHUNK)
    restored_sha = _sha256(WORK_CHUNK)
    log(f"  Restored sha: {restored_sha[:16]}...")
    if restored_sha == MASTER_CHUNK_EXPECTED_SHA:
        log("  RESTORE OK — work copy chunk.zip == master sha (43547ec5)")
    else:
        log(f"  WARNING: restored sha {restored_sha[:8]} != expected {MASTER_CHUNK_EXPECTED_SHA[:8]}")
    # clean up backup
    if original_chunk_zip_backup.exists():
        original_chunk_zip_backup.unlink()

# ---------------------------------------------------------------------------
# Post-flight: verify master is untouched
# ---------------------------------------------------------------------------
log("\n=== POST-FLIGHT: MASTER INTEGRITY VERIFY ===")
final_master_sha = _sha256(MASTER_CHUNK)
log(f"  Master chunk.zip sha: {final_master_sha[:16]}...")
if final_master_sha == MASTER_CHUNK_EXPECTED_SHA:
    log("  MASTER CLEAN — sha 43547ec5 unchanged throughout.")
else:
    log(f"  ALARM — master sha changed to {final_master_sha[:8]}! Investigate immediately.")

log("\nOpening master read_only for pitch verification...")
doc2 = Metashape.Document()
doc2.open(str(MASTER_PSX), read_only=True)
chunk2 = doc2.chunk
M2 = chunk2.transform.matrix
mk26b = next((m for m in chunk2.markers if m.label == "Marker 26"), None)
mk16b = next((m for m in chunk2.markers if m.label == "Marker 16"), None)
if mk26b and mk16b and mk26b.position and mk16b.position:
    master_pitch = _along_pitch(M2, mk26b.position, mk16b.position)
    log(f"  Master along-pitch (Marker 26->16): {master_pitch:.4f} deg  (expected ~4.11)")
    if abs(master_pitch) < 1.0:
        log("  ALARM — master pitch near 0, master WAS mutated.")
    else:
        log(f"  MASTER OK — pitch {master_pitch:.4f} deg consistent with pre-zeropitch state.")

import hashlib
out_sha = hashlib.sha256(OUT_DSM.read_bytes()).hexdigest()[:8]
log(f"\nMarker-plane DSM: {OUT_DSM.name}  sha={out_sha}")
log(f"Transfer: rsync reef-ec2:{OUT_DSM} products/EDR_T1_R2/edr_t1_r2_q030_markerplane_dsm.tif")
