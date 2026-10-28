"""Pobiera zmergowane PR-y (opis, diff, komentarze review) do data/<repo>/raw.jsonl.

    export GITHUB_TOKEN=...            # GitHub Enterprise lub github.com
    python fetch_prs.py configs/my-repo.yaml

Wznawialne: PR-y już zapisane w raw.jsonl są pomijane.
"""
import json
import os
import pathlib
import sys
import time

import requests
import yaml

cfg = yaml.safe_load(open(sys.argv[1]))
API, REPO = cfg["api_url"].rstrip("/"), cfg["repo"]
S = requests.Session()
S.headers["Accept"] = "application/vnd.github+json"
token = os.environ.get(cfg.get("token_env", "GITHUB_TOKEN"))
if token:
    S.headers["Authorization"] = f"Bearer {token}"

out_dir = pathlib.Path("data") / REPO.replace("/", "__")
out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / "raw.jsonl"
done = {json.loads(l)["number"] for l in out.open()} if out.exists() else set()


def get(url, accept=None, **params):
    while True:
        r = S.get(url, headers={"Accept": accept} if accept else {}, params=params, timeout=60)
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            wait = int(r.headers.get("X-RateLimit-Reset", time.time() + 60)) - time.time()
            print(f"rate limit, czekam {int(wait)}s")
            time.sleep(max(wait, 5))
            continue
        r.raise_for_status()
        return r


def pulls():
    page = 1
    while True:
        batch = get(f"{API}/repos/{REPO}/pulls", state="closed", per_page=100,
                    page=page, sort="created", direction="desc").json()
        if not batch:
            return
        yield from batch
        page += 1


count = 0
with out.open("a") as f:
    for pr in pulls():
        if not pr.get("merged_at") or pr["number"] in done:
            continue
        n = pr["number"]
        diff = get(f"{API}/repos/{REPO}/pulls/{n}", accept="application/vnd.github.v3.diff").text
        reviews = get(f"{API}/repos/{REPO}/pulls/{n}/comments", per_page=100).json()
        rec = {"number": n, "title": pr["title"], "body": pr.get("body") or "", "diff": diff,
               "merged_at": pr["merged_at"],
               "review_comments": [{"path": c["path"], "body": c["body"]} for c in reviews]}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        count += 1
        print(f"#{n} {pr['title'][:70]}")
        if cfg.get("max_prs") and count >= cfg["max_prs"]:
            break
print(f"Zapisano {count} nowych PR-ów -> {out}")
