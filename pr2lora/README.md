# PR2LoRA

Lokalny model kodujący (Qwen Coder), który zna Crossplane i wzorce Twojego zespołu:

- **dataset z historii PR-ów** (opis PR = polecenie, diff = odpowiedź, komentarze review = wskazówki),
- **fine-tuning LoRA** na Macu (MLX) — uczy stylu i wzorców, nie faktów,
- **odchudzanie kontekstu** (`context/`) — model dostaje tylko to, czego potrzebuje w danym kroku,
- **serwowanie dla zespołu** przez vLLM na EC2.

Fakty (pola API, dokumentacja) idą przez kontekst/RAG, bo zmieniają się między wersjami. Fine-tuning uczy *jak robimy rzeczy*.

## Struktura

```
configs/            konfiguracja per repo (GitHub Enterprise albo github.com)
fetch_prs.py        PR-y z API GitHuba -> data/<repo>/raw.jsonl
history_to_raw.py   alternatywa: commity z lokalnego klonu (bez API)
build_dataset.py    filtrowanie, przepisywanie słabych opisów, train/valid.jsonl
train.sh            LoRA w MLX + fuse -> models/<repo>
context/            sześć strategii zarządzania kontekstem
bench_context.py    pomiar, ile kontekstu oszczędza każda strategia
serving/vllm.sh     serwer dla zespołu na EC2
tests/stub_llm.py   atrapa serwera LLM do testów pętli bez modelu
```

## Szybki start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. dane
export GITHUB_TOKEN=...
python fetch_prs.py configs/my-repo.yaml
#   albo bez API:  python history_to_raw.py configs/my-repo.yaml ~/workspaces/moje-repo
python build_dataset.py configs/my-repo.yaml

# 2. trening (Mac M3 32 GB, 7B 4-bit: ok. 15–60 min)
./train.sh configs/my-repo.yaml 600
python -m mlx_lm.generate --model models/org__crossplane-platform \
  --prompt "Dodaj kompozycję dla bucketu S3 z szyfrowaniem"

# 3. kontekst
python bench_context.py ~/workspaces/moje-repo
python -m context.repo_map ~/workspaces/moje-repo
python -m context.retrieve ~/workspaces/moje-repo "jak definiujemy podsieci w GCP"
python -m context.xrd ~/workspaces/moje-repo XNetwork

