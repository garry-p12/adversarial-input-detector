"""
Score the 30 held-out probes through the v2 retrained model + tuned policy.

Uses v2 artifacts (anomaly_v2.pkl, classifier_v2.pkl) and the val-tuned
operating point from methodology_rerun.py:
  anomaly_thr=0.75, cls_conj=0.50, cls_med=0.55.

Emits per-detector subscore table + classifier-only-catch audit.
"""

import json
from pathlib import Path

import pandas as pd

from institute_perimeter.detectors.anomaly import MahalanobisAnomalyDetector
from institute_perimeter.detectors.classifier import AdversarialClassifier
from institute_perimeter.detectors.rule_based import score as rb_score

PKG = Path(__file__).resolve().parent.parent
PROBES = PKG / "evaluation" / "probes.csv"
ART = PKG / "artifacts"
REPORT = PKG / "evaluation" / "probe_report.md"

# v2 tuned operating point (from methodology_rerun.py, chosen on val)
ANOM_THR = 0.75
CLS_CONJ = 0.50
CLS_MED = 0.55


def apply_policy(rb, an, cl):
    if cl >= 0.90:
        return "BLOCK", "hard_block_classifier"
    if rb >= 0.60 and cl >= 0.50:
        return "BLOCK", "hard_block_rule_plus_classifier"
    if rb >= 0.40 and an >= 0.60 and cl >= 0.50:
        return "BLOCK", "block_all_three_medium"
    if an >= ANOM_THR and cl >= CLS_CONJ:
        return "REVIEW", "review_anomaly_plus_classifier"
    if rb >= 0.50:
        return "REVIEW", "review_rule_based_alone"
    if cl >= CLS_MED:
        return "REVIEW", "review_classifier_medium"
    return "ALLOW", "default_allow"


def main():
    probes = pd.read_csv(PROBES)
    with open(PKG / "config" / "mission.json") as f:
        mission = json.load(f)

    anomaly = MahalanobisAnomalyDetector()
    anomaly.load(str(ART / "anomaly_v2.pkl"))
    clf = AdversarialClassifier()
    clf.load(str(ART / "classifier_v2.pkl"))

    rows = []
    for _, r in probes.iterrows():
        payload = str(r["payload"])
        rb, triggers = rb_score(payload, {}, mission)
        an = anomaly.score(payload)
        cl = clf.score(payload)
        verdict, rule = apply_policy(rb, an, cl)
        expected_flag = r["expected"] == "adversarial"
        actual_flag = verdict != "ALLOW"
        passed = expected_flag == actual_flag
        rows.append({
            "probe_id": r["probe_id"],
            "category": r["category"],
            "expected": r["expected"],
            "rule_based": round(rb, 3),
            "anomaly": round(an, 3),
            "classifier": round(cl, 3),
            "verdict": verdict,
            "rule_fired": rule,
            "pass": passed,
            "payload": payload,
            "rb_triggers": "; ".join(triggers) if triggers else "",
        })

    df = pd.DataFrame(rows)
    df.to_csv(PKG / "evaluation" / "probe_results.csv", index=False)

    adv = df[df.expected == "adversarial"]
    ben = df[df.expected == "benign"]
    adv_catch = (adv["pass"]).sum()
    ben_correct = (ben["pass"]).sum()
    overall_pass = (df["pass"]).sum()

    # Classifier-only catches (no rb hit, anomaly+classifier conjunction or classifier-medium)
    cls_only_catch = adv[(adv.rule_based == 0.0) & (adv["pass"])]
    rb_only_catch = adv[(adv.rule_based >= 0.5) & (adv.classifier < CLS_CONJ) & (adv["pass"])]
    missed_adv = adv[~adv["pass"]]
    false_pos = ben[~ben["pass"]]

    md = []
    md.append("# Probe scoring (v2 model + val-tuned policy)\n")
    md.append(f"- Model: retrained on dedup corpus, train-only fit (artifacts `*_v2.pkl`)")
    md.append(f"- Policy: `anomaly_thr={ANOM_THR}`, `cls_conj={CLS_CONJ}`, `cls_med={CLS_MED}`")
    md.append(f"- Probes: {len(df)} total ({len(adv)} adversarial, {len(ben)} benign)")
    md.append("")
    md.append("## Headline")
    md.append(f"- Overall pass: **{overall_pass}/{len(df)}** ({overall_pass/len(df)*100:.1f}%)")
    md.append(f"- Adversarial caught (not-ALLOW): **{adv_catch}/{len(adv)}** ({adv_catch/len(adv)*100:.1f}%)")
    md.append(f"- Benign allowed: **{ben_correct}/{len(ben)}** ({ben_correct/len(ben)*100:.1f}%)")
    md.append(f"- Embedding-stack catches (rb=0 adversarials caught): **{len(cls_only_catch)}** — measures whether classifier/anomaly does real work")
    md.append(f"- Rule-only catches (rb≥0.5, cl<{CLS_CONJ}, caught): **{len(rb_only_catch)}**")
    md.append("")
    md.append("## Per-probe table\n")
    md.append("| id | category | expected | rb | an | cl | verdict | rule | pass |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in df.iterrows():
        md.append(f"| {r.probe_id} | {r.category} | {r.expected} | {r.rule_based} | {r.anomaly} | {r.classifier} | {r.verdict} | {r.rule_fired} | {'✓' if r['pass'] else '✗'} |")
    md.append("")

    md.append("## Failures\n")
    if len(missed_adv) == 0 and len(false_pos) == 0:
        md.append("_None._")
    else:
        if len(missed_adv):
            md.append("### Missed adversarial probes (FN)\n")
            md.append("| id | category | rb | an | cl | payload |")
            md.append("|---|---|---|---|---|---|")
            for _, r in missed_adv.iterrows():
                md.append(f"| {r.probe_id} | {r.category} | {r.rule_based} | {r.anomaly} | {r.classifier} | {r.payload[:80]} |")
            md.append("")
        if len(false_pos):
            md.append("### False positives on benign probes\n")
            md.append("| id | category | rb | an | cl | verdict | rule | payload |")
            md.append("|---|---|---|---|---|---|---|")
            for _, r in false_pos.iterrows():
                md.append(f"| {r.probe_id} | {r.category} | {r.rule_based} | {r.anomaly} | {r.classifier} | {r.verdict} | {r.rule_fired} | {r.payload[:80]} |")
            md.append("")

    md.append("## By-category breakdown\n")
    md.append("| category | n | pass | adv_caught_by_embedding (rb=0) |")
    md.append("|---|---|---|---|")
    for cat, grp in df.groupby("category"):
        n = len(grp)
        p = grp["pass"].sum()
        emb = ((grp.expected == "adversarial") & (grp.rule_based == 0.0) & (grp["pass"])).sum()
        md.append(f"| {cat} | {n} | {p}/{n} | {emb} |")

    REPORT.write_text("\n".join(md))
    print(f"Report -> {REPORT}")
    print(f"Adv catch: {adv_catch}/{len(adv)}, benign correct: {ben_correct}/{len(ben)}, embedding catches: {len(cls_only_catch)}")


if __name__ == "__main__":
    main()
