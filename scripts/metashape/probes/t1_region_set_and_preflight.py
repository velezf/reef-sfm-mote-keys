#!/usr/bin/env python3
"""t1_region_set_and_preflight.py — Set tight region on EDR_T1 + pre-flight gate.

Phases (all in one Metashape invocation):
  1. DERIVE    Camera centres + MAD-trimmed sparse → AABB in levelled world
               frame; +0.75 m margin; world/level-axis-aligned rotation.
  2. WRITE     Open RW; assert not read_only; set region; save; verify mtime.
  3. VERIFY    Reopen read-only; confirm region persisted within tolerance.
  4. PREFLIGHT bounds (long 5–18 m, short 3–14 m, up < 5 m);
               all 2348 cameras inside; ≥99 % trimmed sparse inside;
               GPU / params / guardrail / disk.

Exits 0 on PASS, 1 on FAIL. All actual values printed verbatim.

Usage:
    metashape.sh -platform offscreen -r probes/t1_region_set_and_preflight.py <project.psx>
"""
from __future__ import annotations

import gc
import math
import subprocess
import sys
from pathlib import Path

import Metashape

HERE      = Path(__file__).resolve().parent          # …/scripts/metashape/probes
REPO_ROOT = HERE.parent.parent.parent                # …/reef-sfm-mote-keys
RUN_PIPELINE = REPO_ROOT / "scripts" / "metashape" / "run_pipeline.py"
SPOT_CTRL    = REPO_ROOT / "scripts" / "spot" / "spot_controller.sh"

MARGIN_M    = 0.75    # metres added to each side
MAD_K       = 3.5     # keep sparse within k*MAD of per-axis median
SPARSE_PASS = 0.99    # fraction of trimmed sparse that must be inside region

LONG_LO,  LONG_HI  = 5.0,  18.0
SHORT_LO, SHORT_HI = 3.0,  14.0
UP_HI               = 5.0
CAM_BASELINE        = 2348
DISK_MOUNT          = "/data"
DISK_MIN_GB         = 100


def _mat_scale(m) -> float:
    return math.sqrt(m[0, 0] ** 2 + m[1, 0] ** 2 + m[2, 0] ** 2)


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _mad(vals: list[float], med: float | None = None) -> float:
    if med is None:
        med = _median(vals)
    return _median([abs(v - med) for v in vals])


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _sec(title: str) -> None:
    print(f"\n{'='*62}")
    print(f"  {title}")
    print(f"{'='*62}")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — DERIVE REGION  (read-only open; document closed on function exit)
