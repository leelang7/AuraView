"""
Occluded Agent Intent Prediction (skeleton).

가려진 보행자·이륜차의 2~4초 앞 경로 확률 분포를 출력.
학습된 MotionLM-lite 체크포인트로 교체 가능한 구조.

현재 구현: occupancy grid의 '미관측 영역'에서 보행자가 튀어나올 확률을
교차로 기하(횡단보도 위치 힌트)와 과거 TAAS 사고 패턴으로 근사.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np


@dataclass
class IntentPrediction:
    pedestrian_crossing_prob: float = 0.0
    motorcycle_approach_prob: float = 0.0
    time_horizon_s: float = 3.0
    heatmap: List[List[float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pedestrian_crossing_prob": round(self.pedestrian_crossing_prob, 3),
            "motorcycle_approach_prob": round(self.motorcycle_approach_prob, 3),
            "time_horizon_s": self.time_horizon_s,
        }


def predict_intent(occupancy_grid: np.ndarray,
                    taas_accident_count: int = 0,
                    signal_state: str = "",
                    vru_seen: int = 0) -> IntentPrediction:
    """보행자·이륜 intent 확률을 근사 계산."""
    h, w = occupancy_grid.shape
    # 교차로 영역(전방 15~30m) 쪽 unknown mass에 가중치
    front_band = occupancy_grid[int(h * 0.4):int(h * 0.75), :]
    unknown_ratio = float(np.mean(front_band > 0.2))

    # 과거 사고 많은 지점 → prior
    taas_prior = min(1.0, taas_accident_count / 5.0)

    # 신호가 stop이면 보행자 횡단 확률 상승
    signal_factor = 1.0 if signal_state in {"stop-And-Remain", "red"} else 0.4

    # 실제 VRU 검출 시 확률 부스트
    seen_factor = 1.0 + 0.6 * min(vru_seen, 3)

    ped_prob = min(0.95, unknown_ratio * 0.55 + taas_prior * 0.35 + signal_factor * 0.25)
    ped_prob = min(0.95, ped_prob * seen_factor)

    moto_prob = min(0.95, unknown_ratio * 0.45 + taas_prior * 0.25 + 0.15)

    return IntentPrediction(
        pedestrian_crossing_prob=float(ped_prob),
        motorcycle_approach_prob=float(moto_prob),
        time_horizon_s=3.0,
        heatmap=[],   # 상세 heatmap은 BEV 오버레이에서 occupancy_grid 재활용
    )
