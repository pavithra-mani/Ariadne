"""Leak-safe train/val/test split of the silkworm image set.

The images are Roboflow exports: each source photo appears 2-3 times as augmented copies
('Grasserie-12-_jpg.rf.<hash>.jpg'). A naive random split puts copies of one photo in train AND test and inflates every metric.
Groups = (class prefix, source number), then merged when two files are near-duplicates (64-bit dHash, Hamming <= 6).
Split is stratified by class over groups. Output: data/eval/silkworm_split.json

  python -I tools/silkworm_split.py
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/images/SILK WORM DATASETS/images"
OUT = ROOT / "data/eval/silkworm_split.json"
RX = re.compile(r"^(Grasserie|Healthy_Worms|Healthy|Infected)-(\d+)-")
CLASS = {"Grasserie": "grasserie", "Healthy": "healthy", "Healthy_Worms": "healthy", "Infected": "infected"}


def dhash(p: Path) -> int:
    a = np.asarray(Image.open(p).convert("L").resize((9, 8), Image.LANCZOS), dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def main(seed: int = 14):
    files = sorted(p for p in SRC.iterdir() if p.suffix.lower() == ".jpg")
    info, parent = {}, {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    by_stem = defaultdict(list)
    for p in files:
        m = RX.match(p.name)
        if not m:
            print("skip", p.name); continue
        info[p.name] = {"class": CLASS[m.group(1)], "stem": f"{m.group(1)}-{m.group(2)}", "hash": dhash(p)}
        parent[p.name] = p.name
        by_stem[info[p.name]["stem"]].append(p.name)
    for names in by_stem.values():
        for n in names[1:]:
            union(names[0], n)
    # near-duplicates across different stems (also across classes: such a pair would be a labelling conflict)
    names = list(info)
    H = np.array([info[n]["hash"] for n in names], dtype=object)
    buckets = defaultdict(list)
    for n in names:
        buckets[info[n]["hash"] >> 48].append(n)   # candidate blocks by top 16 bits; cheap pre-filter
    merged = conflicts = 0
    for b in buckets.values():
        for i in range(len(b)):
            for j in range(i + 1, len(b)):
                if bin(info[b[i]]["hash"] ^ info[b[j]]["hash"]).count("1") <= 6 and find(b[i]) != find(b[j]):
                    if info[b[i]]["class"] != info[b[j]]["class"]:
                        conflicts += 1
                    union(b[i], b[j]); merged += 1
    groups = defaultdict(list)
    for n in names:
        groups[find(n)].append(n)
    rng = np.random.default_rng(seed)
    split = {}
    for cls in ("healthy", "infected", "grasserie"):
        gs = [g for g, ms in groups.items() if Counter(info[m]["class"] for m in ms).most_common(1)[0][0] == cls]
        rng.shuffle(gs)
        n = len(gs)
        cut1, cut2 = int(0.70 * n), int(0.85 * n)
        for k, g in enumerate(gs):
            for m in groups[g]:
                split[m] = "train" if k < cut1 else "val" if k < cut2 else "test"
    out = {n: {"class": info[n]["class"], "group": find(n), "split": split[n]} for n in names}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"seed": seed, "n_files": len(names), "n_groups": len(groups), "near_dup_merges": merged,
                               "cross_class_near_dups": conflicts, "files": out}))
    c = Counter((v["split"], v["class"]) for v in out.values())
    print(f"{len(names)} files -> {len(groups)} groups; near-duplicate merges: {merged} (cross-class conflicts: {conflicts})")
    for s in ("train", "val", "test"):
        print(s, {k: c[(s, k)] for k in ("healthy", "infected", "grasserie")})


if __name__ == "__main__":
    main()
