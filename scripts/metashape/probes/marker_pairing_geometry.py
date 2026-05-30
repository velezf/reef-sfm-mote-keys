import Metashape, itertools, statistics
doc = Metashape.Document()
doc.open("/data/edr_work/edr_t3.psx", read_only=True)
ch = doc.chunks[0]
ms = list(ch.markers)
print(f"chunk={ch.label}  markers={len(ms)}  (read-only; internal units, pre-scale)\n")

print("MARKERS (label : estimated 3D position):")
recon = []
for m in ms:
    p = m.position
    if p is None:
        print(f"  {m.label:>14s} : None (unreconstructed)")
    else:
        print(f"  {m.label:>14s} : ({p.x:.4f}, {p.y:.4f}, {p.z:.4f})")
        recon.append((m.label, p))

# all pairwise distances
pairs = []
for (la, pa), (lb, pb) in itertools.combinations(recon, 2):
    pairs.append((la, lb, (pa - pb).norm()))
pairs.sort(key=lambda x: x[2])

# nearest neighbor each
nn = {}
for la, pa in recon:
    best, bd = None, None
    for lb, pb in recon:
        if lb == la: continue
        d = (pa - pb).norm()
        if bd is None or d < bd:
            bd, best = d, lb
    nn[la] = (best, bd)

# mutual nearest neighbors
mutual, seen = [], set()
for la, (b, d) in nn.items():
    if b is not None and nn.get(b, (None,))[0] == la and frozenset((la, b)) not in seen:
        mutual.append((la, b, d)); seen.add(frozenset((la, b)))
mutual.sort(key=lambda x: x[2])

print("\nALL PAIRWISE DISTANCES (sorted, internal units):")
for la, lb, d in pairs:
    print(f"  {la} <-> {lb} : {d:.4f}")

if mutual:
    med = statistics.median(d for _,_,d in mutual)
    print(f"\nCANDIDATE WITHIN-BAR PAIRS (mutual nearest neighbors; consistent ~{med:.4f} u = 0.250 m):")
    for la, lb, d in mutual:
        flag = "" if (0.6*med <= d <= 1.4*med) else "  <-- length OUTLIER, verify (may be coincidental, not a bar)"
        print(f"  {la} <-> {lb} : {d:.4f}{flag}")

paired = set()
for la, lb, _ in mutual:
    paired.add(la); paired.add(lb)
orphans = [lbl for lbl, _ in recon if lbl not in paired] + [m.label for m in ms if m.position is None]
print("\nNO CLOSE PARTNER (incomplete bar / false positive — undetected-code disc):")
print("  " + (", ".join(orphans) if orphans else "(none — all markers have a mutual partner)"))
