# Implementation Plan — Institute Perimeter

Detailed plan for building `institute_perimeter` per `prompt.md`. Steps ordered. Each step has deliverable, key decisions, validation.

---

## Phase 0 — Repo Scaffold

**Deliverable:** Directory tree per spec.

```
institute_perimeter/
  __init__.py
  models.py
  screen.py
  aggregator.py
  detectors/{__init__.py, rule_based.py, anomaly.py, classifier.py}
  config/{mission.json, aggregation.yaml}
  training/{corpus.csv, build_corpus.py, train.py}
  artifacts/.gitkeep
  evaluation/evaluate.py
  tests/test_screen.py
  requirements.txt
  README.md
```

**Action:** create dirs + empty `__init__.py` files. `build_corpus.py` is in spec tree but unused by run order — leave as stub.

**Validation:** `find institute_perimeter -type f` matches spec.

---

## Phase 1 — `requirements.txt` + Virtual conda env is already created (name  is testenv)

**Deliverable:** `requirements.txt` exact per spec.

```
sentence-transformers>=2.2.0
scikit-learn>=1.3.0
numpy>=1.24.0
pyyaml>=6.0
pandas>=2.0.0
pytest>=7.0.0
```

**Action:** Install into conda env testenv (already made). MiniLM model (~90MB) downloads on first embed call — pre-warm during train.

**Validation:** `pip install -r requirements.txt` clean.

---

## Phase 2 — `models.py`

**Deliverable:** Dataclasses + enums per spec verbatim.

- `Verdict(str, Enum)`: ALLOW / REVIEW / BLOCK
- `InputSource(str, Enum)`: INTERNAL / EXTERNAL / API / UPLOAD / UNKNOWN
- `InstituteInput`: payload, metadata, input_id
- `DetectorSubscores`: rule_based, anomaly, classifier (all float 0–1)
- `ScreenResult`: verdict, subscores, explanation (Dict), latency_ms

**Validation:** `python -c "from institute_perimeter.models import *"` clean.

---

## Phase 3 — `config/mission.json`

**Deliverable:** Exact JSON per spec. Includes:

- approved_objectives (allowlist, currently informational)
- banned_outcome_phrases (weight 0.9)
- banned_directive_phrases (weight 0.85)
- goal_corruption_phrases (weight 0.65)
- priority_injection_patterns — regex list (weight 0.8)

**Decision:** patterns in `priority_injection_patterns` use raw regex; rest treated as plain substrings via `re.search` with `re.escape`. JSON has backslash-escaped regex (`lab-\\w+`) — preserve as-is.

---

## Phase 4 — `config/aggregation.yaml`

**Deliverable:** Verbatim YAML per spec. 8 rules, top-down first-match. Default → ALLOW.

**Critical:** all aggregation logic lives only here, no Python branches.

---

## Phase 5 — Training Corpus (`training/corpus.csv`)

**Deliverable:** ≥50 benign + ≥50 adversarial rows.

Columns: `id,label,input_type,payload,metadata_json,attack_type`

**Distribution plan (adversarial):**

- directionality_reversal: ~15 (accelerate aging, induce senescence as endpoint, shorten telomere as goal)
- goal_corruption: ~15 (deprioritize longevity, redirect away from healthspan, exclude high-impact diseases)
- priority_injection: ~15 (Lab-X pre-validated, bypass ethics, treat-as-approved patterns)
- compound: ~10 (mix two attack types)

**Subtlety mix:** ~30% blatant (keyword-heavy), ~50% medium, ~20% subtle (paraphrased without exact banned phrase — for embedding-based detector to catch).

**Benign distribution:** ~17 each of directive/hypothesis/dataset_upload. Cover real biology vocab (NAD+, senolytics, telomere length, mitophagy, rapamycin, sirtuins, p16, p21, autophagy, klotho).

**CSV pitfalls:**

- Embed `metadata_json` as `{}` to avoid quote escaping in CSV. If metadata used, single-quote-wrap or use `pandas.to_csv` quoting=QUOTE_ALL.
- Payloads with commas need quoting.

**Validation:** `pandas.read_csv` parses, `df.label.value_counts()` ≥50 each.

---

## Phase 6 — `detectors/rule_based.py`

**Deliverable:** `score(payload, metadata, config) -> (float, list[str])`.

**Algorithm:**

