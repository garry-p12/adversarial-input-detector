import pickle
from typing import List

import numpy as np
from sklearn.linear_model import LogisticRegression

from ._embedder import get_embedder


class AdversarialClassifier:
    def __init__(self):
        self.clf: LogisticRegression | None = None
        self._adv_idx: int = 1

    def _embed(self, payloads: List[str]) -> np.ndarray:
        emb = get_embedder()
        return np.asarray(emb.encode(payloads, show_progress_bar=False, normalize_embeddings=False), dtype=np.float64)

    def fit(self, payloads: List[str], labels: List[int]) -> None:
        X = self._embed(payloads)
        y = np.asarray(labels, dtype=int)
        self.clf = LogisticRegression(max_iter=1000, C=1.0)
        self.clf.fit(X, y)
        classes = list(self.clf.classes_)
        self._adv_idx = classes.index(1) if 1 in classes else (len(classes) - 1)

    def score(self, payload: str) -> float:
        v = self._embed([payload])
        proba = self.clf.predict_proba(v)[0]
        return float(proba[self._adv_idx])

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump({"clf": self.clf, "adv_idx": self._adv_idx}, f)

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            d = pickle.load(f)
        self.clf = d["clf"]
        self._adv_idx = d["adv_idx"]
