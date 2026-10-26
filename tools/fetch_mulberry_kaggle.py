"""Fetch the CC0 mulberry disease photos (Kaggle: nahiduzzaman13/mulberry-leaf-dataset; Bangladesh, 1,091 originals:
Disease Free leaves 440 / Leaf Rust 489 / Leaf spot 162) WITHOUT downloading the 11.4 GB archive: HTTP range requests pull each
file from the remote zip and only a downscaled copy (max side 512 px) is stored locally.
  /tmp/conv/venv/bin/python -I tools/fetch_mulberry_kaggle.py /tmp/mt/mulberry_small     (needs `pip install remotezip pillow`)
"""
import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from remotezip import RemoteZip

API = "https://www.kaggle.com/api/v1/datasets/download/nahiduzzaman13/mulberry-leaf-dataset"
CLS = {"Disease Free leaves": "healthy", "Leaf Rust": "leaf_rust", "Leaf spot": "leaf_spot"}


def signed_url() -> str:
    return subprocess.run(["curl", "-s", "-m", "30", "-o", "/dev/null", "-w", "%{redirect_url}", API], capture_output=True, text=True).stdout


def work(args):
    names, out = args
    z = RemoteZip(signed_url())
    done = 0
    for n in names:
        cls = CLS[n.split("/")[1]]
        dst = out / cls / (Path(n).stem + ".jpg")
        if dst.exists():
            continue
        try:
            im = Image.open(io.BytesIO(z.read(n))).convert("RGB")
            im.thumbnail((512, 512), Image.LANCZOS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.save(dst, quality=92)
            done += 1
        except Exception as e:
            print("FAIL", n, str(e)[:80], flush=True)
    return done


def main(out: Path, workers: int = 6):
    z = RemoteZip(signed_url())
    names = [i.filename for i in z.infolist() if not i.is_dir() and i.filename.split("/")[1] in CLS]
    chunks = [names[i::workers * 4] for i in range(workers * 4)]
    total = 0
    with ThreadPoolExecutor(workers) as ex:
        for d in ex.map(work, [(c, out) for c in chunks]):
            total += d
            print("saved", total, "/", len(names), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