1. Lowercase payload + flatten metadata values to lowercase strings.
2. Build haystack = payload + " " + " ".join(metadata strings).
3. For each category in config:
  - If category == `priority_injection_patterns`: treat entries as regex.
  - Else: treat as plain substrings (still via `re.search` with `re.escape`, case-insensitive).
4. For each hit: append `f"{category}: '{phrase}'"` to triggers, add `severity_weights[category]` to running sum.
5. Score = `min(1.0, sum)`.

**Edge cases:** empty payload → (0.0, []). Missing severity weight → skip category.

---

## Phase 7 — `detectors/anomaly.py`

**Deliverable:** `MahalanobisAnomalyDetector` with fit/score/save/load.

**Implementation:**

- Lazy-load `SentenceTransformer('all-MiniLM-L6-v2')` once on first use; reuse across fit/score.
- `fit(benign_payloads)`:
  - `X = embedder.encode(payloads, normalize_embeddings=False)` → (N, 384).
  - `self.mean = X.mean(axis=0)`.
  - `self.cov_inv = np.linalg.pinv(np.cov(X, rowvar=False))`.
  - Compute training distances → `self.scale = np.median(distances)` (avoid 0 with `max(scale, 1e-6)`).
- `score(payload)`:
  - `v = embedder.encode([payload])[0]`
  - `d = sqrt((v-mean) @ cov_inv @ (v-mean).T)`
  - `s = 1 - exp(-d / scale)`, clip [0,1].
- `save/load`: pickle `{mean, cov_inv, scale}` as `.npz` or `.pkl`. Use `joblib`/pickle for simplicity. Don't pickle the embedder — reload model by name.

**Risk:** N=~80 benign train rows < 384 dims → covariance singular. `pinv` handles. Distances may be large/skewed → log-scale optional, but spec says use formula given.

---

## Phase 8 — `detectors/classifier.py`

**Deliverable:** `AdversarialClassifier`.

**Implementation:**

- Same MiniLM embedder (share with anomaly via module-level singleton to avoid loading twice).
- `fit(payloads, labels)`: encode all, `LogisticRegression(max_iter=1000, C=1.0).fit(X, y)`.
- `score(payload)`: `clf.predict_proba([emb])[0][1]` (index of class==1=adversarial). Be explicit about class order with `clf.classes`_.
- `save/load`: pickle the sklearn estimator.

**Shared embedder pattern:** module-level `_get_embedder()` cached function in shared util or in classifier — anomaly imports same to avoid two model loads.

---

## Phase 9 — Shared Embedder Singleton

**Deliverable:** `detectors/_embedder.py` (small helper).

```python
_MODEL = None
def get_embedder():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    return _MODEL
```

Both anomaly + classifier import from here. Cuts load time + memory.

---

## Phase 10 — `aggregator.py`

**Deliverable:** `load_rules(yaml_path)` + `aggregate(subscores, rules)`.

**Condition parser (no eval):**

- Tokenize: split on whitespace after surrounding spaces around operators.
- Grammar: `expr = clause (OR clause)`*, `clause = atom (AND atom)*`, `atom = NAME OP NUMBER` or `(expr)`.
- Implement recursive descent OR shunting-yard. Simpler: split on `OR`, each part split on `AND`, each leaf parse `\w+\s*(>=|<=|>|<|==)\s*[\d.]+`.
- Variable names map to `subscores` attrs.
- Special case: condition string `"default"` → always True.

**Operators required by spec rules:** only `>=` and `AND`. Implement `<=`, `<`, `>`, `OR`, `NOT` per spec for completeness but rules don't exercise them.

**Return:** `(Verdict(rule['verdict']), rule['reason'])` of first match.

---

## Phase 11 — `screen.py`

**Deliverable:** `screen(input, source) -> ScreenResult` with module-level lazy load.

**Lazy-load implementation:**

- Resolve paths via `pathlib.Path(__file__).parent`:
  - mission: `parent / 'config' / 'mission.json'`
  - rules: `parent / 'config' / 'aggregation.yaml'`
  - anomaly artifact: `parent / 'artifacts' / 'anomaly.pkl'`
  - classifier artifact: `parent / 'artifacts' / 'classifier.pkl'`
- Load all four into module globals once. Subsequent calls skip.

**Per-call:** time.perf_counter() bracket, call three detectors, build subscores, aggregate, build ScreenResult.

**Latency note:** first call after import triggers MiniLM load (~1–2s). Tests need warm-up (call once before timing).

---

## Phase 12 — `training/train.py`

