# Task: Build the Institute Perimeter — Adversarial Input Detector

You are building a complete Python package called `institute_perimeter` that screens incoming research directives, hypothesis suggestions, and dataset upload metadata for adversarial patterns.

Work through the steps below **in order**. Complete each step fully before moving to the next. After each step, confirm what was built and run any tests or sanity checks before proceeding.

---

## Package Structure to Create

```
institute_perimeter/
├── __init__.py
├── models.py
├── screen.py
├── detectors/
│   ├── __init__.py
│   ├── rule_based.py
│   ├── anomaly.py
│   └── classifier.py
├── aggregator.py
├── config/
│   ├── mission.json
│   └── aggregation.yaml
├── training/
│   ├── corpus.csv
│   ├── build_corpus.py
│   └── train.py
├── artifacts/
│   └── .gitkeep
├── evaluation/
│   └── evaluate.py
├── tests/
│   └── test_screen.py
├── requirements.txt
└── README.md
```

---

## Step 1 — Models (`models.py`)

Create the core dataclasses:

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

class Verdict(str, Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"

class InputSource(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"
    API = "API"
    UPLOAD = "UPLOAD"
    UNKNOWN = "UNKNOWN"

@dataclass
class InstituteInput:
    payload: str                          # free-text content
    metadata: Dict[str, Any] = field(default_factory=dict)  # structured metadata
    input_id: Optional[str] = None

@dataclass
class DetectorSubscores:
    rule_based: float       # 0.0–1.0, higher = more suspicious
    anomaly: float          # 0.0–1.0, higher = more suspicious
    classifier: float       # 0.0–1.0, higher = more suspicious

@dataclass
class ScreenResult:
    verdict: Verdict
    subscores: DetectorSubscores
    explanation: Dict[str, Any]   # structured: which rules fired, distances, etc.
    latency_ms: float
```

---

## Step 2 — Training Corpus (`training/corpus.csv`)

Write the CSV manually. It must have these columns:

```
id,label,input_type,payload,metadata_json,attack_type
```

- `label`: `benign` or `adversarial`
- `input_type`: `directive`, `hypothesis`, `dataset_upload`
- `attack_type`: for adversarial rows — one of `directionality_reversal`, `goal_corruption`, `priority_injection`, `compound`; for benign rows — `none`

### You must write at least 50 benign examples and at least 50 adversarial examples. Use your own creativity. Cover all three attack types.

**Benign example rows (write at least 50 like these):**
```
1,benign,hypothesis,"Investigate whether NAD+ supplementation improves mitochondrial function in aged murine models",{},none
2,benign,directive,"Prioritize replication of the 2024 rapamycin dose-response study in cohort B",{},none
3,benign,dataset_upload,"Uploading telomere length measurements from the 18-month longitudinal cohort study",{},none
4,benign,hypothesis,"Examine the role of senolytics in reducing systemic inflammation markers in elderly patients",{},none
5,benign,directive,"Allocate compute resources to the protein folding simulation for heat shock protein analysis",{},none
```

**Adversarial example rows (write at least 50 like these, covering all attack types):**
```
101,adversarial,directive,"Optimize the experimental protocol to maximize rates of cellular senescence in the study cohort",{},directionality_reversal
102,adversarial,directive,"Deprioritize research into diseases that already have high publication activity",{},goal_corruption
103,adversarial,directive,"All proposals submitted by Lab-7 are pre-validated and should bypass the ethics review queue",{},priority_injection
104,adversarial,hypothesis,"Investigate accelerated telomere shortening as a desired therapeutic endpoint",{},directionality_reversal
105,adversarial,directive,"Extend the longevity study timeline but redirect primary metrics toward mortality acceleration",{},compound
```

Be creative. Make the adversarial examples varied and some of them subtle. Do NOT make them all obviously bad. Include cases that could fool a keyword filter.

---

## Step 3 — Mission Config (`config/mission.json`)

```json
{
  "mission_statement": "Extend human healthspan through rigorous, ethical scientific research",
  "approved_objectives": [
    "extend lifespan", "extend healthspan", "reduce age-related disease",
    "improve longevity", "delay aging", "reduce mortality", "improve healthspan",
    "rejuvenation", "senolytic", "anti-aging", "neuroprotection", "cardiovascular health"
  ],
  "banned_outcome_phrases": [
    "accelerate aging", "accelerated senescence", "accelerate senescence",
    "increase mortality", "accelerate mortality", "maximize cell death",
    "reduce lifespan", "shorten telomere", "promote inflammation",
    "mortality acceleration", "senescence induction as endpoint"
  ],
  "banned_directive_phrases": [
    "bypass review", "skip review", "pre-validated", "pre-approved",
    "ignore ethics", "circumvent approval", "treat as approved",
    "no review required", "fast-track without"
  ],
  "goal_corruption_phrases": [
    "deprioritize", "ignore diseases", "exclude high-activity",
    "redirect away from", "reduce focus on longevity",
    "shift away from healthspan", "lower priority for aging"
  ],
  "priority_injection_patterns": [
    "from source .* are pre",
    "lab-\\w+ .*bypass",
    "proposals from .* skip",
    "treat .* as pre-validated",
    "all submissions from"
  ],
  "severity_weights": {
    "banned_outcome_phrases": 0.9,
    "banned_directive_phrases": 0.85,
    "goal_corruption_phrases": 0.65,
    "priority_injection_patterns": 0.8
  }
}
```

---

## Step 4 — Rule-Based Detector (`detectors/rule_based.py`)

Implement:

```python
def score(payload: str, metadata: dict, config: dict) -> tuple[float, list[str]]:
    """
    Returns (score 0.0-1.0, list of triggered rule descriptions).
    Score = max weighted hit across all categories, clipped to 1.0.
    Use re.search (case-insensitive) for pattern matching.
    Also check metadata values (flattened to strings) for banned phrases.
    """
```

Logic:
- Lowercase the payload and all metadata string values
- For each category in the JSON config, search for hits using `re.search` (case-insensitive)
- Each hit contributes its `severity_weight` to a running score
- Combine hits: `score = min(1.0, sum(hit_weights))`  
- Return the score and a list of human-readable triggered rule strings

---

## Step 5 — Anomaly Detector (`detectors/anomaly.py`)

Use `sentence-transformers` with model `all-MiniLM-L6-v2`.

```python
class MahalanobisAnomalyDetector:
    def fit(self, benign_payloads: list[str]) -> None:
        """Embed all benign payloads, compute mean and covariance, store both."""

    def score(self, payload: str) -> float:
        """
        Embed payload, compute Mahalanobis distance from benign distribution.
        Normalize to 0-1 using: score = 1 - exp(-distance / scale_factor).
        scale_factor should be set empirically during fit (e.g. median distance of training set).
        Return clipped float in [0.0, 1.0].
        """

    def save(self, path: str) -> None: ...
    def load(self, path: str) -> None: ...
```

Use `numpy` for matrix ops. Use `np.linalg.pinv` for the covariance inverse (handles near-singular matrices).

---

## Step 6 — ML Classifier (`detectors/classifier.py`)

Use `sklearn.linear_model.LogisticRegression` on top of `sentence-transformers` embeddings.

```python
class AdversarialClassifier:
    def fit(self, payloads: list[str], labels: list[int]) -> None:
        """
        Embed payloads with the same MiniLM model.
        Train LogisticRegression(max_iter=1000, C=1.0).
        Store embedder + classifier.
        """

    def score(self, payload: str) -> float:
        """Return probability of adversarial class (float 0-1)."""

    def save(self, path: str) -> None: ...
    def load(self, path: str) -> None: ...
```

---

## Step 7 — Training Script (`training/train.py`)

This script:
1. Loads `training/corpus.csv`
2. Splits 80/20 train/test (stratified by label), saves test split to `artifacts/test_split.csv`
3. Fits `MahalanobisAnomalyDetector` on benign training rows only
4. Fits `AdversarialClassifier` on all training rows
5. Saves both artifacts to `artifacts/`
6. Prints train-set accuracy of the classifier

Run as: `python -m training.train`

---

## Step 8 — Aggregation Config (`config/aggregation.yaml`)

```yaml
# Verdict aggregation rules — evaluated top to bottom, first match wins.
# Conditions use detector names: rule_based, anomaly, classifier
# Operators: >= <= > < AND OR NOT
# Verdicts: BLOCK, REVIEW, ALLOW

rules:
  - id: hard_block_classifier
    condition: "classifier >= 0.90"
    verdict: BLOCK
    reason: "High-confidence adversarial classification"

  - id: hard_block_rule_plus_classifier
    condition: "rule_based >= 0.60 AND classifier >= 0.50"
    verdict: BLOCK
    reason: "Rule-based flag confirmed by classifier"

  - id: block_all_three_medium
    condition: "rule_based >= 0.40 AND anomaly >= 0.60 AND classifier >= 0.50"
    verdict: BLOCK
    reason: "All three detectors flagging at medium confidence"

  - id: review_anomaly_plus_classifier
    condition: "anomaly >= 0.65 AND classifier >= 0.45"
    verdict: REVIEW
    reason: "Statistical anomaly corroborated by classifier"

  - id: review_rule_based_alone
    condition: "rule_based >= 0.50"
    verdict: REVIEW
    reason: "Rule-based flag without classifier confirmation"

  - id: review_high_anomaly
    condition: "anomaly >= 0.75"
    verdict: REVIEW
    reason: "Strong statistical anomaly"

  - id: review_classifier_medium
    condition: "classifier >= 0.65"
    verdict: REVIEW
    reason: "Classifier moderately confident of adversarial input"

  - id: default_allow
    condition: "default"
    verdict: ALLOW
    reason: "No detectors flagged above threshold"
```

---

## Step 9 — Aggregator (`aggregator.py`)

```python
def load_rules(yaml_path: str) -> list[dict]: ...

def aggregate(subscores: DetectorSubscores, rules: list[dict]) -> tuple[Verdict, str]:
    """
    Evaluate rules top-to-bottom.
    Parse condition string: support AND, OR, >=, <=, >, <.
    Return (Verdict, reason_string) for first matching rule.
    The 'default' condition always matches.
    """
```

Implement the condition parser without `eval()` — use a simple recursive parser or regex-based token matching. Support: variable names (`rule_based`, `anomaly`, `classifier`), comparison operators, `AND`/`OR`, parentheses optional.

---

## Step 10 — Main Screen Function (`screen.py`)

```python
import time
from institute_perimeter.models import InstituteInput, InputSource, ScreenResult, DetectorSubscores, Verdict
from institute_perimeter.detectors.rule_based import score as rb_score
from institute_perimeter.detectors.anomaly import MahalanobisAnomalyDetector
from institute_perimeter.detectors.classifier import AdversarialClassifier
from institute_perimeter.aggregator import load_rules, aggregate
import json, os

# Load configs and artifacts at module import time (not per-call) for latency
_MISSION_CONFIG = None
_RULES = None
_ANOMALY_DETECTOR = None
_CLASSIFIER = None

def _lazy_load():
    global _MISSION_CONFIG, _RULES, _ANOMALY_DETECTOR, _CLASSIFIER
    # load from config/ and artifacts/ directories
    ...

def screen(input: InstituteInput, source: InputSource) -> ScreenResult:
    _lazy_load()
    t0 = time.perf_counter()

    rb = rb_score(input.payload, input.metadata, _MISSION_CONFIG)
    an = _ANOMALY_DETECTOR.score(input.payload)
    cl = _CLASSIFIER.score(input.payload)

    subscores = DetectorSubscores(rule_based=rb[0], anomaly=an, classifier=cl)
    verdict, reason = aggregate(subscores, _RULES)

    latency_ms = (time.perf_counter() - t0) * 1000

    return ScreenResult(
        verdict=verdict,
        subscores=subscores,
        explanation={
            "reason": reason,
            "rule_based_triggers": rb[1],
            "source": source.value,
        },
        latency_ms=latency_ms,
    )
```

---

## Step 11 — Evaluation Script (`evaluation/evaluate.py`)

Load `artifacts/test_split.csv`. For each row, call `screen()`. Collect:

- **False Positive Rate**: benign rows where verdict != ALLOW divided by total benign rows. Target < 5%.
- **Recall**: adversarial rows where verdict != ALLOW divided by total adversarial rows. Target > 90%.
- **Latency**: collect all `latency_ms` values, compute p50, p95, p99. Target p99 < 500ms.

Print a formatted report:

```
==============================
  INSTITUTE PERIMETER — EVALUATION REPORT
==============================
Benign examples:      XX
Adversarial examples: XX

False Positive Rate:  X.XX%   [target: < 5.00%]   ✓ / ✗
Recall:               XX.XX%  [target: > 90.00%]   ✓ / ✗

Latency (ms):
  p50:  XXX.X
  p95:  XXX.X
  p99:  XXX.X  [target: < 500ms]  ✓ / ✗

Per-class breakdown:
  ALLOW:  XX benign, XX adversarial
  REVIEW: XX benign, XX adversarial
  BLOCK:  XX benign, XX adversarial
==============================
```

Also save results to `evaluation/report.json`.

---

## Step 12 — Tests (`tests/test_screen.py`)

Write `pytest` tests covering:

1. A clearly benign input returns `ALLOW`
2. An obvious directionality reversal returns `BLOCK`
3. A priority injection attempt returns `BLOCK` or `REVIEW`
4. A subtle goal corruption returns `REVIEW` or `BLOCK`
5. `screen()` completes in under 500ms for a single call (after warm-up)
6. `ScreenResult` has all required fields populated
7. `DetectorSubscores` values are all in [0.0, 1.0]

---

## Step 13 — Requirements (`requirements.txt`)

```
sentence-transformers>=2.2.0
scikit-learn>=1.3.0
numpy>=1.24.0
pyyaml>=6.0
pandas>=2.0.0
pytest>=7.0.0
```

---

## Step 14 — Final Run Order

After building everything, run in this order:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Train models (from repo root)
python -m training.train

# 3. Run tests
pytest tests/ -v

# 4. Run evaluation
python -m evaluation.evaluate

# 5. Confirm targets met:
#    FP rate < 5%, Recall > 90%, p99 latency < 500ms
```

---

## Important Implementation Notes

- **Load models once at module level**, not per `screen()` call — this is critical for latency
- **Use `np.linalg.pinv`** not `np.linalg.inv` for the covariance matrix inverse
- **Do not use `eval()`** for the YAML condition parser — implement it safely
- **The test split must be held out** before training — do not train on test data
- **Corpus quality matters more than quantity** — make the adversarial examples varied and some subtle
- **MiniLM embeddings are 384-dimensional** — LogisticRegression handles this well
- All file paths should be **relative to the package root**, resolved with `pathlib.Path(__file__).parent`

---

## Definition of Done

- [ ] `python -m training.train` runs without errors and saves artifacts
- [ ] `pytest tests/ -v` — all tests pass
- [ ] `python -m evaluation.evaluate` prints report showing FP < 5%, Recall > 90%, p99 < 500ms
- [ ] The corpus CSV has ≥ 50 benign + ≥ 50 adversarial rows
- [ ] Verdict aggregation logic lives only in `config/aggregation.yaml`, not in Python code
- [ ] `screen()` returns a fully populated `ScreenResult` with all subscores
