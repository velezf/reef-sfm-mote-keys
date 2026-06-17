"""Reproduce Alignment Helper Zero-pitch on the edr_r2_q030_zeropitch work copy.

Step 11 equivalent (feat/zero-pitch-frame):
  - Open WORK copy (never touch foil edr_r2.psx / edr_r2_q030.psx)
  - Identify the two endpoint markers spanning the ~10 m transect (most separated
    pair, most parallel to raster X axis)
  - Apply Zero pitch: chunk.transform.rotation *= euler2mat([yaw, pitch, 0])
    where yaw/pitch are from the WORLD-SPACE midline vector
  - Save .psx
  - Rebuild DSM from existing filtered dense cloud (no re-dense)
  - Export DSM TIF

Usage (headless, EC2):
  metashape.sh -platform offscreen -r scripts/metashape/apply_zero_pitch.py
"""

import math
import sys
import time
from pathlib import Path

import Metashape  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Paths — operator sets these; never point to the foil
# ---------------------------------------------------------------------------
WORK_PSX   = Path("/data/edr_work/edr_r2_q030_zeropitch_20260617.psx")
FOIL_PSX   = Path("/data/edr_work/edr_r2_q030.psx")   # NEVER OPEN THIS
FOIL_Q050  = Path("/data/edr_work/edr_r2.psx")         # NEVER OPEN THIS
OUT_DSM    = Path("/data/edr_work/edr_r2_q030_zeropitch_dsm_20260617.tif")

_LOCAL_CS_WKT = (
    'LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],'
    'UNIT["metre",1]]'
)

# ---------------------------------------------------------------------------
# Foil guard
# ---------------------------------------------------------------------------
for foil in (FOIL_PSX, FOIL_Q050):
    if WORK_PSX.resolve() == foil.resolve():
        sys.exit(f"ABORT: WORK_PSX resolves to foil {foil} — refusing to open.")


