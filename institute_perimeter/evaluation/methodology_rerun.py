"""
Clean-methodology rerun.

- Loads deduplicated corpus (corpus_clean.csv).
- 70/10/20 stratified split on (label, attack_type), seed=42.
- Fits anomaly on benign-train only; classifier on train only.
- Tunes (anomaly_thr, classifier_conj_thr, classifier_med_thr) on val by max-F1
  with FP <= 5% soft preference. Test set is touched exactly once at end.
- Bootstrap CI on FP and recall.
- Writes evaluation/methodology_report.md.
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from institute_perimeter.detectors.anomaly import MahalanobisAnomalyDetector
from institute_perimeter.detectors.classifier import AdversarialClassifier
from institute_perimeter.detectors.rule_based import score as rule_based_score


def _load_mission():
    with open(PKG / "config" / "mission.json", "r") as f:
        return json.load(f)

PKG = Path(__file__).resolve().parent.parent
CORPUS = PKG / "training" / "corpus_clean.csv"
ARTIFACTS = PKG / "artifacts"
REPORT_MD = PKG / "evaluation" / "methodology_report.md"
REPORT_JSON = PKG / "evaluation" / "methodology_report.json"

SEED = 42
TRAIN_FRAC = 0.70
VAL_FRAC = 0.10
TEST_FRAC = 0.20  # noqa
N_BOOT = 1000


def stratified_split(df: pd.DataFrame, seed: int):
    df = df.copy()
    df["_strat"] = df["label"].astype(str) + "|" + df["attack_type"].astype(str)
    # First carve test (20%), then split remainder into train (70/80) and val (10/80).
    train_val, test = train_test_split(
        df, test_size=0.20, stratify=df["_strat"], random_state=seed
    )
    val_rel = 0.10 / 0.80  # 12.5% of remainder = 10% of total
    train, val = train_test_split(
        train_val, test_size=val_rel, stratify=train_val["_strat"], random_state=seed
    )
    return (
        train.drop(columns=["_strat"]).reset_index(drop=True),
        val.drop(columns=["_strat"]).reset_index(drop=True),
        test.drop(columns=["_strat"]).reset_index(drop=True),
    )


def score_rows(df: pd.DataFrame, anomaly: MahalanobisAnomalyDetector, clf: AdversarialClassifier, mission):
    out = []
    for _, r in df.iterrows():
        payload = str(r["payload"])
        rb, _ = rule_based_score(payload, {}, mission)
        an = anomaly.score(payload)
        cl = clf.score(payload)
        out.append({"id": int(r["id"]), "label": r["label"], "attack_type": r["attack_type"],
                    "payload": payload, "rule_based": rb, "anomaly": an, "classifier": cl})
    return pd.DataFrame(out)


def apply_policy(scored: pd.DataFrame, anom_thr: float, cls_conj: float, cls_med: float,
                 cls_hard: float = 0.90, rb_block: float = 0.60, cls_block: float = 0.50,
                 rb_review: float = 0.50, block_all_three_rb: float = 0.40,
                 block_all_three_an: float = 0.60, block_all_three_cls: float = 0.50):
    verdicts, rules = [], []
    for _, r in scored.iterrows():
        rb, an, cl = r["rule_based"], r["anomaly"], r["classifier"]
        if cl >= cls_hard:
            v, rule = "BLOCK", "hard_block_classifier"
        elif rb >= rb_block and cl >= cls_block:
            v, rule = "BLOCK", "hard_block_rule_plus_classifier"
        elif rb >= block_all_three_rb and an >= block_all_three_an and cl >= block_all_three_cls:
            v, rule = "BLOCK", "block_all_three_medium"
        elif an >= anom_thr and cl >= cls_conj:
            v, rule = "REVIEW", "review_anomaly_plus_classifier"
        elif rb >= rb_review:
            v, rule = "REVIEW", "review_rule_based_alone"
        elif cl >= cls_med:
            v, rule = "REVIEW", "review_classifier_medium"
        else:
            v, rule = "ALLOW", "default_allow"
        verdicts.append(v)
        rules.append(rule)
    out = scored.copy()
    out["verdict"] = verdicts
    out["rule_fired"] = rules
    return out


def metrics(df: pd.DataFrame):
    benign = df[df.label == "benign"]
    adv = df[df.label == "adversarial"]
    fp = (benign.verdict != "ALLOW").sum() / max(len(benign), 1)
    rec = (adv.verdict != "ALLOW").sum() / max(len(adv), 1)
    return float(fp), float(rec), len(benign), len(adv)


def bootstrap_ci(arr, n_boot=N_BOOT, seed=SEED):
    if len(arr) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    samples = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))


def tune_thresholds(val_scored: pd.DataFrame):
    """Grid search on val. Objective: max F1 (treating not-ALLOW as positive),
    constraint: prefer configs with val FP <= 5% (1/n_benign granularity)."""
    anom_grid = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    cls_conj_grid = [0.40, 0.45, 0.47, 0.50, 0.55, 0.60]
    cls_med_grid = [0.55, 0.60, 0.65, 0.70, 0.75]

    rows = []
    for a in anom_grid:
        for cc in cls_conj_grid:
            for cm in cls_med_grid:
                policied = apply_policy(val_scored, a, cc, cm)
                fp, rec, _, _ = metrics(policied)
                # f1 over not-ALLOW vs ALLOW
                tp = ((policied.label == "adversarial") & (policied.verdict != "ALLOW")).sum()
                fp_n = ((policied.label == "benign") & (policied.verdict != "ALLOW")).sum()
                fn = ((policied.label == "adversarial") & (policied.verdict == "ALLOW")).sum()
                prec = tp / max(tp + fp_n, 1)
                recl = tp / max(tp + fn, 1)
                f1 = 2 * prec * recl / max(prec + recl, 1e-9)
                rows.append({"anom_thr": a, "cls_conj": cc, "cls_med": cm,
                             "val_fp": fp, "val_recall": rec, "val_f1": f1})
    grid = pd.DataFrame(rows)

    # Prefer FP <= 0.05; among those, max F1; tiebreak max recall, then higher anom_thr.
    feasible = grid[grid.val_fp <= 0.05]
    if len(feasible) == 0:
        feasible = grid  # fallback if val too noisy
    best = feasible.sort_values(["val_f1", "val_recall", "anom_thr"], ascending=[False, False, False]).iloc[0]
    return best, grid


def anomaly_contribution(test_policied: pd.DataFrame, anom_thr: float, cls_conj: float):
    """Counts test adv rows whose REVIEW/BLOCK verdict depended on the anomaly+classifier
    conjunction (rule_fired == review_anomaly_plus_classifier AND no other rule would have fired)."""
    n_depends = 0
    for _, r in test_policied.iterrows():
        if r.label != "adversarial" or r.verdict == "ALLOW":
            continue
        rb, an, cl = r.rule_based, r.anomaly, r.classifier
        # Would any of the rules above the conj rule fire?
        if cl >= 0.90:
            continue
        if rb >= 0.60 and cl >= 0.50:
            continue
        if rb >= 0.40 and an >= 0.60 and cl >= 0.50:
            continue
        conj_fires = (an >= anom_thr) and (cl >= cls_conj)
        rb_alone = rb >= 0.50
        cls_med_alone = cl >= 0.65  # placeholder; actual cls_med passed elsewhere
        # If conj fires and neither alternative would
        if conj_fires and not rb_alone:
            n_depends += 1
    return n_depends


def main():
    df = pd.read_csv(CORPUS)
    print(f"Corpus: {len(df)} rows, benign={int((df.label=='benign').sum())}, adv={int((df.label=='adversarial').sum())}")

    train, val, test = stratified_split(df, SEED)
    print(f"Split: train={len(train)}, val={len(val)}, test={len(test)}")
    print(f"  train benign/adv: {int((train.label=='benign').sum())}/{int((train.label=='adversarial').sum())}")
    print(f"  val   benign/adv: {int((val.label=='benign').sum())}/{int((val.label=='adversarial').sum())}")
    print(f"  test  benign/adv: {int((test.label=='benign').sum())}/{int((test.label=='adversarial').sum())}")

    # Persist splits for audit
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    train.to_csv(ARTIFACTS / "train_split.csv", index=False)
    val.to_csv(ARTIFACTS / "val_split.csv", index=False)
    test.to_csv(ARTIFACTS / "test_split_v2.csv", index=False)

    benign_train = train[train.label == "benign"]["payload"].tolist()
    print(f"Fitting anomaly on {len(benign_train)} benign-train rows...")
    anomaly = MahalanobisAnomalyDetector()
    anomaly.fit(benign_train)
    anomaly.save(str(ARTIFACTS / "anomaly_v2.pkl"))

    payloads = train["payload"].tolist()
    labels = (train["label"] == "adversarial").astype(int).tolist()
    print(f"Fitting classifier on {len(payloads)} train rows...")
    clf = AdversarialClassifier()
    clf.fit(payloads, labels)
    clf.save(str(ARTIFACTS / "classifier_v2.pkl"))

    mission = _load_mission()

    print("Scoring val...")
    val_scored = score_rows(val, anomaly, clf, mission)
    print("Tuning thresholds on val...")
    best, grid = tune_thresholds(val_scored)
    print(f"Selected: anom_thr={best.anom_thr}, cls_conj={best.cls_conj}, cls_med={best.cls_med}")
    print(f"  val: fp={best.val_fp:.4f}, recall={best.val_recall:.4f}, f1={best.val_f1:.4f}")

    print("Scoring test (final, single pass)...")
    test_scored = score_rows(test, anomaly, clf, mission)
    # Latency: time per row
    lats = []
    for p in test_scored.payload.tolist()[:1]:  # warmup
        _ = anomaly.score(p); _ = clf.score(p)
    for p in test_scored.payload.tolist():
        t0 = time.perf_counter()
        _ = rule_based_score(p, {}, mission); _ = anomaly.score(p); _ = clf.score(p)
        lats.append((time.perf_counter() - t0) * 1000)
    test_policied = apply_policy(test_scored, best.anom_thr, best.cls_conj, best.cls_med)

    fp, rec, n_b, n_a = metrics(test_policied)
    fp_flag = (test_policied[test_policied.label == "benign"].verdict != "ALLOW").to_numpy().astype(int)
    rec_flag = (test_policied[test_policied.label == "adversarial"].verdict != "ALLOW").to_numpy().astype(int)
    fp_ci = bootstrap_ci(fp_flag)
    rec_ci = bootstrap_ci(rec_flag)

    p50, p95, p99 = (float(np.percentile(lats, q)) for q in (50, 95, 99))

    # Per-rule firing
    rule_counts = test_policied.groupby(["label", "rule_fired"]).size().unstack(fill_value=0)

    # Anomaly contribution audit
    anom_depend = 0
    for _, r in test_policied.iterrows():
        if r.label != "adversarial" or r.verdict == "ALLOW":
            continue
        if r.classifier >= 0.90:  # hard_block_classifier
            continue
        if r.rule_based >= 0.60 and r.classifier >= 0.50:
            continue
        if r.rule_based >= 0.40 and r.anomaly >= 0.60 and r.classifier >= 0.50:
            continue
        conj = (r.anomaly >= best.anom_thr) and (r.classifier >= best.cls_conj)
        rb_alone = r.rule_based >= 0.50
        cls_med_alone = r.classifier >= best.cls_med
        if conj and not (rb_alone or cls_med_alone):
            anom_depend += 1

    # Adv missed
    missed = test_policied[(test_policied.label == "adversarial") & (test_policied.verdict == "ALLOW")]
    # Benign false-positives
    fps = test_policied[(test_policied.label == "benign") & (test_policied.verdict != "ALLOW")]

    # Old (reported) numbers for delta
    OLD = {"fp_rate": 0.0323, "fp_ci": (0.0, 0.0968), "recall": 0.9688,
           "recall_ci": (0.9062, 1.0), "p50": 14.7, "p95": 53.6, "p99": 66.2,
           "n_benign": 31, "n_adv": 32}

    report = {
        "seed": SEED,
        "corpus_after_dedup": len(df),
        "split": {"train": len(train), "val": len(val), "test": len(test)},
        "tuned_thresholds": {"anomaly": float(best.anom_thr),
                             "classifier_conj": float(best.cls_conj),
                             "classifier_med": float(best.cls_med)},
        "val_metrics": {"fp": float(best.val_fp), "recall": float(best.val_recall),
                        "f1": float(best.val_f1)},
        "test_metrics": {
            "n_benign": int(n_b), "n_adversarial": int(n_a),
            "fp_rate": fp, "fp_ci95": list(fp_ci),
            "recall": rec, "recall_ci95": list(rec_ci),
            "latency_ms": {"p50": p50, "p95": p95, "p99": p99},
        },
        "delta_vs_reported": {
            "fp_rate_delta_pp": (fp - OLD["fp_rate"]) * 100,
            "recall_delta_pp": (rec - OLD["recall"]) * 100,
        },
        "anomaly_dependence_count": int(anom_depend),
        "rule_firing": rule_counts.to_dict() if hasattr(rule_counts, "to_dict") else {},
        "missed_adversarials": missed[["id", "attack_type", "rule_based", "anomaly", "classifier", "payload"]].to_dict(orient="records"),
        "benign_false_positives": fps[["id", "input_type" if "input_type" in fps.columns else "attack_type", "rule_based", "anomaly", "classifier", "verdict", "rule_fired", "payload"]].to_dict(orient="records") if len(fps) else [],
    }
    with open(REPORT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"JSON report -> {REPORT_JSON}")

    # Markdown report
    md = []
    md.append("# Clean-methodology rerun\n")
    md.append(f"- Seed: `{SEED}`")
    md.append(f"- Corpus after dedup: {len(df)} rows (was 315, removed 13 dup payloads)")
    md.append(f"- Stratified by `(label, attack_type)`. Splits — train: {len(train)}, val: {len(val)}, test: {len(test)}")
    md.append("")
    md.append("## Tuned operating point (chosen on val, max-F1 with FP≤5% preference)")
    md.append(f"- `anomaly_thr` = **{best.anom_thr}**  (was 0.65)")
    md.append(f"- `classifier_conj` = **{best.cls_conj}**  (was 0.47)")
    md.append(f"- `classifier_med` = **{best.cls_med}**  (was 0.65)")
    md.append(f"- Val: fp={best.val_fp:.4f}, recall={best.val_recall:.4f}, f1={best.val_f1:.4f}")
    md.append("")
    md.append("## Test set (touched once)")
    md.append("| Metric | Old (reported) | New (clean) | Delta |")
    md.append("|---|---|---|---|")
    md.append(f"| n_benign | {OLD['n_benign']} | {n_b} | — |")
    md.append(f"| n_adv | {OLD['n_adv']} | {n_a} | — |")
    md.append(f"| FP rate | {OLD['fp_rate']*100:.2f}% | {fp*100:.2f}% | {(fp-OLD['fp_rate'])*100:+.2f} pp |")
    md.append(f"| FP 95% CI | [{OLD['fp_ci'][0]*100:.2f}%, {OLD['fp_ci'][1]*100:.2f}%] | [{fp_ci[0]*100:.2f}%, {fp_ci[1]*100:.2f}%] | — |")
    md.append(f"| Recall | {OLD['recall']*100:.2f}% | {rec*100:.2f}% | {(rec-OLD['recall'])*100:+.2f} pp |")
    md.append(f"| Recall 95% CI | [{OLD['recall_ci'][0]*100:.2f}%, {OLD['recall_ci'][1]*100:.2f}%] | [{rec_ci[0]*100:.2f}%, {rec_ci[1]*100:.2f}%] | — |")
    md.append(f"| Latency p50/p95/p99 (ms) | {OLD['p50']}/{OLD['p95']}/{OLD['p99']} | {p50:.1f}/{p95:.1f}/{p99:.1f} | — |")
    md.append("")
    md.append(f"## Anomaly contribution audit\n")
    md.append(f"Test adversarials where the anomaly+classifier conjunction was load-bearing "
              f"(no other rule would have fired): **{anom_depend}** / {n_a}")
    md.append("")
    md.append("## Missed adversarials (FN)\n")
    if len(missed) == 0:
        md.append("_None._")
    else:
        md.append("| id | attack_type | rb | an | cl | payload |")
        md.append("|---|---|---|---|---|---|")
        for _, r in missed.iterrows():
            md.append(f"| {r.id} | {r.attack_type} | {r.rule_based:.2f} | {r.anomaly:.2f} | {r.classifier:.2f} | {r.payload[:90]} |")
    md.append("")
    md.append("## Benign false positives\n")
    if len(fps) == 0:
        md.append("_None._")
    else:
        md.append("| id | rb | an | cl | verdict | rule | payload |")
        md.append("|---|---|---|---|---|---|---|")
        for _, r in fps.iterrows():
            md.append(f"| {r.id} | {r.rule_based:.2f} | {r.anomaly:.2f} | {r.classifier:.2f} | {r.verdict} | {r.rule_fired} | {r.payload[:80]} |")
    md.append("")
    with open(REPORT_MD, "w") as f:
        f.write("\n".join(md))
    print(f"Markdown report -> {REPORT_MD}")


if __name__ == "__main__":
    main()
