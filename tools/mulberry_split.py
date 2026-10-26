"""Leak-safe split of the mulberry disease photos fetched by tools/fetch_mulberry_kaggle.py.
Photos are unique originals (no augmented copies) but burst shots of the same leaf exist, so near-duplicates (64-bit dHash,
Hamming <= 8) are merged into groups before the stratified 70/15/15 split over groups.
  /tmp/conv/venv/bin/python -I tools/mulberry_split.py /tmp/mt/mulberry_small
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def dhash(p):
    a = np.asarray(Image.open(p).convert("L").resize((9, 8), Image.LANCZOS), dtype=np.int16)
    return int("".join("1" if b else "0" for b in (a[:, 1:] > a[:, :-1]).flatten()), 2)


def main(src: Path, seed=14):
    files = sorted(p for p in src.rglob("*.jpg"))
    names = [f"{p.parent.name}/{p.name}" for p in files]
    cls = {n: n.split("/")[0] for n in names}
    h = {n: dhash(p) for n, p in zip(names, files)}
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    merged = conflicts = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if bin(h[names[i]] ^ h[names[j]]).count("1") <= 8 and find(names[i]) != find(names[j]):
                conflicts += cls[names[i]] != cls[names[j]]
                parent[find(names[i])] = find(names[j]); merged += 1
    groups = defaultdict(list)
    for n in names:
        groups[find(n)].append(n)
    rng = np.random.default_rng(seed)
    out = {}
    for c in ("healthy", "leaf_rust", "leaf_spot"):
        gs = [g for g, ms in groups.items() if Counter(cls[m] for m in ms).most_common(1)[0][0] == c]
        rng.shuffle(gs)
        n = len(gs); a, b = int(0.7 * n), int(0.85 * n)
        for k, g in enumerate(gs):
            for m in groups[g]:
                out[m] = {"class": c, "group": g, "split": "train" if k < a else "val" if k < b else "test", "path": m}
    (ROOT / "data/eval/mulberry_split.json").write_text(json.dumps({"seed": seed, "n_files": len(names), "n_groups": len(groups), "near_dup_merges": merged, "cross_class_near_dups": int(conflicts), "files": out}))
    c = Counter((v["split"], v["class"]) for v in out.values())
    print(f"{len(names)} files -> {len(groups)} groups; near-duplicate merges {merged}; cross-class conflicts {conflicts}")
    for s in ("train", "val", "test"):
        print(s, {k: c[(s, k)] for k in ("healthy", "leaf_rust", "leaf_spot")})


if __name__ == "__main__":
    main(Path(sys.argv[1]))
