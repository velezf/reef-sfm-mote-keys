"""Read-only check of master edr_r2_q030.psx rotation.

Derives along-midline pitch from Marker 26 to Marker 16 (the confirmed
midline pair from ADR-0036) and prints it.
Expected: ~4.39 deg (pre-zero-pitch, original stage_level state).
If near 0.11 deg: master was mutated — must restore from snapshot.

Usage (headless, EC2 — READ ONLY, no save):
  metashape -platform offscreen -r check_master_rotation.py
"""
import math, sys
import Metashape  # type: ignore[import-untyped]

MASTER_PSX = "/data/edr_work/edr_r2_q030.psx"

doc = Metashape.Document()
doc.open(MASTER_PSX, read_only=True)
if not doc.read_only:
    sys.exit("ABORT: document opened writable — expected read_only. Refusing.")

chunk = doc.chunk
M = chunk.transform.matrix

print(f"chunk: '{chunk.label}'  read_only={doc.read_only}")
print(f"transform.scale = {chunk.transform.scale:.8f}")
print(f"transform.rotation =")
R = chunk.transform.rotation
for i in range(3):
    print(f"  [{R[i,0]:.8f}  {R[i,1]:.8f}  {R[i,2]:.8f}]")

# Locate midline markers
mk26 = next((m for m in chunk.markers if m.label == "Marker 26"), None)
mk16 = next((m for m in chunk.markers if m.label == "Marker 16"), None)
if mk26 is None or mk16 is None:
    sys.exit(f"ABORT: midline markers not found (got labels: {[m.label for m in chunk.markers]})")

if mk26.position is None or mk16.position is None:
    sys.exit("ABORT: midline markers have no position")

diff = M.mulp(mk26.position) - M.mulp(mk16.position)
pitch = math.degrees(math.atan(diff[2] / diff[0]))
yaw   = math.degrees(math.atan(diff[1] / diff[0]))
dist  = math.sqrt(diff[0]**2 + diff[1]**2 + diff[2]**2)

print(f"\nMarker 26 -> 16  world diff: ({diff[0]:.4f}, {diff[1]:.4f}, {diff[2]:.4f})")
print(f"  dist  = {dist:.4f} m")
print(f"  yaw   = {yaw:.4f} deg")
print(f"  pitch = {pitch:.4f} deg  <-- along-midline dip")
print()
if abs(pitch) < 0.30:
    print("STATUS: ALARM — pitch ~0 deg means master was MUTATED by zero-pitch rotation.")
    print("        Restore edr_r2_q030.files/0/chunk.zip from EBS snapshot snap-0b10abc94d12b78e1.")
elif 3.5 < abs(pitch) < 5.5:
    print(f"STATUS: CLEAN — pitch {pitch:.4f} deg is consistent with original stage_level state (~4.39 deg).")
else:
    print(f"STATUS: UNEXPECTED — pitch {pitch:.4f} deg is outside both expected ranges. Investigate.")
