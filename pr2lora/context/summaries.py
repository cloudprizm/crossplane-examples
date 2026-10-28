"""Strategia 5: streszczenia modułów (katalogów).

Generowane raz, np. w CI po merge'u; cache po hashu treści w .context/summaries.json.
Do promptu trafia kilka zdań na katalog zamiast kodu.

    LLM_URL=... python -m context.summaries /repo
"""
import hashlib
import json
import pathlib
import sys

from .llm import llm
from .repo_map import CODE_EXT, SKIP_DIRS, YAML_EXT

EXT = YAML_EXT | CODE_EXT


def directories(root):
    root = pathlib.Path(root)
    for d in sorted([root] + [p for p in root.rglob("*") if p.is_dir()]):
        if set(d.relative_to(root).parts) & SKIP_DIRS:
            continue
        files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix in EXT)
        if files:
            yield d, files


def summarize_repo(root, out=None):
    root = pathlib.Path(root)
    out = pathlib.Path(out or root / ".context" / "summaries.json")
    cache = json.loads(out.read_text()) if out.exists() else {}
    for d, files in directories(root):
        key = str(d.relative_to(root)) or "."
        body = "\n\n".join(f"# {f.name}\n{f.read_text(errors='ignore')[:3000]}" for f in files)[:12000]
        h = hashlib.sha1(body.encode()).hexdigest()
        if cache.get(key, {}).get("hash") == h:
            continue  # bez zmian -> nie liczymy ponownie
        s = llm([{"role": "user", "content": "Opisz w 3-5 zdaniach: co robi ten katalog, jakie zasoby/XRD "
                                              f"definiuje i jakich wzorców używa.\n\n{body}"}])
        cache[key] = {"hash": h, "summary": s}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    return cache


def as_context(cache):
    return "\n".join(f"{k}: {v['summary']}" for k, v in sorted(cache.items()))


if __name__ == "__main__":
    print(as_context(summarize_repo(sys.argv[1])))
