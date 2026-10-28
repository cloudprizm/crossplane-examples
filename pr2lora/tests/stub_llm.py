"""Atrapa serwera zgodnego z OpenAI do testowania pętli (agent, solve, summaries) bez prawdziwego modelu.

Odpowiada według prostych reguł: agent najpierw woła grep, potem read_file, potem kończy;
prośba o plan dostaje listę JSON; reszta dostaje krótki tekst. Loguje wielkość każdego promptu.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        LOG.append(sum(len(m.get("content") or "") for m in msgs))
        last = msgs[-1].get("content") or ""
        n_tool = sum(1 for m in msgs if m["role"] == "tool")
        msg = {"role": "assistant", "content": "ok"}
        if body.get("tools") and n_tool == 0:
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                   "function": {"name": "grep", "arguments": json.dumps({"pattern": "cloudRegion"})}}]}
        elif body.get("tools") and n_tool == 1:
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c2", "type": "function",
                   "function": {"name": "read_file", "arguments": json.dumps(
                       {"path": "package/network/definition.yaml", "start": 1, "end": 15})}}]}
        elif body.get("tools"):
            msg["content"] = "Gotowe: pole tier dodane do XNetwork (atrapa)."
        elif "listę JSON" in last:
            msg["content"] = '["Znajdź XRD sieci", "Dodaj pole tier do schematu", "Zaktualizuj kompozycję GCP"]'
        elif "Streść" in last:
            msg["content"] = "Krok wykonany."
        elif "Opisz w 3-5" in last:
            msg["content"] = "Katalog definiuje zasoby Crossplane (atrapa streszczenia)."
        out = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8099), H).serve_forever()
