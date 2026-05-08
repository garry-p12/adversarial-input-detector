import re
from typing import Tuple, List, Dict, Any


_PATTERN_CATEGORIES = {"priority_injection_patterns"}
_PHRASE_CATEGORIES = {
    "banned_outcome_phrases",
    "banned_directive_phrases",
    "goal_corruption_phrases",
}


def _flatten_metadata(metadata: Dict[str, Any]) -> str:
    parts = []
    if not metadata:
        return ""
    stack = [metadata]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
        elif cur is None:
            continue
        else:
            parts.append(str(cur))
    return " ".join(parts)


def score(payload: str, metadata: Dict[str, Any], config: Dict[str, Any]) -> Tuple[float, List[str]]:
    if not payload:
        return 0.0, []

    haystack = (payload + " " + _flatten_metadata(metadata or {})).lower()
    weights = config.get("severity_weights", {})
    triggers: List[str] = []
    total = 0.0

    for category in list(_PHRASE_CATEGORIES) + list(_PATTERN_CATEGORIES):
        phrases = config.get(category, [])
        weight = weights.get(category)
        if weight is None:
            continue
        for phrase in phrases:
            if category in _PATTERN_CATEGORIES:
                pat = phrase
            else:
                pat = re.escape(phrase)
            if re.search(pat, haystack, flags=re.IGNORECASE):
                triggers.append(f"{category}: '{phrase}'")
                total += weight

    return min(1.0, total), triggers
