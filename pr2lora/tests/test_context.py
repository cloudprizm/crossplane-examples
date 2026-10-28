import json
import os
import stat

import pytest

import stub_llm
from context import decompose, retrieve, summaries, xrd
from context.agent import Tools, agent
from context.repo_map import repo_map, yaml_summary


# --- 1. mapa repo -----------------------------------------------------------

def test_repo_map_crossplane_resources(repo):
    m = repo_map(repo, use_tree_sitter=False)
    assert "CompositeResourceDefinition xnetworks.demo.io xr=XNetwork claim=Network" in m
    assert "fields=['cloudRegion', 'subnets', 'subnets.cidr']" in m  # wersja referenceable, nie pierwsza
    assert "Composition xnetworks-gcp -> XNetwork steps=['patch-and-transform', 'auto-ready']" in m
    assert "Composition xnetworks-azure -> XNetwork resources=['VirtualNetwork', 'ResourceGroup']" in m
    assert "Kustomization None resources=['definition.yaml']" in m
    assert "Network n1" in m


def test_repo_map_skips_and_survives_bad_files(repo):
    m = repo_map(repo, use_tree_sitter=False)
    assert "ShouldBeSkipped" not in m  # node_modules
    assert "README.md" not in m
    assert "broken.yaml" not in m  # zepsuty YAML nie wywraca mapy
    assert yaml_summary(repo / "examples/broken.yaml") == []


def test_repo_map_signatures_regex(repo):
    m = repo_map(repo, use_tree_sitter=False)
    assert "  func resourceName(team, env string) string\n" in m
    # sygnatura na dwie linie sklejona do końca, aż do {
    assert ("func (f *Function) RunFunction(ctx context.Context, req *fnv1.RunFunctionRequest) "
            "(*fnv1.RunFunctionResponse, error)") in m
    assert "  class Helper\n    def name(self, team, env)\n" in m  # metoda wcięta pod klasą
    assert '  def render(spec, region="eu")' in m


def test_regex_signatures_python_type_hints(tmp_path):
    from context.repo_map import regex_signatures
    p = tmp_path / "t.py"
    p.write_text("async def fetch(url: str,\n          timeout: int = 5) -> dict:\n    pass\n")
    assert regex_signatures(p) == ["  async def fetch(url: str, timeout: int = 5) -> dict"]


def test_repo_map_budget(repo):
    full = repo_map(repo, use_tree_sitter=False)
    cut = repo_map(repo, max_chars=200, use_tree_sitter=False)
    assert len(full) > 200
    assert cut.endswith("(przycięto do budżetu)")
    assert len(cut) < 260


def test_repo_map_is_much_smaller_than_repo(repo):
    m = repo_map(repo, use_tree_sitter=False)
    total = sum(len(p.read_text()) for p in repo.rglob("*.yaml")) + len((repo / "functions/naming/main.go").read_text())
    assert len(m) < total * 0.7


# --- 3. wyszukiwanie --------------------------------------------------------

def test_chunks_split_yaml_docs_and_functions(repo):
    items = list(retrieve.chunks(repo))
    srcs = [s for s, _ in items]
    assert "package/network/compositions.yaml#0" in srcs
    assert "package/network/compositions.yaml#1" in srcs
    go = [t for s, t in items if s == "functions/naming/main.go"]
    assert len(go) == 3 and go[2].startswith("func resourceName")
    assert not any("node_modules" in s for s in srcs)


def test_search_finds_relevant_and_respects_budget(repo):
    idx = retrieve.Index(repo, backend="tfidf")
    assert idx.backend == "tfidf"
    top = idx.search_items("azure VirtualNetwork ResourceGroup", k=3)
    assert top[0][0] == "package/network/compositions.yaml#1"
    small = idx.search_items("network", k=10, budget=300)
    assert sum(len(t) for _, t in small) <= 300
    assert idx.search("resourceName team env", k=1).startswith("# functions/naming/main.go")


def test_search_embed_backend_missing_raises_when_forced(repo):
    pytest.importorskip("sklearn")
    try:
        import sentence_transformers  # noqa: F401
        pytest.skip("sentence-transformers zainstalowany")
    except ImportError:
        pass
    with pytest.raises(Exception):
        retrieve.Index(repo, backend="embed")
    assert retrieve.Index(repo, backend="auto").backend == "tfidf"


# --- 6. XRD -----------------------------------------------------------------

def test_find_xrd_by_xr_and_claim(repo):
    p1, d1 = xrd.find_xrd(repo, "XNetwork")
    p2, d2 = xrd.find_xrd(repo, "Network")
    assert p1 == p2 and p1.name == "definition.yaml"
    with pytest.raises(KeyError):
        xrd.find_xrd(repo, "XNope")


def test_schema_text_uses_referenceable_version(repo):
    _, d = xrd.find_xrd(repo, "XNetwork")
    s = xrd.schema_text(d)
    assert "cloudRegion" in s and "old" not in s


