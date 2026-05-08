# Institute Perimeter

Adversarial input detector for research institute directives, hypotheses, and dataset upload metadata.

Three detectors run in parallel and feed an aggregator that produces a verdict (`ALLOW` / `REVIEW` / `BLOCK`):

1. **Rule-based** — regex/phrase match against banned outcomes, banned directive phrases, goal-corruption phrases, and priority-injection patterns from `config/mission.json`.
2. **Anomaly** — Mahalanobis distance on MiniLM sentence embeddings against a benign-only training distribution.
3. **Classifier** — Logistic regression on MiniLM embeddings, trained on benign vs adversarial corpus.

Aggregation rules live in `config/aggregation.yaml` (top-down, first match wins).

## Quickstart

```bash
pip install -r requirements.txt
python -m institute_perimeter.training.train
pytest institute_perimeter/tests/ -v
python -m institute_perimeter.evaluation.evaluate
```

Targets: FP rate < 5%, recall > 90%, p99 latency < 500ms.

## Layout

```
institute_perimeter/
  models.py            # dataclasses + enums
  screen.py            # screen(input, source) -> ScreenResult
  aggregator.py        # YAML rule evaluator (no eval())
  detectors/
    rule_based.py
    anomaly.py         # MahalanobisAnomalyDetector
    classifier.py      # AdversarialClassifier
    _embedder.py       # shared MiniLM singleton
  config/
    mission.json
    aggregation.yaml
  training/{corpus.csv, train.py}
  artifacts/           # populated by train.py
  evaluation/evaluate.py
  tests/test_screen.py
```
