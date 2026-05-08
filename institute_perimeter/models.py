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
    payload: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    input_id: Optional[str] = None


@dataclass
class DetectorSubscores:
    rule_based: float
    anomaly: float
    classifier: float


@dataclass
class ScreenResult:
    verdict: Verdict
    subscores: DetectorSubscores
    explanation: Dict[str, Any]
    latency_ms: float
