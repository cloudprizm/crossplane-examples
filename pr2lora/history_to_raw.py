"""Alternatywa dla fetch_prs.py: dataset z lokalnej historii gita (bez API GitHuba).

Każdy commit = jeden przykład (wiadomość commita jako opis, diff jako odpowiedź).
Przydatne, gdy repo nie ma PR-ów, nie masz tokenu albo chcesz szybko sprawdzić pipeline.

    python history_to_raw.py configs/my-repo.yaml /sciezka/do/klonu [max_commits]
"""
import json
import pathlib
import subprocess
import sys

import yaml

cfg = yaml.safe_load(open(sys.argv[1]))
repo = sys.argv[2]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0


def git(*a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout


out_dir = pathlib.Path("data") / cfg["repo"].replace("/", "__")
out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / "raw.jsonl"
shas = git("log", "--no-merges", "--format=%H").split()
if limit:
    shas = shas[:limit]
with out.open("w") as f:
    for i, sha in enumerate(shas):
        title, _, body = git("log", "-1", "--format=%s%n%b", sha).partition("\n")
        diff = git("show", "--format=", "--no-color", sha)
        date = git("log", "-1", "--format=%cI", sha).strip()
        f.write(json.dumps({"number": i, "sha": sha, "title": title.strip(), "body": body.strip(),
                            "diff": diff, "merged_at": date, "review_comments": []},
                           ensure_ascii=False) + "\n")
print(f"Zapisano {len(shas)} commitów -> {out}")
