# Institute Perimeter

Adversarial input detector for research institute directives, hypotheses, and dataset upload metadata.

Three detectors run in parallel and feed an aggregator that produces a verdict (`ALLOW` / `REVIEW` / `BLOCK`):

1. **Rule-based** — regex/phrase match against banned outcomes, banned directive phrases, goal-corruption phrases, and priority-injection patterns from `config/mission.json`.
2. **Anomaly** — Mahalanobis distance on MiniLM sentence embeddings against a benign-only training distribution (Ledoit-Wolf shrinkage covariance).
3. **Classifier** — Logistic regression on MiniLM embeddings, trained on benign vs adversarial corpus.

Aggregation rules live in `config/aggregation.yaml` (top-down, first match wins, no `eval()`).

See the root `README.md` for the original write-up and `DOCS_V2.md` for the clean-methodology rerun (recommended).

## Quickstart

```bash
pip install -r requirements.txt
```

### Original pipeline (root README.md — known leakage)

```bash
python -m institute_perimeter.training.train
pytest institute_perimeter/tests/ -v
python -m institute_perimeter.evaluation.evaluate
```

### Clean-methodology pipeline (DOCS_V2.md — recommended)

Removes 13 duplicate corpus rows, uses a 70/10/20 stratified split with a
dedicated val set for threshold tuning, retrains anomaly + classifier on
train only, evaluates test exactly once.

```bash
# 1. Dedup corpus (one-shot; writes training/corpus_clean.csv)
python -c "import pandas as pd; df = pd.read_csv('institute_perimeter/training/corpus.csv'); df.drop_duplicates(subset=['payload'], keep='first').to_csv('institute_perimeter/training/corpus_clean.csv', index=False)"

# 2. Run clean rerun: fits anomaly_v2.pkl + classifier_v2.pkl, tunes
#    thresholds on val, evaluates test once, writes evaluation/methodology_report.{md,json}
python -m institute_perimeter.evaluation.methodology_rerun

# 3. Score 30 held-out probes through the v2 model + val-tuned policy
python -m institute_perimeter.evaluation.probe_scoring
```

Outputs:
- `evaluation/methodology_report.md` — clean test metrics + delta vs reported numbers
- `evaluation/probe_report.md` — per-probe verdicts, per-detector subscores, per-category pass rates
- `evaluation/probes.csv` — 30 held-out probe definitions

Targets: FP rate < 5%, recall > 90%, p99 latency < 500ms.

Headline under clean methodology: FP **3.23%**, recall **86.67%**
(recall CI lower bound 73.33%). Below target on recall — see DOCS_V2.md
for the honest reading and the gap categories surfaced.

## Layout

```
institute_perimeter/
  models.py                  # dataclasses + enums
  screen.py                  # screen(input, source) -> ScreenResult
  aggregator.py              # YAML rule evaluator (no eval())
  detectors/
    rule_based.py
    anomaly.py               # MahalanobisAnomalyDetector (Ledoit-Wolf)
    classifier.py            # AdversarialClassifier (LogReg on MiniLM)
    _embedder.py             # shared MiniLM singleton
  config/
    mission.json
    aggregation.yaml
  training/
    corpus.csv               # 315 rows
    corpus_clean.csv         # 302 rows (post-dedup, generated)
    train.py                 # original 80/20 split
  artifacts/                 # gitignored
    anomaly.pkl, classifier.pkl, test_split.csv          (original)
    anomaly_v2.pkl, classifier_v2.pkl                    (clean rerun)
    train_split.csv, val_split.csv, test_split_v2.csv    (clean splits)
  evaluation/
    evaluate.py              # original eval (uses artifacts/test_split.csv)
    methodology_rerun.py     # clean-methodology train + eval
    probe_scoring.py         # 30-probe held-out scoring
    probes.csv               # probe definitions
    methodology_report.md    # clean rerun results
    probe_report.md          # probe results
  tests/test_screen.py
```

## Reproducibility

Both pipelines pin `random_state=42` for splits and bootstrap. The val-tuned
operating point from the clean rerun is `anomaly_thr=0.75, cls_conj=0.50,
cls_med=0.55` — enforced in code inside `methodology_rerun.py` and
`probe_scoring.py`. The deployed YAML in `config/aggregation.yaml` still
uses the original (test-tuned) thresholds; updating it to the val-tuned
operating point is left as a deployment decision.