@pytest.mark.parametrize("raw,expected", [
    ("```yaml\nkind: X\n```", "kind: X"),
    ("```\nkind: X\n```\n", "kind: X"),
    ("kind: X", "kind: X"),
    ("  \n```yml\na: 1\nb: 2\n```  ", "a: 1\nb: 2"),
])
def test_strip_fences(raw, expected):
    assert xrd.strip_fences(raw) == expected


@pytest.fixture
def fake_crossplane(tmp_path, monkeypatch):
    """Udaje `crossplane beta validate`: przechodzi tylko, gdy plik zawiera cloudRegion."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "crossplane"
    exe.write_text('#!/bin/sh\nif grep -q cloudRegion "$4"; then echo ok; exit 0; fi\n'
                   'echo "spec.cloudRegion: Required value"; exit 1\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_generate_with_validation_retries_until_valid(repo, fake_crossplane, monkeypatch):
    calls = []

    def fake_llm(msgs):
        calls.append(msgs)
        if len(calls) == 1:
            return "```yaml\nkind: Network\nspec: {}\n```"
        return "```yaml\nkind: Network\nspec: {cloudRegion: eu}\n```"

    monkeypatch.setattr("context.llm.llm", fake_llm)
    out = xrd.generate_with_validation(repo, "Network", "claim w eu")
    assert out == "kind: Network\nspec: {cloudRegion: eu}"
    assert len(calls) == 2
    assert "Required value" in calls[1][-1]["content"]  # błąd walidatora wrócił do modelu
    assert "cloudRegion" in calls[0][0]["content"]       # model dostał tylko schemat XRD


def test_generate_with_validation_gives_up(repo, fake_crossplane, monkeypatch):
    monkeypatch.setattr("context.llm.llm", lambda m: "kind: Network")
    with pytest.raises(RuntimeError):
        xrd.generate_with_validation(repo, "Network", "x", retries=2)


# --- 2. agent i narzędzia ---------------------------------------------------

def test_tools(repo):
    t = Tools(repo)
    assert "package/network/definition.yaml" in t.run("grep", {"pattern": "cloudRegion"})
    assert t.run("grep", {"pattern": "zzz_nie_ma_zzz"}) == "brak wyników"
    assert t.run("grep", {"pattern": "-v"}) != ""  # wzorzec z myślnikiem nie jest flagą
    assert t.run("read_file", {"path": "functions/naming/main.go", "start": 1, "end": 1}) == "1: package main"
    assert t.run("read_file", {"path": "../../etc/passwd"}).startswith("błąd")
    assert t.run("read_file", {"path": "nie/ma.yaml"}).startswith("błąd")
    assert t.run("search", {"query": "x"}).startswith("nieznane")  # bez indeksu


def test_agent_loop_with_stub(repo, stub):
    idx = retrieve.Index(repo, backend="tfidf")
    out = agent("Dodaj pole tier", repo, index=idx)
    assert out.startswith("Gotowe")
    assert len(stub_llm.LOG) == 3  # grep -> read_file -> odpowiedź


# --- 4. dzielenie zadania ---------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ('["a", "b"]', ["a", "b"]),
    ('Plan:\n```json\n["a", "b"]\n```', ["a", "b"]),
    ("1. a\n2. b\n", ["a", "b"]),
    ("- a\n- b", ["a", "b"]),
])
def test_parse_plan(text, expected):
    assert decompose.parse_plan(text) == expected


def test_solve_with_stub(repo, stub):
    idx = retrieve.Index(repo, backend="tfidf")
    res = decompose.solve("Dodaj pole tier", repo_map(repo, use_tree_sitter=False), idx)
    assert [r["step"] for r in res] == ["Znajdź XRD sieci", "Dodaj pole tier do schematu", "Zaktualizuj kompozycję GCP"]
    # każdy krok ma świeży, mały kontekst - nie rośnie z liczbą kroków
    step_prompts = stub_llm.LOG[1::2]
    assert max(step_prompts) < 6000 + 1000


# --- 5. streszczenia --------------------------------------------------------

def test_summaries_cache_and_invalidation(repo, stub):
    c1 = summaries.summarize_repo(repo)
    n_calls = len(stub_llm.LOG)
    assert set(c1) == {"package/network", "functions/naming", "tools", "examples"}
    assert (repo / ".context/summaries.json").exists()
    summaries.summarize_repo(repo)
    assert len(stub_llm.LOG) == n_calls  # nic się nie zmieniło -> zero wywołań
    (repo / "tools/helper.py").write_text("def changed(): pass\n")
    c3 = summaries.summarize_repo(repo)
    assert len(stub_llm.LOG) == n_calls + 1  # tylko zmieniony katalog
    assert c3["tools"]["hash"] != c1["tools"]["hash"]
    assert "package/network:" in summaries.as_context(c3)
    assert json.loads((repo / ".context/summaries.json").read_text()) == c3
