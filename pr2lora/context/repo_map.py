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
SIG_START = re.compile(r"^(\s*)(async def |def |class |func )", re.M)


def referenceable_version(spec):
    """Wersja XRD, z której Crossplane tworzy zasoby (referenceable), inaczej pierwsza."""
    vers = spec.get("versions") or [{}]
    return next((v for v in vers if v.get("referenceable")), vers[0])


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
            schema = ((referenceable_version(spec).get("schema") or {}).get("openAPIV3Schema") or {})
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


def regex_signatures(path, max_lines=6):
    """Sygnatury bez tree-sittera: od def/class/func do początku ciała.

    Go/TS: do pierwszego `{`; Python: do `:` kończącego linię (adnotacje typów w środku nie ucinają).
    Obsługuje sygnatury na kilka linii. Metody w klasach dostają wcięcie.
    """
    text = path.read_text(errors="ignore")
    out = []
    for m in SIG_START.finditer(text):
        chunk = text[m.start(2):].split("\n", max_lines)[:max_lines]
        sig = []
        for line in chunk:
            if path.suffix == ".py":
                if line.rstrip().endswith(":"):
                    sig.append(line.rstrip()[:-1])
                    break
            elif "{" in line:
                sig.append(line.split("{", 1)[0])
                break
            sig.append(line)
        indent = "  " * (1 + len(m.group(1).expandtabs(4)) // 4)
        out.append(indent + " ".join(" ".join(sig).split()))
    return out


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
