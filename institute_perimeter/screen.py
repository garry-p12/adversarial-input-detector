import json
import time
from pathlib import Path

from .models import (
    InstituteInput,
    InputSource,
    ScreenResult,
    DetectorSubscores,
)
from .detectors.rule_based import score as rb_score
from .detectors.anomaly import MahalanobisAnomalyDetector
from .detectors.classifier import AdversarialClassifier
from .aggregator import load_rules, aggregate


_PKG_ROOT = Path(__file__).parent
_MISSION_PATH = _PKG_ROOT / "config" / "mission.json"
_RULES_PATH = _PKG_ROOT / "config" / "aggregation.yaml"
_ANOMALY_PATH = _PKG_ROOT / "artifacts" / "anomaly.pkl"
_CLASSIFIER_PATH = _PKG_ROOT / "artifacts" / "classifier.pkl"

_MISSION_CONFIG = None
_RULES = None
_ANOMALY_DETECTOR = None
_CLASSIFIER = None


def _lazy_load():
    global _MISSION_CONFIG, _RULES, _ANOMALY_DETECTOR, _CLASSIFIER
    if _MISSION_CONFIG is None:
        with open(_MISSION_PATH, "r") as f:
            _MISSION_CONFIG = json.load(f)
    if _RULES is None:
        _RULES = load_rules(str(_RULES_PATH))
    if _ANOMALY_DETECTOR is None:
        det = MahalanobisAnomalyDetector()
        det.load(str(_ANOMALY_PATH))
        _ANOMALY_DETECTOR = det
    if _CLASSIFIER is None:
        clf = AdversarialClassifier()
        clf.load(str(_CLASSIFIER_PATH))
        _CLASSIFIER = clf


def screen(input: InstituteInput, source: InputSource) -> ScreenResult:
    _lazy_load()
    t0 = time.perf_counter()

    rb = rb_score(input.payload, input.metadata, _MISSION_CONFIG)
    an = _ANOMALY_DETECTOR.score(input.payload)
    cl = _CLASSIFIER.score(input.payload)

    subscores = DetectorSubscores(rule_based=rb[0], anomaly=an, classifier=cl)
    verdict, reason = aggregate(subscores, _RULES)

    latency_ms = (time.perf_counter() - t0) * 1000.0

    return ScreenResult(
        verdict=verdict,
        subscores=subscores,
        explanation={
            "reason": reason,
            "rule_based_triggers": rb[1],
            "source": source.value,
            "input_id": input.input_id,
        },
        latency_ms=latency_ms,
    )
