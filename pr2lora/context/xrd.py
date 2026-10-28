"""Strategia 6 (Crossplane): tylko potrzebny schemat XRD + walidacja.

Model dostaje schemat jednego XRD zamiast repo, a błędy z `crossplane beta validate`
wracają do niego jako poprawka.

    python -m context.xrd /repo XNetwork            # wypisz XRD i jego schemat
"""
import pathlib
import subprocess
import sys
import tempfile

import yaml

from .repo_map import YAML_EXT, iter_files


def all_xrds(root):
    for p in iter_files(root):
        if p.suffix not in YAML_EXT:
            continue
        try:
            docs = list(yaml.safe_load_all(p.read_text(errors="ignore")))
        except Exception:
            continue
        for doc in docs:
            if isinstance(doc, dict) and doc.get("kind") == "CompositeResourceDefinition":
                yield p, doc


def find_xrd(root, kind):
    for p, doc in all_xrds(root):
        names = doc["spec"].get("names", {})
        claim = doc["spec"].get("claimNames", {})
        if kind in (names.get("kind"), claim.get("kind")):
            return p, doc
    raise KeyError(f"brak XRD dla {kind}")


def schema_text(doc):
    vers = doc["spec"]["versions"]
    v = next((v for v in vers if v.get("referenceable")), vers[0])
    return yaml.safe_dump(v["schema"]["openAPIV3Schema"], sort_keys=False)


def strip_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def generate_with_validation(root, kind, task, retries=3):
    from .llm import llm

    xrd_path, xrd = find_xrd(root, kind)
    msgs = [{"role": "user", "content": f"Schemat XRD {kind}:\n{schema_text(xrd)}\n\n"
                                        f"Zadanie: {task}\nZwróć sam YAML."}]
    for _ in range(retries):
        out = strip_fences(llm(msgs))
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(out)
        r = subprocess.run(["crossplane", "beta", "validate", str(xrd_path), f.name],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return out
        msgs += [{"role": "assistant", "content": out},
                 {"role": "user", "content": f"Walidacja nie przeszła:\n{r.stdout}{r.stderr}\nPopraw."}]
    raise RuntimeError("Nie udało się wygenerować poprawnego YAML-a")


if __name__ == "__main__":
    path, doc = find_xrd(sys.argv[1], sys.argv[2])
    print(f"# {path}\n{schema_text(doc)}")
