"""Mierzy, ile kontekstu oszczędza każda strategia (bez modelu, offline).

    python bench_context.py /sciezka/do/repo-crossplane [--json wynik.json]

Tokeny liczone szacunkowo jako znaki / 4 (dla kodu i YAML-a to przybliżenie;
dokładnie policzysz tokenizerem swojego modelu).
"""
import argparse
import json
import pathlib

from context import signatures as ts
from context.repo_map import CODE_EXT, YAML_EXT, iter_files, repo_map
from context.retrieve import Index
from context.xrd import all_xrds, schema_text

QUERIES = [
    "network subnet definition for gcp",
    "azure sql database composition",
    "account project subscription",
]


def tok(n):
    return round(n / 4)


def pct(part, whole):
    return f"{100 * (1 - part / whole):.0f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--json")
    ap.add_argument("--query", action="append")
    a = ap.parse_args()
    root = pathlib.Path(a.repo)

    files = [p for p in iter_files(root) if p.suffix in YAML_EXT | CODE_EXT]
    full = sum(len(p.read_text(errors="ignore")) for p in files)
    rmap = repo_map(root, max_chars=10**9)
    xrds = [(str(p.relative_to(root)), d["spec"]["names"]["kind"], len(schema_text(d))) for p, d in all_xrds(root)]
    idx = Index(root)
    queries = a.query or QUERIES
    hits = {q: idx.search_items(q, k=4, budget=6000) for q in queries}

    res = {
        "repo": str(root), "files": len(files), "full_chars": full,
        "repo_map_chars": len(rmap), "signatures": "tree-sitter" if ts.available() else "regex",
        "chunks": len(idx.items), "retrieval_backend": idx.backend,
        "xrds": [{"file": f, "kind": k, "schema_chars": n} for f, k, n in xrds],
        "retrieval": {q: {"sources": [s for s, _ in h], "chars": sum(len(t) for _, t in h)} for q, h in hits.items()},
    }

    print(f"## Repo: {root}  ({len(files)} plików YAML/kod)\n")
    print("| Co trafia do kontekstu | Znaki | ~Tokeny | Redukcja vs całe repo |")
    print("| --- | --- | --- | --- |")
    print(f"| Całe repo | {full} | {tok(full)} | – |")
    print(f"| Mapa repo (strategia 1) | {len(rmap)} | {tok(len(rmap))} | {pct(len(rmap), full)} |")
    for q, h in hits.items():
        n = sum(len(t) for _, t in h)
        print(f"| Wyszukiwanie: \"{q}\" (top {len(h)}) | {n} | {tok(n)} | {pct(n, full)} |")
    if xrds:
        avg = sum(n for *_, n in xrds) / len(xrds)
        print(f"| Schemat jednego XRD (średnio z {len(xrds)}) | {avg:.0f} | {tok(avg)} | {pct(avg, full)} |")
    print(f"\nFragmentów do wyszukiwania: {len(idx.items)} (backend: {idx.backend}); "
          f"sygnatury: {res['signatures']}\n")
    print("### Mapa repo\n```text\n" + rmap + "\n```")
    for q, h in hits.items():
        print(f"\nZapytanie \"{q}\" -> " + ", ".join(s for s, _ in h))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
