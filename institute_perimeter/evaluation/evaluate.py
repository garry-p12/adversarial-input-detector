import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import institute_perimeter.screen as screen_mod
from institute_perimeter.detectors.anomaly import MahalanobisAnomalyDetector
from institute_perimeter.detectors.classifier import AdversarialClassifier
from institute_perimeter.models import InstituteInput, InputSource, Verdict
from institute_perimeter.screen import screen


_PKG_ROOT = Path(__file__).resolve().parent.parent
_TEST_SPLIT_PATH = _PKG_ROOT / "artifacts" / "test_split.csv"
_REPORT_PATH = _PKG_ROOT / "evaluation" / "report.json"
_V2_TEST_SPLIT_PATH = _PKG_ROOT / "artifacts" / "test_split_v2.csv"
_V2_ANOMALY_PATH = _PKG_ROOT / "artifacts" / "anomaly_v2.pkl"
_V2_CLASSIFIER_PATH = _PKG_ROOT / "artifacts" / "classifier_v2.pkl"
_V2_REPORT_PATH = _PKG_ROOT / "evaluation" / "report_v2.json"
_V2_RULES_PATH = _PKG_ROOT / "config" / "aggregation_v2.yaml"


def _activate_v2():
    """Force screen() to use v2 artifacts + val-tuned aggregation rules."""
    from institute_perimeter.aggregator import load_rules
    anomaly = MahalanobisAnomalyDetector()
    anomaly.load(str(_V2_ANOMALY_PATH))
    clf = AdversarialClassifier()
    clf.load(str(_V2_CLASSIFIER_PATH))
    screen_mod._lazy_load()
    screen_mod._ANOMALY_DETECTOR = anomaly
    screen_mod._CLASSIFIER = clf
    screen_mod._RULES = load_rules(str(_V2_RULES_PATH))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2", action="store_true",
                        help="Use v2 artifacts (clean-methodology rerun): test_split_v2.csv, anomaly_v2.pkl, classifier_v2.pkl")
    args = parser.parse_args()

    test_path = _V2_TEST_SPLIT_PATH if args.v2 else _TEST_SPLIT_PATH
    report_path = _V2_REPORT_PATH if args.v2 else _REPORT_PATH

    if args.v2:
        _activate_v2()
        print(f"[v2 mode] Using {test_path.name}, anomaly_v2.pkl, classifier_v2.pkl")

    df = pd.read_csv(test_path)

    # Warm-up call (not measured)
    screen(InstituteInput(payload="warmup hypothesis about senolytics in aged mice"), InputSource.INTERNAL)

    rows = []
    for _, r in df.iterrows():
        result = screen(InstituteInput(payload=str(r["payload"])), InputSource.INTERNAL)
        rows.append({
            "id": int(r["id"]),
            "label": r["label"],
            "verdict": result.verdict.value,
            "rule_based": result.subscores.rule_based,
            "anomaly": result.subscores.anomaly,
            "classifier": result.subscores.classifier,
            "latency_ms": result.latency_ms,
        })

    rdf = pd.DataFrame(rows)

    benign = rdf[rdf.label == "benign"]
    adv = rdf[rdf.label == "adversarial"]

    fp_rate = float((benign.verdict != "ALLOW").sum() / max(len(benign), 1))
    recall = float((adv.verdict != "ALLOW").sum() / max(len(adv), 1))

    # Bootstrap 95% CIs (1000 resamples)
    rng = np.random.default_rng(42)
    n_boot = 1000
    benign_flag = (benign.verdict != "ALLOW").to_numpy().astype(int)
    adv_flag = (adv.verdict != "ALLOW").to_numpy().astype(int)

    def _boot_ci(arr):
        if len(arr) == 0:
            return (0.0, 0.0)
        samples = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
        return (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))

    fp_ci = _boot_ci(benign_flag)
    rec_ci = _boot_ci(adv_flag)

    lat = rdf["latency_ms"].to_numpy()
    p50 = float(np.percentile(lat, 50))
    p95 = float(np.percentile(lat, 95))
    p99 = float(np.percentile(lat, 99))

    fp_ok = fp_rate < 0.05
    rec_ok = recall > 0.90
    lat_ok = p99 < 500.0

    def mark(b):
        return "✓" if b else "✗"

    breakdown = {
        v: {
            "benign": int(((rdf.label == "benign") & (rdf.verdict == v)).sum()),
            "adversarial": int(((rdf.label == "adversarial") & (rdf.verdict == v)).sum()),
        }
        for v in ["ALLOW", "REVIEW", "BLOCK"]
    }

    print("==============================")
    print("  INSTITUTE PERIMETER — EVALUATION REPORT")
    print("==============================")
    print(f"Benign examples:      {len(benign)}")
    print(f"Adversarial examples: {len(adv)}")
    print()
    print(f"False Positive Rate:  {fp_rate * 100:.2f}%   95% CI [{fp_ci[0]*100:.2f}%, {fp_ci[1]*100:.2f}%]   [target: < 5.00%]   {mark(fp_ok)}")
    print(f"Recall:               {recall * 100:.2f}%  95% CI [{rec_ci[0]*100:.2f}%, {rec_ci[1]*100:.2f}%]   [target: > 90.00%]   {mark(rec_ok)}")
    print()
    print("Latency (ms):")
    print(f"  p50:  {p50:.1f}")
    print(f"  p95:  {p95:.1f}")
    print(f"  p99:  {p99:.1f}  [target: < 500ms]  {mark(lat_ok)}")
    print()
    print("Per-class breakdown:")
    for v in ["ALLOW", "REVIEW", "BLOCK"]:
        print(f"  {v:<7} {breakdown[v]['benign']} benign, {breakdown[v]['adversarial']} adversarial")
    print("==============================")

    report = {
        "n_benign": int(len(benign)),
        "n_adversarial": int(len(adv)),
        "false_positive_rate": fp_rate,
        "false_positive_rate_ci95": list(fp_ci),
        "recall": recall,
        "recall_ci95": list(rec_ci),
        "latency_ms": {"p50": p50, "p95": p95, "p99": p99},
        "targets": {"fp_rate_lt_0.05": fp_ok, "recall_gt_0.90": rec_ok, "p99_lt_500ms": lat_ok},
        "breakdown": breakdown,
        "rows": rows,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
