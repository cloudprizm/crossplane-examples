"""Strategia 4: dzielenie zadania na kroki.

Najpierw plan (lista kroków), potem każdy krok ze świeżym kontekstem:
tylko fragmenty znalezione dla tego kroku + 1-zdaniowe notatki z poprzednich.
"""
import json
import re

from .llm import llm


def parse_plan(text):
    m = re.search(r"\[.*\]", text, re.S)
    try:
        plan = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        plan = []
    return [str(s) for s in plan] or [l.strip("-* 0123456789.") for l in text.splitlines() if l.strip()]


def solve(task, repo_map_text, index, max_steps=6):
    plan = parse_plan(llm([{"role": "user", "content":
        f"Mapa repo:\n{repo_map_text}\n\nRozbij zadanie na 2-{max_steps} kroków. "
        f"Zwróć wyłącznie listę JSON stringów.\nZadanie: {task}"}]))[:max_steps]
    notes, results = [], []
    for step in plan:
        ctx = index.search(step, k=4)  # tylko kontekst dla tego kroku
        out = llm([{"role": "system", "content": "Dotychczas zrobiono: " + (" | ".join(notes[-5:]) or "nic")},
                   {"role": "user", "content": f"Kontekst:\n{ctx}\n\nKrok: {step}"}])
        results.append({"step": step, "output": out})
        notes.append(llm([{"role": "user", "content": f"Streść w 1 zdaniu, co zrobiono:\n{out[:4000]}"}]))
    return results
