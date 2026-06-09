#!/usr/bin/env python3
"""t1_dense_preflight.py — Pre-flight gate before EDR_T1 dense build.

Asserts and PRINTS actual values for all 5 checks. All must pass.

  CHECK 1  REGION     center/size/rotation; dims in metres (internal × 0.15246
                       isotropic); all aligned cameras inside region; bounds:
                       long 5–15 m, short 3–10 m, up <3 m.
  CHECK 2  GPU        L4 enumerated by nvidia-smi + gpu_mask > 0 in Metashape.
  CHECK 3  PARAMS     dense_quality=High, depth_filtering=Mild (ESM step 12,
                       ADR-0010).
  CHECK 4  GUARDRAIL  ALLOW_DENSE guard confirmed in spot_controller.sh.
  CHECK 5  DISK       df /data free >= 100 GB.

Exits 0 on PASS (all 5 clear), 1 on any FAIL.

Usage:
    metashape.sh -platform offscreen -r probes/t1_dense_preflight.py <project.psx>
"""
from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import Metashape

HERE = Path(__file__).resolve().parent          # …/scripts/metashape/probes
REPO_ROOT = HERE.parent.parent.parent           # …/reef-sfm-mote-keys
RUN_PIPELINE = REPO_ROOT / "scripts" / "metashape" / "run_pipeline.py"
SPOT_CTRL = REPO_ROOT / "scripts" / "spot" / "spot_controller.sh"

# Region bounds (metres)
LONG_LO,  LONG_HI  = 5.0, 15.0
SHORT_LO, SHORT_HI = 3.0, 10.0
UP_HI               = 3.0
CAM_BASELINE        = 2348

DISK_MOUNT  = "/data"
DISK_MIN_GB = 100


