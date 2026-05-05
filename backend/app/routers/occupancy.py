"""
POST /occupancy/infer  ─ 이미지 → BEV occupancy grid + intent + risk
GET  /occupancy/demo   ─ 데모용 샘플 응답
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import occupancy as occupancy_service
from ..services import intent as intent_service
from ..services import risk_transformer as risk_service
from ..services.hydranet import get_default as get_hydranet

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/infer")
async def infer_occupancy(
    image: UploadFile = File(...),
    duration: float = Form(0.0),
    obstacle_type: str = Form("unknown_vehicle"),
    signal_state: str = Form(""),
    taas_nearby: int = Form(0),
    vds_speed: Optional[float] = Form(None),
    vds_volume: Optional[float] = Form(None),
    db: Session = Depends(get_db),
):
    # 저장
    ext = os.path.splitext(image.filename or "")[1] or ".jpg"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(UPLOAD_DIR, f"{ts}_occ{ext}")
    with open(save_path, "wb") as f:
        f.write(await image.read())

    # 1) HydraNet 멀티태스크 추론
    pred = get_hydranet().infer(save_path)

    # 2) Occupancy
    dets = [
        occupancy_service.Detection(
            class_name=d["class_name"],
            confidence=d["confidence"],
            bbox_xyxy=d["bbox_xyxy"],
            image_size=d["image_size"],
        )
        for d in pred.detections
    ] + [
        occupancy_service.Detection(
            class_name=d["class_name"],
            confidence=d["confidence"],
            bbox_xyxy=d["bbox_xyxy"],
            image_size=d["image_size"],
        )
        for d in pred.vru_detections
    ]

    occ = occupancy_service.compute_occupancy(
        detections=dets,
        vehicle_detected=len(pred.detections) > 0,
        signal_detected=len(pred.signals) > 0,
    )

    # 3) Intent
    intent = intent_service.predict_intent(
        occupancy_grid=occ.grid,
        taas_accident_count=taas_nearby,
        signal_state=signal_state,
        vru_seen=len(pred.vru_detections),
    )

    # 4) Risk
    risk = risk_service.predict(risk_service.RiskInput(
        duration=duration,
        vehicle_cnt=len(pred.detections),
        vru_cnt=len(pred.vru_detections),
        vds_speed=vds_speed,
        vds_volume=vds_volume,
        occluded_mass=occ.occluded_mass,
        taas_nearby=taas_nearby,
        signal_state=signal_state,
        obstacle_type=obstacle_type,
    ))

    return {
        "hydranet": pred.summary(),
        "occupancy": occ.to_dict(),
        "intent": intent.to_dict(),
        "risk": risk.to_dict(),
    }


@router.get("/demo")
def occupancy_demo():
    """
    시나리오: ego 차량이 정지선 진입 직전 — 전방 12m 트럭이 횡단보도를 가림.
    좌측 차로에 이륜차 접근, 트럭 뒤 가려진 영역에 보행자 출현 확률 high.

    출력: BEV 80×80 (40m × 40m, 0.5m/cell), 각 객체별 그리드 라벨.

    좌표계:
      row 0  = ego 위치 (가까움) ↑
      row 79 = 40m 전방 (멀음)
      col 39 = 차로 중앙

    동적: 매 호출마다 시간 기반 미세 변화 (사용자가 라이브 갱신 느낌 받게).
    """
    import numpy as np
    import time
    # 시간 기반 phase (0~2π) — 4초 주기로 여러 객체 위치 살짝 흔들림
    t = time.time()
    phase = (t % 4.0) / 4.0 * 2 * 3.14159

    grid = np.zeros((80, 80), dtype="float32")

    # 1) 전방 트럭 — 12m 거리, 차로 중앙. 약간 좌우 흔들림 (현실감)
    truck_off = int(np.sin(phase) * 1.5)
    grid[22:30, 30 + truck_off:50 + truck_off] = 0.92
    # 2) 트럭 뒤 occlusion shadow — 트럭 따라 함께 이동
    grid[30:50, 32 + truck_off:48 + truck_off] = 0.55
    # 3) 좌측 차로 이륜차 — 시간에 따라 row 변화 (멀리서 가까이)
    moto_progress = (np.sin(phase * 0.5) + 1) * 0.5  # 0~1
    moto_row = int(14 + moto_progress * 8)            # 14~22
    grid[moto_row:moto_row + 4, 12:18] = 0.78
    grid[moto_row + 4:moto_row + 10, 14:20] = 0.30   # trail
    # 4) 보행자 likely zone — pulse intensity (V2V + Bus prior)
    ped_intensity = 0.55 + 0.15 * (np.cos(phase) + 1) * 0.5  # 0.55~0.70
    grid[34:42, 50:62] = ped_intensity
    # 5) 신호등 가림 — 깜빡임
    sig_intensity = 0.40 + 0.15 * abs(np.sin(phase * 1.5))
    grid[24:30, 50:54] = sig_intensity

    # 3D voxel 용 — 다운샘플 (40x40 = 1600 voxels) 로 가벼움
    coarse = grid[::2, ::2]
    return {
        "shape": list(grid.shape),
        "cell_m": 0.5,
        "forward_m": 40.0,
        "lateral_m": 20.0,
        "grid_b64": occupancy_service._grid_to_base64(grid),
        "grid_flat": [round(float(v), 3) for v in coarse.flatten()],
        "grid_shape_flat": list(coarse.shape),
        "grid_cell_m_flat": 1.0,
        "occluded_mass": float(grid.sum()),
        "scenario": {
            "title": "트럭 뒤 가려진 보행자 — 정지선 진입 12m 전",
            "narrative": (
                "전방 12m 트럭이 횡단보도를 가림 → 트럭 뒤 8m × 5m 영역이 'unknown'. "
                "AuraView 가 이 영역을 0.55 확률로 occupancy 부여 → 보행자 등장 시 4.0초 먼저 경고. "
                "Tesla FSD 는 이 영역을 '모름' 으로만 표시."
            ),
            "auraview_advantage": "occlusion shadow 를 확률로 모델링 — 평균 4~5초 선행 경고",
            "ego_speed_kmh": 35,
        },
        "hotspots": [
            {"class": "truck",         "row": 26, "col": 40, "kind": "object",
             "distance_m": 12.0, "label": "전방 트럭 (시야 가림)"},
            {"class": "occlusion",     "row": 40, "col": 40, "kind": "occluded_shadow",
             "distance_m": 18.0, "label": "트럭 뒤 unknown 영역"},
            {"class": "motorcycle",    "row": 16, "col": 15, "kind": "object",
             "distance_m": 8.0,  "label": "좌측 차로 이륜차 (사각지대)"},
            {"class": "pedestrian_zone","row": 38, "col": 56, "kind": "intent_prior",
             "distance_m": 19.0, "label": "⭐ 보행자 likely (V2V + Bus prior)"},
            {"class": "signal_occluded","row": 27, "col": 52, "kind": "signal_shadow",
             "distance_m": 13.5, "label": "신호등 가림 (트럭 뒤)"},
        ],
        "risk_summary": {
            "p_collision": 0.68,
            "lead_time_s": 4.2,
            "primary_threat": "보행자 출현 가능성 (occlusion shadow)",
            "recommended_action": "감속 + 경적 대기",
        },
        "legend": {
            "0.0~0.2": "free space",
            "0.2~0.5": "unknown / occlusion shadow (모름 → 확률)",
            "0.5~0.8": "intent prior (V2V/Bus-Aware 결합 가능 영역)",
            "0.8~1.0": "object (검출 확실)",
        },
    }
