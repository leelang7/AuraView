"""
End-to-End Risk Transformer.

입력: [duration, vehicle_cnt, vru_cnt, vds_speed, vds_volume, occluded_mass,
        taas_nearby, signal_stop, incident_flag, obstacle_big]  (10 features)
출력: P(collision), P(near_miss), feature attention

기본 동작:
  - models/risk_transformer.pt 가 있으면 → trained PyTorch Transformer 추론
  - 없으면 → 해석 가능 linear-logistic fallback (개발·테스트 환경)

학습 스크립트: notebooks/train_risk_transformer_real.py
설계 의도: 6종 공공데이터 + Fleet 누적 데이터를 한 모델에 투입.
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


def _make_feats(inp: RiskInput) -> Dict[str, float]:
    big_obstacle = inp.obstacle_type in {"truck", "bus", "top_truck", "van"}
    signal_stop = 1.0 if inp.signal_state == "stop-And-Remain" else 0.0
    incident_flag = 1.0 if inp.incident_flag else 0.0
    return {
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


# ─── Trained Transformer lazy loader ───────────────────────────────────
_TRAINED = None       # cached torch model
_TRAINED_TRIED = False
_FEATURE_ORDER = [
    "duration", "vehicle_cnt", "vru_cnt", "vds_speed", "vds_volume",
    "occluded_mass", "taas_nearby", "signal_stop", "incident_flag", "obstacle_big",
]


def _try_load_trained():
    """
    models/risk_transformer.pt 를 한 번 로드 시도. torch 가 없거나 파일 없으면 None.
    """
    global _TRAINED, _TRAINED_TRIED
    if _TRAINED_TRIED:
        return _TRAINED
    _TRAINED_TRIED = True
    try:
        import os
        from pathlib import Path
        import torch
        import torch.nn as nn

        ckpt_path = Path(os.path.dirname(__file__)).resolve().parents[2] / "models" / "risk_transformer.pt"
        if not ckpt_path.exists():
            return None

        class _Net(nn.Module):
            def __init__(self, n=10, d=64, h=4, L=2, drop=0.1):
                super().__init__()
                self.emb = nn.Linear(1, d)
                self.pos = nn.Parameter(torch.randn(n, d) * 0.02)
                layer = nn.TransformerEncoderLayer(d, h, dim_feedforward=128,
                                                    dropout=drop, batch_first=True)
                self.enc = nn.TransformerEncoder(layer, L)
                self.head = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, 2))

            def forward(self, x):
                h_ = self.emb(x.unsqueeze(-1)) + self.pos
                h_ = self.enc(h_)
                return self.head(h_.mean(dim=1))

        ckpt = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
        arch = ckpt.get("arch", {})
        model = _Net(
            n=arch.get("n_features", 10),
            d=arch.get("d_model", 64),
            h=arch.get("n_heads", 4),
            L=arch.get("n_layers", 2),
        )
        model.load_state_dict(ckpt["state_dict"])
        model.eval()
        _TRAINED = model
        return _TRAINED
    except Exception:
        _TRAINED = None
        return None


def _trained_predict(feats: Dict[str, float]) -> Optional[float]:
    model = _try_load_trained()
    if model is None:
        return None
    try:
        import torch
        vec = [float(feats.get(k, 0.0)) for k in _FEATURE_ORDER]
        x = torch.tensor([vec], dtype=torch.float32)
        with torch.no_grad():
            logits = model(x)
            prob = torch.softmax(logits, dim=1)[0, 1].item()
        return float(prob)
    except Exception:
        return None


def predict(inp: RiskInput) -> RiskOutput:
    """학습된 Transformer 우선 — 없으면 해석 가능 linear-logistic fallback."""
    feats = _make_feats(inp)

    # 1) Trained Transformer 시도
    trained_p = _trained_predict(feats)

    # 2) Linear contribution (해석성·attention 용으로 항상 계산)
    contrib = {name: WEIGHTS[name] * val for name, val in feats.items()}
    logit_coll = BIAS + sum(contrib.values())
    fallback_p = _sigmoid(logit_coll)

    p_coll = trained_p if trained_p is not None else fallback_p
    p_near = min(1.0, p_coll * 1.6)

    total = sum(abs(v) for v in contrib.values()) or 1e-9
    attention = {k: abs(v) / total for k, v in contrib.items()}

    explanation: List[str] = []
    top = sorted(attention.items(), key=lambda kv: kv[1], reverse=True)[:3]
    for name, weight in top:
        if weight < 0.03:
            continue
        explanation.append(f"{name} 기여도 {weight*100:.0f}%")
    if trained_p is not None:
        explanation.insert(0, "trained Transformer 사용")
    else:
        explanation.insert(0, "linear baseline fallback")

    return RiskOutput(
        p_collision=p_coll,
        p_near_miss=p_near,
        attention=attention,
        explanation=explanation,
    )