def _mat_scale(m) -> float:
    return math.sqrt(m[0, 0] ** 2 + m[1, 0] ** 2 + m[2, 0] ** 2)


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _sep(n: int, title: str) -> None:
    print(f"\n{'='*58}")
    print(f"  CHECK {n}  {title}")
    print(f"{'='*58}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: t1_dense_preflight.py <project.psx>")
        sys.exit(1)
    psx = sys.argv[1]

    print("=== T1 DENSE PRE-FLIGHT ===")
    print(f"project : {psx}")
    print()

    failures: list[str] = []

    # ── CHECK 1: REGION ──────────────────────────────────────────────────────
    _sep(1, "REGION")
    doc = Metashape.Document()
    doc.open(psx, read_only=True)
    chunk = doc.chunks[0]
    print(f"  chunk           : {chunk.label}")

    scale = _mat_scale(chunk.transform.matrix)
    print(f"  transform scale : {scale:.6f} m/internal_unit")

    reg = chunk.region
    sx_m = reg.size.x * scale
    sy_m = reg.size.y * scale
    sz_m = reg.size.z * scale
    cx, cy, cz = reg.center.x, reg.center.y, reg.center.z
    print(f"  region center   : ({cx:.4f}, {cy:.4f}, {cz:.4f})")
    print(f"  region size (m) : x={sx_m:.3f}  y={sy_m:.3f}  z={sz_m:.3f}")

    Rm = reg.rot
    det = (Rm[0,0]*(Rm[1,1]*Rm[2,2]-Rm[1,2]*Rm[2,1])
           - Rm[0,1]*(Rm[1,0]*Rm[2,2]-Rm[1,2]*Rm[2,0])
           + Rm[0,2]*(Rm[1,0]*Rm[2,1]-Rm[1,1]*Rm[2,0]))
    print(f"  rotation det    : {det:.4f}  (valid rotation ≈ ±1.0)")

    sizes_m = sorted([sx_m, sy_m, sz_m])
    up_m, short_m, long_m = sizes_m[0], sizes_m[1], sizes_m[2]
    print(f"  long axis       : {long_m:.3f} m  (expect {LONG_LO}–{LONG_HI} m)")
    print(f"  short axis      : {short_m:.3f} m  (expect {SHORT_LO}–{SHORT_HI} m)")
    print(f"  up axis         : {up_m:.3f} m  (expect < {UP_HI} m)")

    axis_ok = True
    if not (LONG_LO <= long_m <= LONG_HI):
        failures.append(f"REGION: long={long_m:.3f} m outside [{LONG_LO}, {LONG_HI}] m")
        axis_ok = False
    if not (SHORT_LO <= short_m <= SHORT_HI):
        failures.append(f"REGION: short={short_m:.3f} m outside [{SHORT_LO}, {SHORT_HI}] m")
        axis_ok = False
    if up_m >= UP_HI:
        failures.append(f"REGION: up={up_m:.3f} m >= {UP_HI} m limit")
        axis_ok = False

    # Camera inside-region check.
    # reg.rot columns = region axes in chunk coords.
    # To project onto region axes: local = reg.rot^T * (cam_pos - region_center)
    n_checked = n_outside = 0
    outside_labels: list[str] = []
    hx, hy, hz = reg.size.x / 2, reg.size.y / 2, reg.size.z / 2
    for cam in chunk.cameras:
        if cam.transform is None:
            continue
        n_checked += 1
        # cam.transform is camera→chunk; mulp([0,0,0]) = camera centre in chunk coords
        p = cam.transform.mulp(Metashape.Vector([0, 0, 0]))
        rel = p - reg.center
        lx = Rm[0,0]*rel.x + Rm[1,0]*rel.y + Rm[2,0]*rel.z
        ly = Rm[0,1]*rel.x + Rm[1,1]*rel.y + Rm[2,1]*rel.z
        lz = Rm[0,2]*rel.x + Rm[1,2]*rel.y + Rm[2,2]*rel.z
        if abs(lx) > hx or abs(ly) > hy or abs(lz) > hz:
            n_outside += 1
            if len(outside_labels) < 5:
                outside_labels.append(cam.label)

    print(f"  cameras aligned : {n_checked}  (baseline {CAM_BASELINE})")
    print(f"  cameras outside : {n_outside}")

    if n_outside > 0:
        msg = f"REGION: {n_outside}/{n_checked} cameras outside region bbox (sample: {outside_labels})"
        failures.append(msg)
        print(f"  [FAIL] {msg}")
    elif n_checked < CAM_BASELINE:
        msg = f"REGION: {n_checked} aligned cameras < baseline {CAM_BASELINE}"
        failures.append(msg)
        print(f"  [FAIL] {msg}")
    else:
        print(f"  [PASS] all {n_checked} cameras inside region")

    if axis_ok:
        print(f"  [PASS] region axis bounds OK")
    else:
        print(f"  [FAIL] region axis bounds out of spec (see above)")

    # ── CHECK 2: GPU ─────────────────────────────────────────────────────────
    _sep(2, "GPU")
    rc, smi_out = _run(["nvidia-smi", "-L"])
    print("  nvidia-smi -L:")
    for line in smi_out.splitlines() or ["  (no output)"]:
        print(f"    {line}")

    if rc == 0 and "L4" in smi_out:
        print("  [PASS] L4 found in nvidia-smi")
    else:
        msg = f"GPU: L4 not in nvidia-smi -L (rc={rc})"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    gm = Metashape.app.gpu_mask
    print(f"  Metashape gpu_mask : {gm}  (binary: {gm:04b})")
    if gm > 0:
        print(f"  [PASS] gpu_mask={gm} enables GPU")
    else:
        msg = "GPU: gpu_mask=0 (no GPU enabled in Metashape)"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    # ── CHECK 3: DENSE PARAMS ─────────────────────────────────────────────────
    _sep(3, "DENSE PARAMS  (ESM Table S2 step 12, ADR-0010)")
    try:
        src = RUN_PIPELINE.read_text()
        q_ok = 'dense_quality: str = "High"' in src
        d_ok = 'depth_filtering: str = "Mild"' in src
        print(f"  run_pipeline.py : {RUN_PIPELINE}")
        print(f"  dense_quality   : {'High  (default confirmed)' if q_ok else '??? NOT FOUND'}")
        print(f"  depth_filtering : {'Mild  (default confirmed)' if d_ok else '??? NOT FOUND'}")
        if q_ok and d_ok:
            print("  [PASS] Quality=High, Filtering=Mild")
        else:
            for ok, name in [(q_ok, "dense_quality=High"), (d_ok, "depth_filtering=Mild")]:
                if not ok:
                    msg = f"PARAMS: {name} not found as default in run_pipeline.py"
                    failures.append(msg)
                    print(f"  [FAIL] {msg}")
    except Exception as exc:
        msg = f"PARAMS: cannot read {RUN_PIPELINE}: {exc}"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    # ── CHECK 4: GUARDRAIL ────────────────────────────────────────────────────
    _sep(4, "CONTROLLER GUARDRAIL")
    try:
        ctrl_src = SPOT_CTRL.read_text()
        has_var   = "ALLOW_DENSE" in ctrl_src
        has_event = "dense_guardrail_halt" in ctrl_src
        print(f"  spot_controller : {SPOT_CTRL}")
        print(f"  ALLOW_DENSE var : {'found' if has_var else 'MISSING'}")
        print(f"  guardrail event : {'dense_guardrail_halt found' if has_event else 'MISSING'}")
        if has_var and has_event:
            print("  [PASS] dense guardrail armed (ALLOW_DENSE + dense_guardrail_halt event)")
        else:
            msg = "GUARDRAIL: dense guard not confirmed in spot_controller.sh"
            failures.append(msg)
            print(f"  [FAIL] {msg}")
    except Exception as exc:
        msg = f"GUARDRAIL: cannot read {SPOT_CTRL}: {exc}"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    # ── CHECK 5: DISK ─────────────────────────────────────────────────────────
    _sep(5, f"DISK  (>= {DISK_MIN_GB} GB free on {DISK_MOUNT})")
    _, df_h = _run(["df", "-h", DISK_MOUNT])
    print("  df -h /data:")
    for line in df_h.splitlines():
        print(f"    {line}")
    _, df_bg = _run(["df", "-BG", "--output=avail", DISK_MOUNT])
    free_gb = 0
    for line in df_bg.splitlines():
        s = line.strip().rstrip("G")
        if s.isdigit():
            free_gb = int(s)
    print(f"  free (parsed)   : {free_gb} GB")
    if free_gb >= DISK_MIN_GB:
        print(f"  [PASS] {free_gb} GB free >= {DISK_MIN_GB} GB")
    else:
        msg = f"DISK: {free_gb} GB free < {DISK_MIN_GB} GB on {DISK_MOUNT}"
        failures.append(msg)
        print(f"  [FAIL] {msg}")

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    print()
    print("=" * 58)
    if failures:
        print(f"PRE-FLIGHT: FAILED  ({len(failures)} check(s))")
        for f in failures:
            print(f"  FAIL: {f}")
        print("DO NOT launch dense. Fix all failures first.")
        sys.exit(1)
    else:
        print("PRE-FLIGHT: PASS — all 5 checks cleared. Safe to launch dense.")
        sys.exit(0)


if __name__ == "__main__":
    main()
