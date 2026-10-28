"""Filtruje PR-y, opcjonalnie przepisuje słabe opisy i zapisuje train/valid.jsonl dla mlx-lm.

    python build_dataset.py configs/my-repo.yaml
"""
import json
import os
import pathlib
import random
import re
import sys

import requests
import yaml

cfg = yaml.safe_load(open(sys.argv[1]))
d = pathlib.Path("data") / cfg["repo"].replace("/", "__")
rw = cfg.get("rewriter") or {}
SYSTEM = (f"Jesteś ekspertem od Kubernetes i Crossplane w repozytorium {cfg['repo']}. "
          "Piszesz kod zgodny z wzorcami tego repozytorium.")


def filter_diff(diff):
    """Zostawia tylko pliki pasujące do paths_include."""
    parts = re.split(r"(?=^diff --git )", diff, flags=re.M)
    return "".join(p for p in parts if p.startswith("diff --git") and
                   any(s in p.splitlines()[0] for s in cfg["paths_include"]))


def rewrite(title, body, diff):
    prompt = ("Na podstawie tytułu i diffu napisz zwięzłe polecenie dla programisty, opisujące CO ma "
              "zostać zrobione (nie jak). Tylko polecenie.\n\n"
              f"Tytuł: {title}\nOpis: {body}\nDiff:\n{diff[:12000]}")
    r = requests.post(f"{rw['base_url']}/chat/completions", timeout=300,
                      headers={"Authorization": f"Bearer {os.environ.get(rw.get('api_key_env', ''), 'x')}"},
                      json={"model": rw["model"], "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.2})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


examples, skipped = [], {"brak plików": 0, "za duży": 0, "revert": 0}
for line in (d / "raw.jsonl").open():
    pr = json.loads(line)
    diff = filter_diff(pr["diff"])
    if not diff:
        skipped["brak plików"] += 1
        continue
    if len(diff) > cfg["max_diff_chars"]:
        skipped["za duży"] += 1
        continue
    if re.match(r"(?i)^revert", pr["title"]):
        skipped["revert"] += 1
        continue
    instr = f"{pr['title']}\n\n{pr['body']}".strip()
    if len(pr["body"]) < cfg["min_desc_chars"] and rw.get("enabled"):
        instr = rewrite(pr["title"], pr["body"], diff)
    if pr["review_comments"]:
        notes = "\n".join(f"- {c['path']}: {c['body']}" for c in pr["review_comments"][:10])
        instr += f"\n\nUwagi z review, które należy uwzględnić:\n{notes}"
    examples.append({"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": instr},
        {"role": "assistant", "content": f"```diff\n{diff}\n```"}]})

random.seed(42)
random.shuffle(examples)
k = max(1, int(len(examples) * cfg["valid_ratio"])) if examples else 0
for name, rows in [("valid", examples[:k]), ("train", examples[k:])]:
    with (d / f"{name}.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"train={len(examples) - k} valid={k} pominięte={skipped} -> {d}")
