import pickle
from typing import List

import numpy as np
from sklearn.covariance import LedoitWolf

from ._embedder import get_embedder


# Ledoit-Wolf shrinkage covariance handles the N<<dim regime (~80 benign rows
# vs 384-D embeddings) by interpolating between sample covariance and a scaled
# identity, with the shrinkage intensity chosen analytically. The resulting
# precision matrix is well-conditioned without dropping the directions that
# separate benign from adversarial inputs (PCA-on-benign dropped exactly those).
class MahalanobisAnomalyDetector:
    def __init__(self):
        self.mean: np.ndarray | None = None
        self.precision: np.ndarray | None = None
        self.scale: float = 1.0

    def _embed(self, payloads: List[str]) -> np.ndarray:
        emb = get_embedder()
        return np.asarray(emb.encode(payloads, show_progress_bar=False, normalize_embeddings=False), dtype=np.float64)

    def _distance(self, v: np.ndarray) -> float:
        diff = v - self.mean
        d2 = float(diff @ self.precision @ diff.T)
        return float(np.sqrt(max(d2, 0.0)))

    def fit(self, benign_payloads: List[str]) -> None:
        X = self._embed(benign_payloads)
        lw = LedoitWolf().fit(X)
        self.mean = np.asarray(lw.location_, dtype=np.float64)
        self.precision = np.asarray(lw.precision_, dtype=np.float64)
        dists = np.array([self._distance(x) for x in X])
        med = float(np.median(dists))
        self.scale = max(med, 1e-6)

    def score(self, payload: str) -> float:
        v = self._embed([payload])[0]
        d = self._distance(v)
        s = 1.0 - float(np.exp(-d / self.scale))
        return float(np.clip(s, 0.0, 1.0))

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump({"mean": self.mean, "precision": self.precision, "scale": self.scale}, f)

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            d = pickle.load(f)
        self.mean = d["mean"]
        self.precision = d["precision"]
        self.scale = d["scale"]
