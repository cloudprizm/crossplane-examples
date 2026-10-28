"""Testy skryptów end-to-end: fetch_prs (atrapa API GitHuba), history_to_raw, build_dataset, bench."""
import json
import os
import pathlib
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from conftest import ROOT, QuietHandler, json_response
import stub_llm

PY = sys.executable

DIFF_OK = """diff --git a/package/s3/composition.yaml b/package/s3/composition.yaml
--- a/package/s3/composition.yaml
+++ b/package/s3/composition.yaml
@@ -1 +1,2 @@
 kind: Composition
+  encryption: true
"""
DIFF_DOCS = """diff --git a/docs/notes.md b/docs/notes.md
+hello
"""


def run(script, *args, cwd, env=None):
    e = {**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}
    r = subprocess.run([PY, str(ROOT / script), *map(str, args)], cwd=cwd, env=e,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def write_cfg(tmp_path, **over):
    cfg = {"api_url": "http://unused", "repo": "acme/infra", "token_env": "GH_TEST_TOKEN",
           "max_prs": 0, "paths_include": ["package/", ".yaml"], "max_diff_chars": 2000,
           "min_desc_chars": 40, "rewriter": {"enabled": False}, "base_model": "x", "valid_ratio": 0.25}
    cfg.update(over)
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def read_jsonl(p):
    return [json.loads(l) for l in pathlib.Path(p).read_text().splitlines()]


# --- fetch_prs.py -----------------------------------------------------------

def github_handler(prs, rate_limit_once=False):
    state = {"limited": not rate_limit_once, "auth": set(), "calls": 0}

    class H(QuietHandler):
        def do_GET(self):
            state["calls"] += 1
            state["auth"].add(self.headers.get("Authorization"))
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not state["limited"]:
                state["limited"] = True
                return json_response(self, {"message": "rate limit"}, 403,
                                     {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()))})
            parts = u.path.strip("/").split("/")  # api/v3/repos/acme/infra/pulls[/n[/comments]]
            if parts[-1] == "pulls":
                page, per = int(q["page"][0]), int(q["per_page"][0])
                chunk = prs[(page - 1) * per: page * per]
                return json_response(self, [{k: v for k, v in p.items() if k not in ("diff", "comments")}
                                            for p in chunk])
            n = int(parts[-2] if parts[-1] == "comments" else parts[-1])
            pr = next(p for p in prs if p["number"] == n)
            if parts[-1] == "comments":
                return json_response(self, pr.get("comments", []))
            assert self.headers["Accept"] == "application/vnd.github.v3.diff"
            return json_response(self, None, raw=pr["diff"])

    return H, state


def make_prs(n):
    return [{"number": i, "title": f"PR {i}", "body": "opis" if i % 2 else None,
             "merged_at": None if i % 5 == 0 else "2026-01-01T00:00:00Z",
             "diff": DIFF_OK, "comments": [{"path": "package/s3/composition.yaml", "body": "dodaj tagi"}]}
            for i in range(1, n + 1)]


def test_fetch_prs_pagination_resume_and_limits(tmp_path, server):
    prs = make_prs(130)  # dwie strony po 100
    H, state = github_handler(prs)
    s = server(H)
    cfg = write_cfg(tmp_path, api_url=s.url + "/api/v3")
    out = tmp_path / "data/acme__infra/raw.jsonl"

    run("fetch_prs.py", cfg, cwd=tmp_path, env={"GH_TEST_TOKEN": "t0k"})
    rows = read_jsonl(out)
    merged = [p["number"] for p in prs if p["merged_at"]]
    assert sorted(r["number"] for r in rows) == merged  # niezmergowane pominięte, obie strony pobrane
    assert rows[0]["body"] == "" or isinstance(rows[0]["body"], str)  # None -> ""
    assert rows[0]["review_comments"] == [{"path": "package/s3/composition.yaml", "body": "dodaj tagi"}]
    assert "+  encryption: true" in rows[0]["diff"]
    assert state["auth"] == {"Bearer t0k"}

    calls = state["calls"]
    stdout = run("fetch_prs.py", cfg, cwd=tmp_path, env={"GH_TEST_TOKEN": "t0k"})
    assert "Zapisano 0 nowych" in stdout and len(read_jsonl(out)) == len(merged)  # wznowienie
    assert state["calls"] - calls == 3  # tylko listing stron, bez ponownego pobierania diffów


