"""Strategia 2: narzędzia zamiast kontekstu.

Model dostaje mapę repo i narzędzia (grep, read_file, search). Sam dociąga to, czego potrzebuje.

    LLM_URL=http://localhost:8000/v1 LLM_MODEL=... python -m context.agent /repo "Dodaj pole tier do XRD sieci"
"""
import json
import pathlib
import subprocess
import sys

from .llm import chat
from .repo_map import repo_map

TOOLS = [
    {"type": "function", "function": {
        "name": "grep", "description": "Szukaj tekstu/regexu w repo, zwraca plik:linia:treść",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}},
                       "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Odczytaj fragment pliku (numery linii od 1)",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search", "description": "Wyszukaj fragmenty kodu pasujące do opisu",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
]


class Tools:
    def __init__(self, root, index=None):
        self.root = pathlib.Path(root).resolve()
        self.index = index

    def _safe(self, rel):
        p = (self.root / rel).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("ścieżka poza repo")
        return p

    def run(self, name, args):
        try:
            if name == "grep":
                r = subprocess.run(["rg", "-n", "--max-count", "5", "-e", args["pattern"], str(self.root)],
                                   capture_output=True, text=True, timeout=30)
                return r.stdout.replace(str(self.root) + "/", "")[:4000] or "brak wyników"
            if name == "read_file":
                lines = self._safe(args["path"]).read_text(errors="ignore").splitlines()
                s, e = int(args.get("start") or 1), int(args.get("end") or 200)
                return "\n".join(f"{i}: {l}" for i, l in enumerate(lines[s - 1:e], s))
            if name == "search" and self.index:
                return self.index.search(args["query"], k=4)
            return f"nieznane narzędzie {name}"
        except Exception as ex:  # błąd wraca do modelu, żeby mógł się poprawić
            return f"błąd: {ex}"


def agent(task, root, index=None, max_steps=10):
    tools = Tools(root, index)
    msgs = [{"role": "system", "content": "Pracujesz w repozytorium Crossplane. Masz mapę repo i narzędzia. "
                                          "Czytaj tylko to, czego potrzebujesz.\n\nMapa repo:\n" + repo_map(root)},
            {"role": "user", "content": task}]
    for _ in range(max_steps):
        m = chat(msgs, tools=TOOLS if index else TOOLS[:2])
        msgs.append(m)
        if not m.get("tool_calls"):
            return m.get("content")
        for c in m["tool_calls"]:
            out = tools.run(c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return "Przekroczono limit kroków"


if __name__ == "__main__":
    print(agent(" ".join(sys.argv[2:]), sys.argv[1]))
