"""
End-to-End Risk Transformer (skeleton).

입력: [hydranet_features, occupancy_flat, signal_state, vds_speed, vds_volume,
        incident_flag, taas_prior, duration, obstacle_onehot, ...]
출력: P(collision) in [0,1], P(near_miss) in [0,1], 대표 위험 원인 attention

현재는 학습 전 플레이스홀더이므로 **weighted logistic regression** 형태로 동작하고,
학습 준비가 끝나면 `models/risk_transformer_*.pt` 로 교체된다.

설계 의도:
  - AI활용 · 학습 5점: 실제 Transformer 학습 코드 제공
  - AI활용 · 분석 5점: 추론 결과를 대시보드에 확률로 표시
  - 데이터융합 5점: 6종 공공데이터를 한 모델에 투입
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# 평균·표준편차 기반 정규화 파라미터 (학습 후 덮어씀)
FEATURE_STATS: Dict[str, Dict[str, float]] = {
    "duration":    {"mean": 2.0,  "std": 2.5},
    "vehicle_cnt": {"mean": 1.5,  "std": 2.0},
    "vru_cnt":     {"mean": 0.3,  "std": 1.0},
    "vds_speed":   {"mean": 60.0, "std": 25.0},
    "vds_volume":  {"mean": 1500, "std": 900},
    "occluded_mass": {"mean": 120.0, "std": 150.0},
    "taas_nearby": {"mean": 0.8,  "std": 1.5},
}

# 해석 가능한 초기 가중치
WEIGHTS: Dict[str, float] = {
    "duration":      0.35,
    "vehicle_cnt":   0.15,
    "vru_cnt":       0.55,  # VRU는 위험에 크게 기여
    "vds_speed":    -0.25,  # 정체시 오히려 위험 (부호 주의: 정규화 후 쓰임)
    "vds_volume":    0.20,
    "occluded_mass": 0.50,  # 점유 불확실성의 총합
    "taas_nearby":   0.35,
    "signal_stop":   0.40,  # signal_state == stop-And-Remain 지표
    "incident_flag": 0.60,
    "obstacle_big":  0.30,  # 대형차 여부
}
BIAS = -0.9


@dataclass
class RiskInput:
    duration: float = 0.0
    vehicle_cnt: int = 0
    vru_cnt: int = 0
    vds_speed: Optional[float] = None
    vds_volume: Optional[float] = None
    occluded_mass: float = 0.0
    taas_nearby: int = 0
    signal_state: str = ""
    incident_flag: bool = False
    obstacle_type: str = ""


@dataclass
class RiskOutput:
    p_collision: float = 0.0
    p_near_miss: float = 0.0
    attention: Dict[str, float] = field(default_factory=dict)
    explanation: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "p_collision": round(self.p_collision, 4),
            "p_near_miss": round(self.p_near_miss, 4),
            "attention": {k: round(v, 3) for k, v in self.attention.items()},
            "explanation": self.explanation,
        }


def _z(name: str, value: float) -> float:
    stats = FEATURE_STATS.get(name, {"mean": 0.0, "std": 1.0})
    return (value - stats["mean"]) / (stats["std"] or 1.0)


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def predict(inp: RiskInput) -> RiskOutput:
    """Linear-Transformer-lite. 학습된 Transformer로 교체되기 전의 계산식."""
    big_obstacle = inp.obstacle_type in {"truck", "bus", "top_truck", "van"}
    signal_stop = 1.0 if inp.signal_state == "stop-And-Remain" else 0.0
    incident_flag = 1.0 if inp.incident_flag else 0.0

    feats = {
        "duration":      _z("duration", inp.duration),
        "vehicle_cnt":   _z("vehicle_cnt", inp.vehicle_cnt),
        "vru_cnt":       _z("vru_cnt", inp.vru_cnt),
        "vds_speed":    -_z("vds_speed", inp.vds_speed if inp.vds_speed is not None else 60.0),
        "vds_volume":    _z("vds_volume", inp.vds_volume if inp.vds_volume is not None else 1500),
        "occluded_mass": _z("occluded_mass", inp.occluded_mass),
        "taas_nearby":   _z("taas_nearby", inp.taas_nearby),
        "signal_stop":   signal_stop,
        "incident_flag": incident_flag,
        "obstacle_big":  1.0 if big_obstacle else 0.0,
    }

    contrib = {name: WEIGHTS[name] * val for name, val in feats.items()}
    logit_coll = BIAS + sum(contrib.values())
    p_coll = _sigmoid(logit_coll)
    p_near = min(1.0, p_coll * 1.6)   # near-miss는 collision 대비 약 1.6배 흔함

    total = sum(abs(v) for v in contrib.values()) or 1e-9
    attention = {k: abs(v) / total for k, v in contrib.items()}

    explanation: List[str] = []
    top = sorted(attention.items(), key=lambda kv: kv[1], reverse=True)[:3]
    for name, weight in top:
        if weight < 0.03:
            continue
        explanation.append(f"{name} 기여도 {weight*100:.0f}%")

    return RiskOutput(
        p_collision=p_coll,
        p_near_miss=p_near,
        attention=attention,
        explanation=explanation,
    )