def test_fetch_prs_max_prs_and_no_token(tmp_path, server):
    H, state = github_handler(make_prs(20))
    s = server(H)
    cfg = write_cfg(tmp_path, api_url=s.url, max_prs=3)
    env = {k: v for k, v in os.environ.items() if k != "GH_TEST_TOKEN"}
    r = subprocess.run([PY, str(ROOT / "fetch_prs.py"), str(cfg)], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert len(read_jsonl(tmp_path / "data/acme__infra/raw.jsonl")) == 3
    assert state["auth"] == {None}  # publiczne repo bez tokenu


@pytest.mark.slow
def test_fetch_prs_waits_on_rate_limit(tmp_path, server):
    H, _ = github_handler(make_prs(2), rate_limit_once=True)
    s = server(H)
    cfg = write_cfg(tmp_path, api_url=s.url)
    t = time.time()
    stdout = run("fetch_prs.py", cfg, cwd=tmp_path)
    assert "rate limit" in stdout and time.time() - t >= 5
    assert len(read_jsonl(tmp_path / "data/acme__infra/raw.jsonl")) == 2


# --- history_to_raw.py ------------------------------------------------------

def test_history_to_raw(tmp_path):
    g = tmp_path / "g"
    g.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(g), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True)
    git("init", "-q")
    (g / "a.yaml").write_text("kind: A\n")
    git("add", "."); git("commit", "-qm", "first\n\nlonger body")
    (g / "a.yaml").write_text("kind: B\n")
    git("commit", "-qam", "second")
    cfg = write_cfg(tmp_path)
    run("history_to_raw.py", cfg, g, cwd=tmp_path)
    rows = read_jsonl(tmp_path / "data/acme__infra/raw.jsonl")
    assert [r["title"] for r in rows] == ["second", "first"]
    assert rows[1]["body"] == "longer body"
    assert "+kind: B" in rows[0]["diff"]
    run("history_to_raw.py", cfg, g, 1, cwd=tmp_path)
    assert len(read_jsonl(tmp_path / "data/acme__infra/raw.jsonl")) == 1


# --- build_dataset.py -------------------------------------------------------

def write_raw(tmp_path, rows):
    d = tmp_path / "data/acme__infra"
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def pr(n, title="Dodaj szyfrowanie do S3", body="Szczegółowy opis zmiany, wystarczająco długi na polecenie.",
       diff=DIFF_OK, comments=()):
    return {"number": n, "title": title, "body": body, "diff": diff, "review_comments": list(comments)}


def test_build_dataset_filters_and_format(tmp_path):
    d = write_raw(tmp_path, [
        pr(1, comments=[{"path": "p.yaml", "body": "użyj naszego prefiksu"}]),
        pr(2), pr(3), pr(4),
        pr(5, diff=DIFF_DOCS),                       # tylko docs -> brak plików
        pr(6, diff=DIFF_OK + "+x\n" * 2000),         # za duży
        pr(7, title="Revert \"Dodaj S3\""),          # revert
        pr(8, diff=DIFF_DOCS + DIFF_OK),             # mieszany -> zostaje tylko część package/
    ])
    out = run("build_dataset.py", write_cfg(tmp_path), cwd=tmp_path)
    assert "'brak plików': 1, 'za duży': 1, 'revert': 1" in out
    train, valid = read_jsonl(d / "train.jsonl"), read_jsonl(d / "valid.jsonl")
    assert len(train) + len(valid) == 5 and len(valid) == 1
    allx = train + valid
    for ex in allx:
        roles = [m["role"] for m in ex["messages"]]
        assert roles == ["system", "user", "assistant"]
        a = ex["messages"][2]["content"]
        assert a.startswith("```diff\n") and a.endswith("\n```")
        assert "docs/notes.md" not in a
    assert sum("Uwagi z review" in ex["messages"][1]["content"] for ex in allx) == 1


def test_build_dataset_rewrites_weak_descriptions(tmp_path, server):
    seen = []

    class H(QuietHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            json_response(self, {"choices": [{"message": {"content": "Włącz szyfrowanie w kompozycji S3."}}]})

    s = server(H)
    d = write_raw(tmp_path, [pr(1, title="fix", body=""), pr(2)])
    cfg = write_cfg(tmp_path, valid_ratio=0.0,
                    rewriter={"enabled": True, "base_url": s.url + "/v1", "model": "big", "api_key_env": "RW"})
    run("build_dataset.py", cfg, cwd=tmp_path)
    rows = read_jsonl(d / "train.jsonl") + read_jsonl(d / "valid.jsonl")
    users = sorted(r["messages"][1]["content"] for r in rows)
    assert "Włącz szyfrowanie w kompozycji S3." in users  # słaby opis przepisany
    assert len(seen) == 1 and seen[0]["model"] == "big"   # dobry opis nie poszedł do LLM
    assert "encryption" in seen[0]["messages"][0]["content"]  # rewriter widzi diff


def test_build_dataset_empty_input(tmp_path):
    d = write_raw(tmp_path, [pr(1, diff=DIFF_DOCS)])
    out = run("build_dataset.py", write_cfg(tmp_path), cwd=tmp_path)
    assert "train=0 valid=0" in out
    assert (d / "train.jsonl").read_text() == ""


# --- bench_context.py i skrypty powłoki -------------------------------------

def test_bench_context(repo, tmp_path):
    j = tmp_path / "b.json"
    out = run("bench_context.py", repo, "--json", j, "--query", "azure virtual network", cwd=tmp_path)
    res = json.loads(j.read_text())
    assert res["files"] == 7 and res["repo_map_chars"] < res["full_chars"]
    assert res["xrds"][0]["kind"] == "XNetwork"
    assert res["retrieval"]["azure virtual network"]["sources"][0].startswith("package/network/compositions")
    assert "| Mapa repo (strategia 1) |" in out


@pytest.mark.parametrize("script", ["train.sh", "serving/vllm.sh"])
def test_shell_syntax(script):
    subprocess.run(["bash", "-n", str(ROOT / script)], check=True)


def test_configs_are_valid():
    need = {"api_url", "repo", "paths_include", "max_diff_chars", "min_desc_chars", "rewriter",
            "base_model", "valid_ratio"}
    for p in (ROOT / "configs").glob("*.yaml"):
        assert need <= set(yaml.safe_load(p.read_text())), p
