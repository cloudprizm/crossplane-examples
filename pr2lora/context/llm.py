"""Wspólny klient LLM dla endpointów zgodnych z OpenAI (vLLM, mlx_lm.server, Ollama, SGLang).

Konfiguracja przez zmienne środowiskowe:
  LLM_URL     np. http://localhost:8000/v1   (vLLM) albo http://localhost:8080/v1 (mlx_lm.server)
  LLM_MODEL   nazwa modelu lub adaptera LoRA w vLLM (np. crossplane-infra)
  LLM_API_KEY klucz, jeśli serwer go wymaga (vLLM --api-key)
"""
import os

import requests

URL = os.environ.get("LLM_URL", "http://localhost:8000/v1")
MODEL = os.environ.get("LLM_MODEL", "local")
API_KEY = os.environ.get("LLM_API_KEY", "none")


def chat(messages, tools=None, url=None, model=None, temperature=0.2, timeout=300):
    """Zwraca cały obiekt message z odpowiedzi (z ewentualnymi tool_calls)."""
    body = {"model": model or MODEL, "messages": messages, "temperature": temperature}
    if tools:
        body["tools"] = tools
    r = requests.post(
        f"{(url or URL).rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=body,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def llm(messages, **kw):
    """Skrót: zwraca sam tekst odpowiedzi."""
    return (chat(messages, **kw).get("content") or "").strip()
