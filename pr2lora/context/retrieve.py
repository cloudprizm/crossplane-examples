"""Strategia 3: wyszukiwanie semantyczne po kawałkach kodu.

Kod jest cięty po jednostkach logicznych (jeden dokument YAML, jedna funkcja/klasa).
Backend:
  - "embed": sentence-transformers + BAAI/bge-small-en-v1.5 (lepsza jakość, wymaga pobrania modelu)
  - "tfidf": scikit-learn, działa offline (słowa kluczowe zamiast znaczenia)
  - "auto":  embed, a jeśli niedostępny - tfidf

    python -m context.retrieve /sciezka/do/repo "jak definiujemy siec w GCP"
"""
import pathlib
import re
import sys

import numpy as np

from .repo_map import CODE_EXT, YAML_EXT, iter_files

YAML_SPLIT = re.compile(r"^---\s*$", re.M)
CODE_SPLIT = re.compile(r"(?=^(?:def |class |func |export function |function ))", re.M)


def chunks(root):
    root = pathlib.Path(root)
    for p in iter_files(root):
        rel = str(p.relative_to(root))
        text = p.read_text(errors="ignore")
        if p.suffix in YAML_EXT:
            for i, doc in enumerate(YAML_SPLIT.split(text)):
                if doc.strip():
                    yield f"{rel}#{i}", doc.strip()
        elif p.suffix in CODE_EXT:
            for part in CODE_SPLIT.split(text):
                if part.strip():
                    yield rel, part.strip()


class Index:
    def __init__(self, root, backend="auto", model="BAAI/bge-small-en-v1.5"):
        self.items = list(chunks(root))
        texts = [t[:2000] for _, t in self.items]
        self.backend = backend
        if backend in ("auto", "embed"):
            try:
                from sentence_transformers import SentenceTransformer
                self.emb = SentenceTransformer(model)
                self.vecs = self.emb.encode(texts, normalize_embeddings=True)
                self.backend = "embed"
                return
            except Exception:
                if backend == "embed":
                    raise
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.tfidf = TfidfVectorizer(token_pattern=r"[A-Za-z][A-Za-z0-9_]+", sublinear_tf=True)
        self.vecs = self.tfidf.fit_transform(texts)
        self.backend = "tfidf"

    def _scores(self, query):
        if self.backend == "embed":
            q = self.emb.encode([query], normalize_embeddings=True)[0]
            return self.vecs @ q
        return (self.vecs @ self.tfidf.transform([query]).T).toarray().ravel()

    def search_items(self, query, k=5, budget=6000):
        out, used = [], 0
        for i in np.argsort(-self._scores(query))[:k]:
            src, text = self.items[i]
            if used + len(text) > budget:
                break
            out.append((src, text))
            used += len(text)
        return out

    def search(self, query, k=5, budget=6000):
        return "\n\n".join(f"# {s}\n{t}" for s, t in self.search_items(query, k, budget))


if __name__ == "__main__":
    idx = Index(sys.argv[1])
    print(f"[backend={idx.backend}, fragmentów={len(idx.items)}]\n")
    print(idx.search(" ".join(sys.argv[2:]), k=4))
