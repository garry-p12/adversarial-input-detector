from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from institute_perimeter.detectors.anomaly import MahalanobisAnomalyDetector
from institute_perimeter.detectors.classifier import AdversarialClassifier


_PKG_ROOT = Path(__file__).resolve().parent.parent
_CORPUS_PATH = _PKG_ROOT / "training" / "corpus.csv"
_ARTIFACTS_DIR = _PKG_ROOT / "artifacts"
_TEST_SPLIT_PATH = _ARTIFACTS_DIR / "test_split.csv"
_ANOMALY_PATH = _ARTIFACTS_DIR / "anomaly.pkl"
_CLASSIFIER_PATH = _ARTIFACTS_DIR / "classifier.pkl"


def main():
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(_CORPUS_PATH)
    print(f"Loaded corpus: {len(df)} rows ({(df.label == 'benign').sum()} benign, {(df.label == 'adversarial').sum()} adversarial)")

    train_df, test_df = train_test_split(
        df, test_size=0.2, stratify=df["label"], random_state=42
    )
    test_df.to_csv(_TEST_SPLIT_PATH, index=False)
    print(f"Saved test split to {_TEST_SPLIT_PATH} ({len(test_df)} rows)")

    benign_train = train_df[train_df.label == "benign"]["payload"].tolist()
    print(f"Fitting anomaly detector on {len(benign_train)} benign rows...")
    anomaly = MahalanobisAnomalyDetector()
    anomaly.fit(benign_train)
    anomaly.save(str(_ANOMALY_PATH))
    print(f"Saved anomaly detector to {_ANOMALY_PATH}")

    payloads = train_df["payload"].tolist()
    labels = (train_df["label"] == "adversarial").astype(int).tolist()
    print(f"Fitting classifier on {len(payloads)} rows...")
    clf = AdversarialClassifier()
    clf.fit(payloads, labels)
    clf.save(str(_CLASSIFIER_PATH))
    print(f"Saved classifier to {_CLASSIFIER_PATH}")

    train_preds = [1 if clf.score(p) >= 0.5 else 0 for p in payloads]
    correct = sum(1 for a, b in zip(train_preds, labels) if a == b)
    acc = correct / len(labels)
    print(f"Classifier train accuracy: {acc:.4f}")


if __name__ == "__main__":
    main()