# 4. z modelem (mlx_lm.server albo vLLM)
mlx_lm.server --model models/org__crossplane-platform --port 8080
export LLM_URL=http://localhost:8080/v1 LLM_MODEL=default
python -m context.agent ~/workspaces/moje-repo "Dodaj pole tier do XRD sieci"
python -m context.summaries ~/workspaces/moje-repo
```

## Strategie kontekstu (`context/`)

| # | Moduł | Co daje | Kiedy |
| --- | --- | --- | --- |
| 1 | `repo_map.py` | struktura repo: XRD (z polami), kompozycje (kroki pipeline / zasoby), sygnatury kodu | zawsze, na start |
| 2 | `agent.py` | model sam woła `grep`, `read_file`, `search` | zadania wieloplikowe |
| 3 | `retrieve.py` | top-k fragmentów (dokument YAML / funkcja); embeddingi albo TF-IDF offline | „jak to u nas robimy” |
| 4 | `decompose.py` | plan, potem każdy krok ze świeżym kontekstem | duże zmiany |
| 5 | `summaries.py` | 3–5 zdań na katalog, cache po hashu w `.context/` | duże repo, CI po merge'u |
| 6 | `xrd.py` | schemat jednego XRD + pętla poprawek z `crossplane beta validate` | generowanie YAML-i |

Wszystkie moduły z modelem używają `context/llm.py` (`LLM_URL`, `LLM_MODEL`, `LLM_API_KEY`), więc działają z mlx_lm.server, vLLM, SGLang i Ollamą.

## Wyniki testu na prawdziwym repo

Uruchomione 28.10.2026 na `cloudprizm/crossplane-examples` (29 plików YAML, 4 XRD, 7 kompozycji), w środowisku bez internetu: sygnatury przez regex, wyszukiwanie przez TF-IDF. Tokeny ≈ znaki/4.

| Co trafia do kontekstu | Znaki | ~Tokeny | Redukcja |
| --- | --- | --- | --- |
| Całe repo | 42 375 | ~10 600 | – |
| Mapa repo | 2 506 | ~630 | 94% |
| Wyszukiwanie „network subnet definition for gcp” (top 4) | 2 027 | ~510 | 95% |
| Wyszukiwanie „azure sql database composition” (top 4) | 4 742 | ~1 190 | 89% |
| Wyszukiwanie „account project subscription” (top 4) | 1 885 | ~470 | 96% |
| Schemat jednego XRD (średnio) | 702 | ~180 | 98% |

Na wcześniejszym, sztucznym repo z 3 plików mapa dawała 68% — im większe repo, tym większy zysk, bo mapa rośnie z liczbą zasobów, nie z długością plików.

Przetestowane też (na atrapie serwera, `tests/stub_llm.py`):
- `agent.py` — pętla grep → read_file → odpowiedź działa; ścieżki spoza repo są blokowane,
- `decompose.py` — plan z JSON-a i kroki ze świeżym kontekstem,
- `summaries.py` — 8 katalogów, drugi przebieg w całości z cache,
- `xrd.py` — znajduje XRD także po nazwie claimu (`Network` → `XNetwork`).

**Nie przetestowane** (brak w środowisku testowym): trening MLX (wymaga Maca), embeddingi `sentence-transformers` i tree-sitter (brak dostępu do PyPI/Hugging Face), `crossplane beta validate` (brak CLI), prawdziwy model. Jakość odpowiedzi modelu trzeba ocenić u siebie.

### Próbny dataset

`history_to_raw.py` + `build_dataset.py` na tym samym repo: 16 commitów → 15 train / 1 valid, przykłady 1,4–24 tys. znaków. Dwie obserwacje:
- opisy typu „order rgp and vnet for better look” są za słabe na polecenie — dla prawdziwych danych włącz `rewriter`,
- 16 przykładów to za mało na trening; minimum to ok. 100–200 PR-ów.

## Serwowanie dla zespołu (EC2)

`serving/vllm.sh` — vLLM zamiast Ollamy (continuous batching, prefix caching dla stałej mapy repo, API zgodne z OpenAI). Szacunki, nie pomiary:

| Model (4-bit) na GPU 24 GB | Tokeny/s dla 1 osoby (L4 / A10G) | Równolegle przy 8 tys. kontekstu |
| --- | --- | --- |
| Qwen2.5-Coder 7B | ~40–50 / ~70–90 | ~30 |
| Qwen2.5-Coder 14B | ~20–25 / ~40–50 | ~7 |
| Qwen2.5-Coder 32B | nie mieści się z kontekstem (potrzebne 48 GB, g6e.xlarge) | – |

Koszt g6.xlarge, pon–pt 7:00–20:00 (~282 h/mies.): spot ~$93 (eu-west-3) / ~$138 (eu-central-1), on-demand ~$285, plus dysk ~$10. Ceny spot z października 2026, zmieniają się codziennie.

Realną liczbę równoległych zapytań vLLM wypisuje przy starcie (`Maximum concurrency`).

## Następne kroki

- Odfiltrowywać z datasetu przykłady, które nie przechodzą `crossplane beta validate`.
- Doinstalować `sentence-transformers` i tree-sitter i powtórzyć `bench_context.py`.
- Przetestować bazowego Qwen Codera na kilku prawdziwych zadaniach przed treningiem.
- Adaptery MLX nie są w formacie PEFT — do vLLM trenować na EC2 (PEFT/Unsloth) albo konwertować.
