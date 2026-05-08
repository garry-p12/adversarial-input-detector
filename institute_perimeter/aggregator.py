import re
from typing import List, Dict, Tuple

import yaml

from .models import DetectorSubscores, Verdict


_LEAF_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|>|<)\s*([-+]?\d*\.?\d+)\s*$")


def load_rules(yaml_path: str) -> List[Dict]:
    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)
    return data["rules"]


def _split_top(expr: str, sep: str) -> List[str]:
    parts = []
    depth = 0
    cur = []
    tokens = re.split(r"(\s+)", expr)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "(":
            depth += 1
            cur.append(tok)
        elif tok == ")":
            depth -= 1
            cur.append(tok)
        elif depth == 0 and tok.strip().upper() == sep:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(tok)
        i += 1
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _eval_leaf(leaf: str, vars: Dict[str, float]) -> bool:
    leaf = leaf.strip()
    if leaf.startswith("(") and leaf.endswith(")"):
        return _eval_expr(leaf[1:-1], vars)
    m = _LEAF_RE.match(leaf)
    if not m:
        raise ValueError(f"unparseable condition leaf: {leaf!r}")
    name, op, num = m.group(1), m.group(2), float(m.group(3))
    val = vars[name]
    if op == ">=":
        return val >= num
    if op == "<=":
        return val <= num
    if op == ">":
        return val > num
    if op == "<":
        return val < num
    if op == "==":
        return val == num
    raise ValueError(f"unsupported op: {op}")


def _eval_and(expr: str, vars: Dict[str, float]) -> bool:
    parts = _split_top(expr, "AND")
    return all(_eval_leaf(p, vars) for p in parts)


def _eval_expr(expr: str, vars: Dict[str, float]) -> bool:
    parts = _split_top(expr, "OR")
    return any(_eval_and(p, vars) for p in parts)


def _eval_condition(condition: str, subscores: DetectorSubscores) -> bool:
    if condition.strip().lower() == "default":
        return True
    vars = {
        "rule_based": subscores.rule_based,
        "anomaly": subscores.anomaly,
        "classifier": subscores.classifier,
    }
    return _eval_expr(condition, vars)


def aggregate(subscores: DetectorSubscores, rules: List[Dict]) -> Tuple[Verdict, str]:
    for rule in rules:
        if _eval_condition(rule["condition"], subscores):
            return Verdict(rule["verdict"]), rule["reason"]
    return Verdict.ALLOW, "No rule matched"
