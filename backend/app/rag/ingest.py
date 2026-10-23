"""Ingest the sericulture knowledge base into ChromaDB.

    python -m app.rag.ingest [--reset]      # reads data/kb/**/*.{md,txt,pdf}
Folder name becomes the `topic` metadata (mulberry, silkworm, rearing, reeling, storage, policy).
"""
import hashlib
import re
import sys
from pathlib import Path

from app.config import DATA_DIR
from app.rag.store import collection, reset_collection

KB_DIR = DATA_DIR / "kb"
CHUNK_CHARS, OVERLAP = 900, 150


def read_doc(path: Path) -> tuple[dict, str]:
    meta = {"title": path.stem.replace("_", " ").title(), "source": path.name}
    if path.suffix == ".pdf":
        from pypdf import PdfReader
        return meta, "\n\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k = "origin" if k.strip() == "source" else k.strip()  # `source` always stays the file name
                meta[k] = v.strip()
        text = text[m.end():]
    return meta, text


GENERIC = {"symptoms", "management", "control", "prevention", "treatment", "cause", "causes", "source of infection", "sources of infection",
           "spread of the disease", "early stage of infection", "later stage of infection", "physical", "chemical", "biological",
           "egg stage", "larval stage", "moth stage", "mode of spread", "damage", "life cycle", "description", "nature of damage"}


def chunk(text: str) -> list[str]:
    """Split on headings, then pack to ~CHUNK_CHARS with overlap. Scraped documents flatten heading levels
    ('Grasserie' and its 'Symptoms' are both '##'), so generic sub-headings inherit the parent disease/pest
    heading and any 'Diseases and pests of ...' group heading: 'Symptoms' alone would be unsearchable."""
    sections, ctx, buf = [], "", []
    group = parent = ""
    for line in text.splitlines():
        if line.startswith("#"):
            if buf:
                sections.append((ctx, "\n".join(buf).strip()))
            h = line.lstrip("# ").strip().rstrip(":")
            if h.lower().startswith("diseases and pests of"):
                group, parent = h, ""
                ctx = h
            elif h.lower() in GENERIC and parent:
                ctx = " > ".join(x for x in (group, parent, h) if x)
            else:
                parent = h
                ctx = " > ".join(x for x in (group, h) if x and x != h) + (" > " if group and group != h else "") + h if group else h
            buf = []
        elif not line.startswith(">"):  # skip placeholder banner
            buf.append(line)
    if buf:
        sections.append((ctx, "\n".join(buf).strip()))
    out = []
    for h, body in sections:
        if not body:
            continue
        start = 0
        while start < len(body):
            piece = body[start:start + CHUNK_CHARS].strip()
            out.append(f"{h}: {piece}" if h else piece)
            if start + CHUNK_CHARS >= len(body):
                break
            start += CHUNK_CHARS - OVERLAP
    return out


def ingest(reset: bool = False, kb_dir: Path = KB_DIR) -> int:
    col = reset_collection("knowledge") if reset else collection("knowledge")
    n = 0
    for path in sorted(kb_dir.rglob("*")):
        if path.suffix.lower() not in {".md", ".txt", ".pdf"} or path.name.startswith("."):
            continue
        meta, text = read_doc(path)
        topic = path.parent.name if path.parent != kb_dir else "general"
        chunks = chunk(text)
        if not chunks:
            continue
        ids = [hashlib.md5(f"{path}:{i}:{c}".encode()).hexdigest() for i, c in enumerate(chunks)]
        col.upsert(ids=ids, documents=chunks, metadatas=[
            {"title": meta["title"], "source": meta["source"], "origin": meta.get("origin", ""), "publisher": meta.get("publisher", ""),
             "topic": topic, "chunk": i}
            for i in range(len(chunks))])
        n += len(chunks)
    return n


if __name__ == "__main__":
    print("Ingested chunks:", ingest(reset="--reset" in sys.argv))
