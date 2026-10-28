"""Strategia 1: mapa repozytorium.

Zamiast całych plików model dostaje strukturę: zasoby Crossplane'a (XRD, Composition,
claimy) i sygnatury funkcji z kodu. Użycie:

    python -m context.repo_map /sciezka/do/repo [max_chars]
"""
import pathlib
import re
import sys

import yaml

from . import signatures as ts

SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "__pycache__", ".context"}
YAML_EXT = {".yaml", ".yml"}
CODE_EXT = {".py", ".go", ".ts"}
SIG = re.compile(r"^\s*(def |class |func )\s*([^{:\n]+)", re.M)


def iter_files(root):
    root = pathlib.Path(root)
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS):
            yield p


def _props(schema, depth=2, prefix=""):
    """Spłaszczone nazwy pól ze schematu OpenAPI (do 2 poziomów)."""
    out = []
    for name, sub in (schema or {}).get("properties", {}).items():
        out.append(prefix + name)
        if depth > 1 and isinstance(sub, dict):
            out += _props(sub, depth - 1, prefix + name + ".")
    return out


def yaml_summary(path):
    out = []
    try:
        docs = list(yaml.safe_load_all(path.read_text(errors="ignore")))
    except Exception:
        return out
    for doc in docs:
        if not isinstance(doc, dict) or "kind" not in doc:
            continue
        kind = doc["kind"]
        name = (doc.get("metadata") or {}).get("name")
        spec = doc.get("spec") or {}
        line = f"  {kind} {name}"
        if kind == "CompositeResourceDefinition":
            names = spec.get("names") or {}
            claim = (spec.get("claimNames") or {}).get("kind")
            vers = spec.get("versions") or [{}]
            schema = ((vers[0].get("schema") or {}).get("openAPIV3Schema") or {})
            fields = _props((schema.get("properties") or {}).get("spec"))
            line += f" xr={names.get('kind')}" + (f" claim={claim}" if claim else "")
            if fields:
                line += f" fields={fields[:12]}"
        elif kind == "Composition":
            ref = spec.get("compositeTypeRef") or {}
            line += f" -> {ref.get('kind')}"
            if spec.get("pipeline"):
                line += " steps=" + str([s.get("step") for s in spec["pipeline"]])
            if spec.get("resources"):
                kinds = [((r.get("base") or {}).get("kind")) for r in spec["resources"]]
                line += f" resources={kinds}"
        elif kind == "Kustomization":
            line += f" resources={doc.get('resources')}"
        out.append(line)
    return out


def regex_signatures(path):
    return [f"  {a.strip()} {b.strip()}" for a, b in SIG.findall(path.read_text(errors="ignore"))]


def repo_map(root, max_chars=8000, use_tree_sitter=None):
    if use_tree_sitter is None:
        use_tree_sitter = ts.available()
    root = pathlib.Path(root)
    lines = []
    for p in iter_files(root):
        if p.suffix in YAML_EXT:
            items = yaml_summary(p)
        elif p.suffix in CODE_EXT:
            items = ts.signatures(p) if use_tree_sitter else regex_signatures(p)
        else:
            continue
        if items:
            lines += [str(p.relative_to(root))] + items
    text = "\n".join(lines)
    if len(text) > max_chars:  # przytnij do budżetu
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n... (przycięto do budżetu)"
    return text


if __name__ == "__main__":
    print(repo_map(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 8000))