# ─────────────────────────────────────────────────────────────────────────────
def _derive_region(psx: str) -> dict:
    _sec("PHASE 1 — DERIVE REGION")
    doc = Metashape.Document()
    doc.open(psx, read_only=True)
    chunk = doc.chunks[0]
    print(f"  chunk           : {chunk.label}")
    T     = chunk.transform.matrix
    T_inv = T.inv()
    scale = _mat_scale(T)
    print(f"  transform scale : {scale:.6f} m/internal_unit")

    # ── camera centres in world coords ──────────────────────────────────────
    cam_wx: list[float] = []
    cam_wy: list[float] = []
    cam_wz: list[float] = []
    n_aligned = 0
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        n_aligned += 1
        # cam.transform is camera→chunk; mulp([0,0,0]) = camera centre in chunk coords
        p_int = cam.transform.mulp(Metashape.Vector([0.0, 0.0, 0.0]))
        p_w   = T.mulp(p_int)
        cam_wx.append(p_w.x); cam_wy.append(p_w.y); cam_wz.append(p_w.z)
    print(f"  aligned cameras : {n_aligned}")

    # ── sparse tie points in world coords ───────────────────────────────────
    raw_wx: list[float] = []
    raw_wy: list[float] = []
    raw_wz: list[float] = []
    tp = chunk.tie_points
    if tp is not None and tp.points:
        for pt in tp.points:
            try:
                if not pt.valid:
                    continue
                c = pt.coord
                # coord may be homogeneous (4-vector) or 3-vector
                if hasattr(c, 'w') and c.w != 0:
                    p_int = Metashape.Vector([c.x / c.w, c.y / c.w, c.z / c.w])
                elif hasattr(c, 'w'):
                    continue
                else:
                    p_int = Metashape.Vector([c.x, c.y, c.z])
                p_w = T.mulp(p_int)
                raw_wx.append(p_w.x); raw_wy.append(p_w.y); raw_wz.append(p_w.z)
            except Exception:
                continue
    print(f"  raw sparse pts  : {len(raw_wx):,}")

    # ── MAD trim per axis ────────────────────────────────────────────────────
    tsp_wx: list[float] = []
    tsp_wy: list[float] = []
    tsp_wz: list[float] = []
    if raw_wx:
        med_x, med_y, med_z = _median(raw_wx), _median(raw_wy), _median(raw_wz)
        mad_x = max(_mad(raw_wx, med_x), 1e-6)
        mad_y = max(_mad(raw_wy, med_y), 1e-6)
        mad_z = max(_mad(raw_wz, med_z), 1e-6)
        lo_x = med_x - MAD_K * mad_x;  hi_x = med_x + MAD_K * mad_x
        lo_y = med_y - MAD_K * mad_y;  hi_y = med_y + MAD_K * mad_y
        lo_z = med_z - MAD_K * mad_z;  hi_z = med_z + MAD_K * mad_z
        for x, y, z in zip(raw_wx, raw_wy, raw_wz):
            if lo_x <= x <= hi_x and lo_y <= y <= hi_y and lo_z <= z <= hi_z:
                tsp_wx.append(x); tsp_wy.append(y); tsp_wz.append(z)
        kept_pct = 100 * len(tsp_wx) / max(1, len(raw_wx))
        print(f"  MAD k={MAD_K}: kept {len(tsp_wx):,}/{len(raw_wx):,} ({kept_pct:.1f}%)")
        print(f"    X window (m): [{lo_x:.3f}, {hi_x:.3f}]")
        print(f"    Y window (m): [{lo_y:.3f}, {hi_y:.3f}]")
        print(f"    Z window (m): [{lo_z:.3f}, {hi_z:.3f}]")
    else:
        print("  WARNING: no valid sparse tie points — region derived from cameras only")

    # ── combined AABB in world frame ─────────────────────────────────────────
    all_x = cam_wx + tsp_wx
    all_y = cam_wy + tsp_wy
    all_z = cam_wz + tsp_wz
    if not all_x:
        raise RuntimeError("No camera centres or sparse points — cannot derive region")
    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)
    zmin, zmax = min(all_z), max(all_z)
    cx_w = (xmin + xmax) / 2
    cy_w = (ymin + ymax) / 2
    cz_w = (zmin + zmax) / 2
    xe = xmax - xmin
    ye = ymax - ymin
    ze = zmax - zmin
    print(f"\n  AABB (world, metres) — cameras + trimmed sparse:")
    print(f"    X: [{xmin:.3f}, {xmax:.3f}]  extent={xe:.3f} m")
    print(f"    Y: [{ymin:.3f}, {ymax:.3f}]  extent={ye:.3f} m")
    print(f"    Z: [{zmin:.3f}, {zmax:.3f}]  extent={ze:.3f} m")
    print(f"  centre (world)  : ({cx_w:.4f}, {cy_w:.4f}, {cz_w:.4f})")

    xe_m = xe + 2 * MARGIN_M
    ye_m = ye + 2 * MARGIN_M
    ze_m = ze + 2 * MARGIN_M
    print(f"\n  with +{MARGIN_M} m margin each side:")
    print(f"    X: {xe_m:.3f} m  Y: {ye_m:.3f} m  Z: {ze_m:.3f} m")

    # ── world-axis-aligned rotation (= level-frame-aligned after stage_level) ─
    # T maps internal→world; T_inv.mulv(world_dir) → internal direction (scaled).
    # Normalize to get unit direction in internal coords.
    def _w2i_dir(dx: float, dy: float, dz: float) -> list[float]:
        v = T_inv.mulv(Metashape.Vector([dx, dy, dz]))
        n = math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2)
        return [v.x / n, v.y / n, v.z / n]

    wx_i = _w2i_dir(1.0, 0.0, 0.0)   # world X in internal
    wy_i = _w2i_dir(0.0, 1.0, 0.0)   # world Y in internal
    wz_i = _w2i_dir(0.0, 0.0, 1.0)   # world Z in internal

    # region.rot: each column = one region axis expressed in internal coords
    rot = Metashape.Matrix([
        [wx_i[0], wy_i[0], wz_i[0]],
        [wx_i[1], wy_i[1], wz_i[1]],
        [wx_i[2], wy_i[2], wz_i[2]],
    ])

    # ── convert centre + size to internal units ───────────────────────────────
    centre_int = T_inv.mulp(Metashape.Vector([cx_w, cy_w, cz_w]))
    sx_i = xe_m / scale
    sy_i = ye_m / scale
    sz_i = ze_m / scale

    print(f"\n  Region (internal coords):")
    print(f"    centre : ({centre_int.x:.5f}, {centre_int.y:.5f}, {centre_int.z:.5f})")
    print(f"    size   : ({sx_i:.5f}, {sy_i:.5f}, {sz_i:.5f})")
    print(f"    → metres: ({sx_i*scale:.3f}, {sy_i*scale:.3f}, {sz_i*scale:.3f})")

    del doc
    gc.collect()
    print("  [Phase 1 done — doc closed, RW open safe]")

    return {
        "centre_int"          : centre_int,
        "size_int"            : Metashape.Vector([sx_i, sy_i, sz_i]),
        "rot"                 : rot,
        "scale"               : scale,
        "cam_world"           : (cam_wx, cam_wy, cam_wz),
        "sparse_trimmed_world": (tsp_wx, tsp_wy, tsp_wz),
        "n_aligned"           : n_aligned,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — WRITE REGION  (read-write open)
# ─────────────────────────────────────────────────────────────────────────────
def _write_region(psx: str, params: dict) -> None:
    _sec("PHASE 2 — WRITE REGION")
    doc = Metashape.Document()
    doc.open(psx)
    if doc.read_only:
        raise RuntimeError(f"Document opened read-only (lock present?): {psx}")
    print("  read_only       : False  [PASS]")
    chunk = doc.chunks[0]

    ci = params["centre_int"]
    si = params["size_int"]
    chunk.region.center = ci
    chunk.region.size   = si
    chunk.region.rot    = params["rot"]
    print(f"  region.center   : ({ci.x:.5f}, {ci.y:.5f}, {ci.z:.5f})")
    print(f"  region.size     : ({si.x:.5f}, {si.y:.5f}, {si.z:.5f})")

    psx_path    = Path(psx)
    mtime_pre   = psx_path.stat().st_mtime
    doc.save()
    mtime_post  = psx_path.stat().st_mtime
    if mtime_post <= mtime_pre:
        raise RuntimeError(
            f"Save did not advance mtime: pre={mtime_pre:.0f} post={mtime_post:.0f}")
    print(f"  save mtime      : {mtime_pre:.0f} → {mtime_post:.0f}  [PASS]")

    del doc
    gc.collect()
    print("  [Phase 2 done — doc closed]")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — VERIFY  (read-only reopen)
# ─────────────────────────────────────────────────────────────────────────────
def _verify_region(psx: str, params: dict) -> None:
    _sec("PHASE 3 — VERIFY REGION PERSISTED")
    doc = Metashape.Document()
    doc.open(psx, read_only=True)
    chunk  = doc.chunks[0]
    scale  = params["scale"]
    tol    = 1e-5
    ci_exp = params["centre_int"]
    si_exp = params["size_int"]
    ci_rb  = chunk.region.center
    si_rb  = chunk.region.size

    c_ok = (abs(ci_rb.x - ci_exp.x) < tol
            and abs(ci_rb.y - ci_exp.y) < tol
            and abs(ci_rb.z - ci_exp.z) < tol)
    s_ok = (abs(si_rb.x - si_exp.x) < tol
            and abs(si_rb.y - si_exp.y) < tol
            and abs(si_rb.z - si_exp.z) < tol)

    print(f"  centre expected : ({ci_exp.x:.5f}, {ci_exp.y:.5f}, {ci_exp.z:.5f})")
    print(f"  centre read-back: ({ci_rb.x:.5f}, {ci_rb.y:.5f}, {ci_rb.z:.5f})")
    print(f"  centre match    : {'[PASS]' if c_ok else '[FAIL]'}")
    print(f"  size (m) r/b    : ({si_rb.x*scale:.3f}, {si_rb.y*scale:.3f}, {si_rb.z*scale:.3f})")
    print(f"  size match      : {'[PASS]' if s_ok else '[FAIL]'}")

    del doc
    gc.collect()

    if not (c_ok and s_ok):
        raise RuntimeError("VERIFY FAIL: region did not persist correctly after save")
    print("  [Phase 3 done — verify PASS]")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — PRE-FLIGHT  (read-only reopen)
# ─────────────────────────────────────────────────────────────────────────────
def _preflight(psx: str, params: dict) -> list[str]:
    _sec("PHASE 4 — RE-PRE-FLIGHT")
    doc = Metashape.Document()
    doc.open(psx, read_only=True)
    chunk = doc.chunks[0]
    T     = chunk.transform.matrix
    scale = _mat_scale(T)
    T_inv = T.inv()
    failures: list[str] = []

    # ── REGION BOUNDS ─────────────────────────────────────────────────────────
    print("\n  [REGION BOUNDS]")
    reg  = chunk.region
    Rm   = reg.rot
    sx_m = reg.size.x * scale
    sy_m = reg.size.y * scale
    sz_m = reg.size.z * scale
    sizes_m = sorted([sx_m, sy_m, sz_m])
    up_m, short_m, long_m = sizes_m[0], sizes_m[1], sizes_m[2]
    print(f"  region size (m) : x={sx_m:.3f}  y={sy_m:.3f}  z={sz_m:.3f}")
    print(f"  long axis       : {long_m:.3f} m  (expect {LONG_LO}–{LONG_HI} m)")
    print(f"  short axis      : {short_m:.3f} m  (expect {SHORT_LO}–{SHORT_HI} m)")
    print(f"  up axis         : {up_m:.3f} m  (expect <{UP_HI} m)")
    for ok, pass_msg, fail_msg in [
        (LONG_LO  <= long_m  <= LONG_HI,
         f"long={long_m:.3f} m in [{LONG_LO},{LONG_HI}]",
         f"REGION long={long_m:.3f} m outside [{LONG_LO},{LONG_HI}] m"),
        (SHORT_LO <= short_m <= SHORT_HI,
         f"short={short_m:.3f} m in [{SHORT_LO},{SHORT_HI}]",
         f"REGION short={short_m:.3f} m outside [{SHORT_LO},{SHORT_HI}] m"),
        (up_m < UP_HI,
         f"up={up_m:.3f} m < {UP_HI}",
         f"REGION up={up_m:.3f} m >= {UP_HI} m"),
    ]:
        if ok:
            print(f"  [PASS] {pass_msg}")
        else:
            print(f"  [FAIL] {fail_msg}")
            failures.append(fail_msg)

    # ── CAMERA COVERAGE ───────────────────────────────────────────────────────
    print("\n  [CAMERA COVERAGE — all 2348 aligned cameras inside region]")
    hx, hy, hz = reg.size.x / 2, reg.size.y / 2, reg.size.z / 2
    n_cams = n_cams_out = 0
    outside_labels: list[str] = []
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        n_cams += 1
        p_int = cam.transform.mulp(Metashape.Vector([0.0, 0.0, 0.0]))
        rel   = p_int - reg.center
        lx    = Rm[0,0]*rel.x + Rm[1,0]*rel.y + Rm[2,0]*rel.z
        ly    = Rm[0,1]*rel.x + Rm[1,1]*rel.y + Rm[2,1]*rel.z
        lz    = Rm[0,2]*rel.x + Rm[1,2]*rel.y + Rm[2,2]*rel.z
        if abs(lx) > hx or abs(ly) > hy or abs(lz) > hz:
            n_cams_out += 1
            if len(outside_labels) < 5:
                outside_labels.append(cam.label)
    print(f"  aligned cameras : {n_cams}  (baseline {CAM_BASELINE})")
    print(f"  cameras outside : {n_cams_out}")
    if n_cams < CAM_BASELINE:
        msg = f"CAMERAS: {n_cams} aligned < baseline {CAM_BASELINE}"
        failures.append(msg); print(f"  [FAIL] {msg}")
    elif n_cams_out > 0:
        msg = f"CAMERAS: {n_cams_out}/{n_cams} outside region (sample: {outside_labels})"
        failures.append(msg); print(f"  [FAIL] {msg}")
    else:
        print(f"  [PASS] all {n_cams} cameras inside region")

    # ── SPARSE COVERAGE ───────────────────────────────────────────────────────
    print("\n  [SPARSE COVERAGE — ≥99% of trimmed sparse inside region]")
    tsp_wx, tsp_wy, tsp_wz = params["sparse_trimmed_world"]
    n_tsp = len(tsp_wx)
    n_tsp_out = 0
    for wx, wy, wz in zip(tsp_wx, tsp_wy, tsp_wz):
        p_int = T_inv.mulp(Metashape.Vector([wx, wy, wz]))
        rel   = p_int - reg.center
        lx    = Rm[0,0]*rel.x + Rm[1,0]*rel.y + Rm[2,0]*rel.z
        ly    = Rm[0,1]*rel.x + Rm[1,1]*rel.y + Rm[2,1]*rel.z
        lz    = Rm[0,2]*rel.x + Rm[1,2]*rel.y + Rm[2,2]*rel.z
        if abs(lx) > hx or abs(ly) > hy or abs(lz) > hz:
            n_tsp_out += 1
    frac_in = (n_tsp - n_tsp_out) / max(1, n_tsp)
    print(f"  trimmed sparse  : {n_tsp:,}  outside: {n_tsp_out}  "
          f"fraction_in: {frac_in:.4f} ({frac_in*100:.1f}%)")
    if n_tsp == 0:
        print("  [WARN] no trimmed sparse points (not a failure)")
    elif frac_in < SPARSE_PASS:
        msg = f"SPARSE: {frac_in:.3f} inside < {SPARSE_PASS} required"
        failures.append(msg); print(f"  [FAIL] {msg}")
    else:
        print(f"  [PASS] {frac_in*100:.1f}% of trimmed sparse inside")

    del doc
    gc.collect()

    # ── GPU ───────────────────────────────────────────────────────────────────
    print("\n  [GPU — L4 + gpu_mask]")
    rc, smi = _run(["nvidia-smi", "-L"])
    for line in (smi.splitlines() or ["(no output)"]):
        print(f"    {line}")
    if rc == 0 and "L4" in smi:
        print("  [PASS] L4 enumerated by nvidia-smi")
    else:
        msg = f"GPU: L4 not in nvidia-smi (rc={rc})"
        failures.append(msg); print(f"  [FAIL] {msg}")
    gm = Metashape.app.gpu_mask
    print(f"  gpu_mask        : {gm}  (0x{gm:08X})")
    if gm > 0:
        print(f"  [PASS] gpu_mask={gm} enables GPU(s)")
    else:
        msg = "GPU: gpu_mask=0 (no GPU enabled)"
        failures.append(msg); print(f"  [FAIL] {msg}")

    # ── DENSE PARAMS ─────────────────────────────────────────────────────────
    print("\n  [DENSE PARAMS — Quality=High, Filtering=Mild]")
    try:
        src = RUN_PIPELINE.read_text()
        q_ok = 'dense_quality: str = "High"' in src
        d_ok = 'depth_filtering: str = "Mild"' in src
        print(f"  dense_quality   : {'High ✓' if q_ok else 'NOT FOUND'}")
        print(f"  depth_filtering : {'Mild ✓' if d_ok else 'NOT FOUND'}")
        if q_ok and d_ok:
            print("  [PASS] Quality=High, Filtering=Mild (ESM Table S2 step 12, ADR-0010)")
        else:
            for ok, name in [(q_ok, "dense_quality=High"), (d_ok, "depth_filtering=Mild")]:
                if not ok:
                    msg = f"PARAMS: {name} not default in run_pipeline.py"
                    failures.append(msg); print(f"  [FAIL] {msg}")
    except Exception as exc:
        msg = f"PARAMS: cannot read {RUN_PIPELINE}: {exc}"
        failures.append(msg); print(f"  [FAIL] {msg}")

    # ── CONTROLLER GUARDRAIL + POST-DENSE HALT ────────────────────────────────
    print("\n  [CONTROLLER GUARDRAIL — ALLOW_DENSE + post-dense halt]")
    try:
        ctrl_src = SPOT_CTRL.read_text()
        has_allow   = "ALLOW_DENSE" in ctrl_src
        has_event   = "dense_guardrail_halt" in ctrl_src
        has_stopbef = "--stop-before" in ctrl_src      # arg supported
        print(f"  ALLOW_DENSE var : {'found' if has_allow else 'MISSING'}")
        print(f"  guardrail event : {'found' if has_event else 'MISSING'}")
        print(f"  --stop-before   : {'supported' if has_stopbef else 'MISSING'}")
        if has_allow and has_event and has_stopbef:
            print("  [PASS] ALLOW_DENSE guard + --stop-before halt confirmed")
        else:
            msg = "GUARDRAIL: dense guard incomplete in spot_controller.sh"
            failures.append(msg); print(f"  [FAIL] {msg}")
    except Exception as exc:
        msg = f"GUARDRAIL: cannot read {SPOT_CTRL}: {exc}"
        failures.append(msg); print(f"  [FAIL] {msg}")

    # ── DISK ──────────────────────────────────────────────────────────────────
    print(f"\n  [DISK — ≥{DISK_MIN_GB} GB free on {DISK_MOUNT}]")
    _, df_h = _run(["df", "-h", DISK_MOUNT])
    for line in df_h.splitlines():
        print(f"    {line}")
    _, df_bg = _run(["df", "-BG", "--output=avail", DISK_MOUNT])
    free_gb = 0
    for line in df_bg.splitlines():
        s = line.strip().rstrip("G")
        if s.isdigit():
            free_gb = int(s)
    print(f"  free (GB)       : {free_gb}")
    if free_gb >= DISK_MIN_GB:
        print(f"  [PASS] {free_gb} GB free >= {DISK_MIN_GB} GB")
    else:
        msg = f"DISK: {free_gb} GB < {DISK_MIN_GB} GB"
        failures.append(msg); print(f"  [FAIL] {msg}")

    return failures


# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: t1_region_set_and_preflight.py <project.psx>")
        sys.exit(1)
    psx = sys.argv[1]

    print("=== T1 REGION SET + PRE-FLIGHT ===")
    print(f"project : {psx}")

    try:
        params = _derive_region(psx)
        _write_region(psx, params)
        _verify_region(psx, params)
        failures = _preflight(psx, params)
    except Exception as exc:
        print(f"\nFATAL: {exc}")
        sys.exit(1)

    print(f"\n{'='*62}")
    if failures:
        print(f"RESULT: FAILED  ({len(failures)} check(s))")
        for f in failures:
            print(f"  FAIL: {f}")
        print("DO NOT launch dense. Fix all failures first.")
        sys.exit(1)
    else:
        print("RESULT: PASS — region set + verified + all pre-flight checks clear.")
        print("Safe to launch dense.")
        sys.exit(0)


if __name__ == "__main__":
    main()
