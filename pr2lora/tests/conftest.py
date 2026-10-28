import json
import pathlib
import sys
import threading
import textwrap
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import stub_llm  # noqa: E402

XRD = """\
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xnetworks.demo.io
spec:
  group: demo.io
  names: {kind: XNetwork, plural: xnetworks}
  claimNames: {kind: Network, plural: networks}
  versions:
  - name: v1alpha1
    served: true
    referenceable: false
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec: {type: object, properties: {old: {type: string}}}
  - name: v1beta1
    served: true
    referenceable: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              cloudRegion: {type: string}
              subnets:
                type: object
                properties:
                  cidr: {type: string}
            required: [cloudRegion]
"""

PIPELINE = """\
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: xnetworks-gcp
spec:
  compositeTypeRef: {apiVersion: demo.io/v1beta1, kind: XNetwork}
  mode: Pipeline
  pipeline:
  - step: patch-and-transform
    functionRef: {name: function-patch-and-transform}
  - step: auto-ready
    functionRef: {name: function-auto-ready}
---
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: xnetworks-azure
spec:
  compositeTypeRef: {apiVersion: demo.io/v1beta1, kind: XNetwork}
  resources:
  - name: vnet
    base: {apiVersion: network.azure.upbound.io/v1beta1, kind: VirtualNetwork}
  - name: rg
    base: {apiVersion: azure.upbound.io/v1beta1, kind: ResourceGroup}
"""

GO = """\
package main

type Function struct{}

func (f *Function) RunFunction(ctx context.Context,
    req *fnv1.RunFunctionRequest) (*fnv1.RunFunctionResponse, error) {
    return nil, nil
}

func resourceName(team, env string) string {
    return team + "-" + env
}
"""

PY = """\
class Helper:
    def name(self, team, env):
        return team

def render(spec, region="eu"):
    return spec
"""


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    files = {
        "package/network/definition.yaml": XRD,
        "package/network/compositions.yaml": PIPELINE,
        "package/network/kustomization.yaml": "apiVersion: kustomize.config.k8s.io/v1beta1\n"
                                              "kind: Kustomization\nresources: [definition.yaml]\n",
        "functions/naming/main.go": GO,
        "tools/helper.py": PY,
        "examples/broken.yaml": "kind: [unclosed\n  : :\n",
        "examples/claim.yaml": "apiVersion: demo.io/v1beta1\nkind: Network\nmetadata: {name: n1}\n"
                               "spec: {cloudRegion: europe-west3}\n",
        "README.md": "# not indexed\n",
        "node_modules/x/skip.yaml": "kind: ShouldBeSkipped\nmetadata: {name: x}\n",
    }
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    return r


class _Server:
    def __init__(self, handler):
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def stub(monkeypatch):
    stub_llm.LOG.clear()
    s = _Server(stub_llm.H)
    monkeypatch.setenv("LLM_URL", s.url + "/v1")
    yield s
    s.close()


@pytest.fixture
def server():
    """Fabryka serwerów HTTP z własnym handlerem (np. atrapa API GitHuba)."""
    started = []

    def make(handler):
        s = _Server(handler)
        started.append(s)
        return s

    yield make
    for s in started:
        s.close()


def json_response(handler, obj, status=200, headers=None, raw=None):
    body = raw.encode() if raw is not None else json.dumps(obj).encode()
    handler.send_response(status)
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