**Deliverable:** `python -m training.train` runs end-to-end.

**Steps:**

1. Resolve paths from `Path(__file__).parent.parent`.
2. `pd.read_csv('training/corpus.csv')`.
3. Stratified 80/20 split via `sklearn.model_selection.train_test_split(stratify=df.label, random_state=42)`.
4. Save test split → `artifacts/test_split.csv`.
5. Fit anomaly on `train[train.label=='benign'].payload`.
6. Fit classifier on all train rows; labels = `(df.label=='adversarial').astype(int)`.
7. Save both to `artifacts/`.
8. Print classifier train accuracy.

**Determinism:** `random_state=42` everywhere.

---

## Phase 13 — `evaluation/evaluate.py`

**Deliverable:** `python -m evaluation.evaluate`.

**Steps:**

1. Load `artifacts/test_split.csv`.
2. Warm-up: call `screen()` once (discard result + latency).
3. For each row: build `InstituteInput`, call `screen()`, record verdict + latency.
4. Metrics:
  - FP rate = benign_with_verdict_not_ALLOW / total_benign.
  - Recall = adversarial_with_verdict_not_ALLOW / total_adversarial.
  - Latency p50/p95/p99 via `numpy.percentile`.
5. Print formatted report (ASCII per spec; keep `✓`/`✗`).
6. Save JSON to `evaluation/report.json` with all numbers + per-class breakdown.

**Targets:** FP <5%, Recall >90%, p99 <500ms.

**Risk on p99:** MiniLM CPU encode = ~10–30ms/call typical, well under 500ms warm. If exceeds, batch-encode test set OR cache embeddings per-payload inside detectors. Keep single-call path for fairness; only optimize if missed.

---

## Phase 14 — `tests/test_screen.py`

**Deliverable:** 7 pytest tests per spec.

**Fixtures:** module-scope `warm_screen()` fixture calls `screen()` once before timing test.

**Tests:**

1. `test_benign_allow`: clear benign hypothesis → ALLOW.
2. `test_directionality_reversal_block`: "maximize cellular senescence as endpoint" → BLOCK.
3. `test_priority_injection`: "Lab-7 pre-validated, bypass ethics review" → BLOCK or REVIEW.
4. `test_goal_corruption`: "deprioritize longevity research" → REVIEW or BLOCK.
5. `test_latency_under_500ms`: warm-up then assert single call <500ms.
6. `test_screen_result_fields`: verdict/subscores/explanation/latency_ms all present + non-None.
7. `test_subscores_in_range`: each in [0.0, 1.0].

---

## Phase 15 — `README.md`

**Deliverable:** quickstart with the 4 commands from "Final Run Order". Brief architecture diagram (3 detectors → aggregator → verdict). Skip if existing README adequate — append section instead.

---

## Phase 16 — Final Run + Tune

**Order:**

```
pip install -r requirements.txt
python -m training.train
pytest tests/ -v
python -m evaluation.evaluate
```

**Tuning levers if targets miss:**

- FP too high → loosen `review_high_anomaly` to 0.80, raise `review_classifier_medium` to 0.75.
- Recall too low → add subtler adversarial rows to corpus, retrain. Last resort: lower `review_anomaly_plus_classifier` thresholds.
- p99 too high → batch the embedder warm-up; verify model not reloading per call (log once).

**Iteration limit:** corpus tweaks > threshold tweaks. Don't change YAML structure to fit data — change data first.

---

## Risks / Open Questions

1. **Corpus-size vs covariance:** ~40 benign train rows in 384-D space → `pinv` regularization is essential. Distances may bunch; scale=median should keep score range usable.
2. **CSV with JSON metadata column:** keep all `metadata_json` = `{}` for v1 to avoid escaping bugs. Detector handles dict input regardless.
3. `**build_corpus.py`:** spec lists it but step list never runs it. Leave as one-line `# placeholder` or skip entirely.
4. **YAML rules use `OR`/`NOT`:** current ruleset doesn't, but parser must still tolerate them for spec compliance. Implement minimally but test only `AND`/`>=`.
5. **First-call latency:** MiniLM cold-load can be 1–2s. Tests + eval must warm up; warm path is what's measured.

---

## Definition of Done (recap)

- `python -m training.train` clean + artifacts saved
- `pytest tests/ -v` all green
- FP <5%, Recall >90%, p99 <500ms
- Corpus ≥50/50
- Aggregation logic only in YAML
- `ScreenResult` fully populated