def log(msg: str) -> None:
    print(f"[apply_zero_pitch] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Open WORK copy
# ---------------------------------------------------------------------------
log(f"Opening WORK copy: {WORK_PSX}")
doc = Metashape.Document()
doc.open(str(WORK_PSX), read_only=False)
if doc.read_only:
    sys.exit("ABORT: document opened read-only (stale lock?). Refusing to proceed.")

chunk = doc.chunk
if chunk is None:
    sys.exit("ABORT: no active chunk in the document.")

log(f"Chunk: '{chunk.label}'  cameras: {len(chunk.cameras)}  markers: {len(chunk.markers)}")

# ---------------------------------------------------------------------------
# Print ALL markers + world positions
# ---------------------------------------------------------------------------
M = chunk.transform.matrix
log("=== ALL MARKERS ===")
marker_world: dict[str, Metashape.Vector] = {}
for mk in chunk.markers:
    if mk.position is not None:
        wp = M.mulp(mk.position)
        marker_world[mk.label] = wp
        log(f"  {mk.label:16s}  local=({mk.position.x:.4f}, {mk.position.y:.4f}, {mk.position.z:.4f})"
            f"  world=({wp.x:.4f}, {wp.y:.4f}, {wp.z:.4f})")
    else:
        log(f"  {mk.label:16s}  NO POSITION")

if len(marker_world) < 2:
    sys.exit("ABORT: fewer than 2 markers have positions — cannot determine midline.")

# ---------------------------------------------------------------------------
# Pick the midline pair: most separated, most parallel to X
# ---------------------------------------------------------------------------
labels = list(marker_world.keys())
best = {"pair": None, "dist": 0.0, "angle_to_x": 90.0}

log("\n=== CANDIDATE PAIRS ===")
for i in range(len(labels)):
    for j in range(i + 1, len(labels)):
        la, lb = labels[i], labels[j]
        pa, pb = marker_world[la], marker_world[lb]
        dx, dy, dz = pb.x - pa.x, pb.y - pa.y, pb.z - pa.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        angle_to_x = math.degrees(math.atan2(abs(dy), abs(dx)))  # angle from X in XY plane
        log(f"  {la} <-> {lb}  dist={dist:.3f} m  angle_to_X={angle_to_x:.2f} deg")
        # Criterion: separation > 9 m (full transect, not mid-point pairs)
        # AND smallest angle to raster X axis (most parallel to along-transect direction)
        if dist > 9.0 and angle_to_x < best["angle_to_x"]:
            best = {"pair": (la, lb), "dist": dist, "angle_to_x": angle_to_x}

if best["pair"] is None:
    sys.exit("ABORT: no marker pair with separation > 9 m found. Cannot define midline.")

la, lb = best["pair"]
log(f"\nPICKED midline: {la} <-> {lb}")
log(f"  dist={best['dist']:.4f} m  angle_to_X={best['angle_to_x']:.4f} deg")
log("  JUSTIFICATION: separation >9m (full transect, not mid-pair), smallest angle to raster X.")
log("  Cross-check: separation should be ~10 m (full transect length); angle <5 deg expected.")

m1_local = next(mk.position for mk in chunk.markers if mk.label == la)
m2_local = next(mk.position for mk in chunk.markers if mk.label == lb)

# ---------------------------------------------------------------------------
# Compute Zero-pitch rotation (refineButtonClicked, pitchCheckBox=True)
# ---------------------------------------------------------------------------
diff = M.mulp(m1_local) - M.mulp(m2_local)
# Original Alignment Helper uses math.atan (ratio, not atan2) so the angle is
# the same regardless of which end of the midline is m1 vs m2 (sign of diff[0]
# cancels in the ratio when diff[0] < 0 and diff[2] < 0 → positive pitch).
yaw   = math.degrees(math.atan(diff[1] / diff[0]))
pitch = math.degrees(math.atan(diff[2] / diff[0]))
log(f"\n=== ZERO PITCH ROTATION ===")
log(f"  world-space diff: ({diff[0]:.4f}, {diff[1]:.4f}, {diff[2]:.4f})")
log(f"  yaw={yaw:.4f} deg  pitch={pitch:.4f} deg  (atan-ratio convention, not atan2)")
log(f"  along-midline pitch before: {pitch:.4f} deg  (target: ~0)")

E = Metashape.Utils.euler2mat([yaw, pitch, 0])
chunk.transform.rotation = chunk.transform.rotation * E
log("  chunk.transform.rotation updated (right-multiplied by euler2mat([yaw, pitch, 0]))")

# Verify: recompute diff in new frame
M2 = chunk.transform.matrix
diff2 = M2.mulp(m1_local) - M2.mulp(m2_local)
pitch2 = math.degrees(math.atan(diff2[2] / diff2[0]))
yaw2   = math.degrees(math.atan(diff2[1] / diff2[0]))
log(f"  POST-ROTATION midline: yaw={yaw2:.4f} deg  pitch={pitch2:.4f} deg")
if abs(pitch2) > 0.30:
    sys.exit(f"ABORT (before save): post-rotation pitch {pitch2:.4f} deg > 0.30 deg. "
             "Wrong marker pair or rotation sign. WORK copy NOT saved.")
log(f"  OK: post-rotation pitch {abs(pitch2):.4f} deg < 0.30 deg threshold.")

# ---------------------------------------------------------------------------
# Save .psx — only reached if verification passed
# ---------------------------------------------------------------------------
log(f"\nSaving {WORK_PSX} ...")
doc.save()
import os
mtime = os.stat(WORK_PSX).st_mtime
log(f"  Saved OK  mtime={mtime}")

# ---------------------------------------------------------------------------
# Build DSM from existing filtered dense cloud — no re-dense
# ---------------------------------------------------------------------------
if chunk.point_cloud is None:
    sys.exit("ABORT: no filtered dense point cloud in chunk. Cannot build DSM.")

pc = chunk.point_cloud
log(f"\n=== BUILD DSM ===")
log(f"  Point cloud: {pc.point_count:,} pts (filtered; reused from q030 — no re-dense)")

# LOCAL_CS projection (ADR-0020 recipe)
chunk.crs = Metashape.CoordinateSystem(_LOCAL_CS_WKT)
top_xy = Metashape.Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
origin = chunk.transform.matrix.mulp(Metashape.Vector([0, 0, 0]))
lf = chunk.crs.localframe(origin)
proj = Metashape.OrthoProjection()
proj.crs = chunk.crs
proj.type = Metashape.OrthoProjection.Type.Planar
proj.matrix = (Metashape.Matrix.Rotation(top_xy)
               * Metashape.Matrix.Rotation(lf.rotation()))

# Pre-flight: predicted cell count (tripwire from ADR-0018/0020)
R_reg = chunk.region
T_tr  = chunk.transform
s = T_tr.scale or 1.0
res = 0.01
pcols = (R_reg.size.x * s) / res
prows = (R_reg.size.y * s) / res
log(f"  Predicted DEM: {pcols:.0f} x {prows:.0f} cells ({pcols * prows:.3e})")
TRIPWIRE = 2_000_000
if pcols * prows > TRIPWIRE:
    sys.exit(f"ABORT: predicted cell count {pcols * prows:.3e} > {TRIPWIRE:,} (OOM tripwire). "
             "Projection not local-planar — check chunk.crs.")

t0 = time.time()
chunk.buildDem(
    source_data=Metashape.PointCloudData,
    interpolation=Metashape.EnabledInterpolation,
    projection=proj,
    resolution=res,
)
elapsed = time.time() - t0
dem = chunk.elevation
log(f"  buildDem done in {elapsed:.1f} s  dims: {dem.width} x {dem.height}")

# ---------------------------------------------------------------------------
# Export DSM TIF
# ---------------------------------------------------------------------------
log(f"\nExporting DSM -> {OUT_DSM}")
chunk.exportRaster(
    str(OUT_DSM),
    source_data=Metashape.ElevationData,
    resolution=res,
    image_format=Metashape.ImageFormat.ImageFormatTIFF,
    save_alpha=False,
)
log(f"  Exported  size: {OUT_DSM.stat().st_size / 1024:.1f} KB")

# Final save
doc.save()
log("  Final save OK")
log("\nDone. Transfer DSM from EC2:")
log(f"  rsync reef-ec2:{OUT_DSM} products/EDR_T1_R2/edr_t1_r2_q030_zeropitch_dsm.tif")
