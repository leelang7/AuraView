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


_SCENARIOS = {
    "truck_occlusion": {
        "title": "트럭 뒤 가려진 보행자 — 정지선 진입 12m 전",
        "narrative": "전방 12m 트럭이 횡단보도를 가림. AuraView 가 occlusion shadow 영역을 0.55 확률로 부여 → 보행자 등장 시 4.0초 먼저 경고.",
        "advantage": "occlusion shadow 를 확률로 모델링 — 평균 4~5초 선행 경고",
        "ego_speed_kmh": 35,
        "p_collision": 0.68,
        "lead_time_s": 4.2,
        "primary_threat": "보행자 출현 가능성 (occlusion shadow)",
        "recommended_action": "감속 + 경적 대기",
        "alert_text": "🚨 횡단보도 가려짐 — 트럭 뒤 보행자 가능 · 즉시 감속",
    },
    "motorcycle_blindspot": {
        "title": "좌측 사각지대 이륜차 접근 — 차선 변경 직전",
        "narrative": "좌측 후방 사각지대로 이륜차 빠르게 접근. ego 차량 차선 변경 시도 위험.",
        "advantage": "BEV 사각지대 영역 vehicle detection — 백미러 사각 4.5m 이내 100% 포착",
        "ego_speed_kmh": 45,
        "p_collision": 0.72,
        "lead_time_s": 3.1,
        "primary_threat": "좌측 사각지대 이륜차",
        "recommended_action": "차선 변경 보류 + 좌측 미러 재확인",
        "alert_text": "⚠️ 좌측 사각지대 이륜차 — 차선 변경 보류",
    },
    "signal_occlusion": {
        "title": "버스 뒤 가려진 신호등 — 교차로 진입 18m 전",
        "narrative": "전방 버스가 신호등을 완전히 가림. ITS API + V2V 결합으로 신호 상태 복원.",
        "advantage": "공공 신호 API + V2V 결합 — Tesla 는 vision 만으로 가린 신호 못 본다",
        "ego_speed_kmh": 30,
        "p_collision": 0.58,
        "lead_time_s": 5.6,
        "primary_threat": "가려진 신호등 (적색 가능성)",
        "recommended_action": "정지선 직전 감속 · 음성 안내 활성",
        "alert_text": "🚦 버스 뒤 신호 적색 — 정지선 직전 감속",
    },
    "rainy_intersection": {
        "title": "우천 교차로 — 우산 보행자 + 노면 반사",
        "narrative": "비 + 우산이 보행자 윤곽을 흐림. 야간 + 우천 가중치로 occupancy 부여.",
        "advantage": "rainy/night 시나리오 분리도 +0.45 — Transformer 가 환경 변수로 가중",
        "ego_speed_kmh": 25,
        "p_collision": 0.61,
        "lead_time_s": 3.8,
        "primary_threat": "우산 보행자 (시야 흐림)",
        "recommended_action": "감속 + 와이퍼 최대 + 헤드라이트",
        "alert_text": "🌧️ 우천 보행자 흐림 — 감속 권고",
    },
}


def _build_scene(name: str, phase: float):
    """시나리오 이름 + phase(0~2π) → (grid prob, class_grid, hotspots).

    class_grid: 0=free, 1=truck/bus, 2=motorcycle/car, 3=occlusion, 4=pedestrian, 5=signal
    """
    import numpy as np

    grid = np.zeros((80, 80), dtype="float32")
    cls = np.zeros((80, 80), dtype="int8")  # class label per cell

    if name == "truck_occlusion":
        truck_off = int(np.sin(phase) * 1.5)
        grid[22:30, 30 + truck_off:50 + truck_off] = 0.92; cls[22:30, 30 + truck_off:50 + truck_off] = 1  # 트럭
        grid[30:50, 32 + truck_off:48 + truck_off] = 0.55; cls[30:50, 32 + truck_off:48 + truck_off] = 3  # occlusion shadow
        moto_progress = (np.sin(phase * 0.5) + 1) * 0.5
        moto_row = int(14 + moto_progress * 8)
        grid[moto_row:moto_row + 4, 12:18] = 0.78; cls[moto_row:moto_row + 4, 12:18] = 2
        ped_intensity = 0.55 + 0.15 * (np.cos(phase) + 1) * 0.5
        grid[34:42, 50:62] = ped_intensity; cls[34:42, 50:62] = 4
        grid[24:30, 50:54] = 0.40 + 0.15 * abs(np.sin(phase * 1.5)); cls[24:30, 50:54] = 5
        hotspots = [
            {"class": "truck", "row": 26, "col": 40, "kind": "object", "distance_m": 12.0, "label": "전방 트럭 (시야 가림)"},
            {"class": "occlusion", "row": 40, "col": 40, "kind": "occluded_shadow", "distance_m": 18.0, "label": "트럭 뒤 unknown 영역"},
            {"class": "motorcycle", "row": 16, "col": 15, "kind": "object", "distance_m": 8.0, "label": "좌측 차로 이륜차"},
            {"class": "pedestrian_zone", "row": 38, "col": 56, "kind": "intent_prior", "distance_m": 19.0, "label": "⭐ 보행자 likely (V2V+Bus prior)"},
            {"class": "signal_occluded", "row": 27, "col": 52, "kind": "signal_shadow", "distance_m": 13.5, "label": "신호등 가림"},
        ]

    elif name == "motorcycle_blindspot":
        # 1) 자차 좌측 사각지대 영역 (배경, 먼저 깔기)
        grid[10:25, 5:14] = 0.30; cls[10:25, 5:14] = 3
        # 2) 우측 차로 차량
        grid[20:28, 60:72] = 0.85; cls[20:28, 60:72] = 1
        # 3) 전방 신호등
        grid[40:46, 38:42] = 0.60; cls[40:46, 38:42] = 5
        # 4) ego 좌후방 사각지대 이륜차 — 좌측 가까이 (row ~10, col 10~14) 빠르게 접근
        # ★ 마지막에 그려서 occlusion 영역 위에 표시
        moto_progress = (phase / (2 * 3.14159))
        moto_row = int(8 + moto_progress * 6)
        grid[moto_row:moto_row + 5, 8:14] = 0.92; cls[moto_row:moto_row + 5, 8:14] = 2
        hotspots = [
            {"class": "motorcycle", "row": moto_row + 2, "col": 11, "kind": "object", "distance_m": 5.0, "label": "⚠️ 좌측 사각지대 이륜차 (5m)"},
            {"class": "blindspot_zone", "row": 16, "col": 9, "kind": "blindspot", "distance_m": 4.0, "label": "백미러 사각지대 영역"},
            {"class": "vehicle", "row": 24, "col": 66, "kind": "object", "distance_m": 11.0, "label": "우측 차로 차량"},
        ]

    elif name == "signal_occlusion":
        # 전방 버스 (큰 객체) 25m 거리 신호등 가림
        bus_off = int(np.sin(phase * 0.8) * 0.8)
        grid[36:48, 28 + bus_off:52 + bus_off] = 0.94; cls[36:48, 28 + bus_off:52 + bus_off] = 1  # 버스
        # 가려진 신호등 위치 (버스 뒤)
        sig_state = (phase % 2) > 1  # 점멸 효과
        grid[50:56, 36:44] = 0.88 if sig_state else 0.60; cls[50:56, 36:44] = 5
        # 좌측 차로 차량
        grid[20:28, 18:30] = 0.75; cls[20:28, 18:30] = 1
        # 보행자 정류장 부근
        grid[44:50, 60:70] = 0.55; cls[44:50, 60:70] = 4
        # 우측 사이로 끼어드는 오토바이 (배달)
        moto_progress = (np.sin(phase * 0.6) + 1) * 0.5
        moto_row = int(18 + moto_progress * 6)
        grid[moto_row:moto_row + 5, 50:55] = 0.82; cls[moto_row:moto_row + 5, 50:55] = 2
        hotspots = [
            {"class": "bus", "row": 42, "col": 40, "kind": "object", "distance_m": 18.0, "label": "전방 버스 (신호 가림)"},
            {"class": "signal_occluded", "row": 53, "col": 40, "kind": "signal_shadow", "distance_m": 25.0, "label": "🚦 적색 신호 (버스 뒤·API 복원)"},
            {"class": "motorcycle", "row": moto_row + 2, "col": 52, "kind": "object", "distance_m": 10.0, "label": "🏍️ 우측 끼어들기 오토바이"},
            {"class": "pedestrian_zone", "row": 46, "col": 65, "kind": "intent_prior", "distance_m": 22.0, "label": "정류장 보행자 likely"},
        ]

    elif name == "rainy_intersection":
        # 노면 반사 — 전체적으로 약한 noise
        np.random.seed(int(phase * 100) % 1000)
        grid += np.random.rand(80, 80) * 0.10
        # 우산 보행자 — 윤곽 흐림 (intensity 낮음)
        for ped_col in [25, 45, 60]:
            ped_row = 30 + (ped_col % 7)
            grid[ped_row:ped_row + 4, ped_col:ped_col + 4] = 0.65
            cls[ped_row:ped_row + 4, ped_col:ped_col + 4] = 4
        # 전방 차량
        grid[24:30, 32:48] = 0.85; cls[24:30, 32:48] = 1
        # 신호등
        grid[44:50, 38:42] = 0.78; cls[44:50, 38:42] = 5
        # 우천 배달 오토바이 (좌측, 약간 흔들림)
        wobble = int(np.sin(phase * 1.2) * 0.7)
        moto_row = int(15 + (np.cos(phase * 0.4) + 1) * 4)
        grid[moto_row:moto_row + 5, 12 + wobble:17 + wobble] = 0.79
        cls[moto_row:moto_row + 5, 12 + wobble:17 + wobble] = 2
        hotspots = [
            {"class": "vehicle", "row": 27, "col": 40, "kind": "object", "distance_m": 13.5, "label": "전방 차량"},
            {"class": "motorcycle", "row": moto_row + 2, "col": 14, "kind": "object", "distance_m": 9.0, "label": "🏍️ 배달 오토바이 (우천 미끄럼 위험)"},
            {"class": "pedestrian_zone", "row": 32, "col": 27, "kind": "intent_prior", "distance_m": 16.0, "label": "🌧️ 우산 보행자 (좌)"},
            {"class": "pedestrian_zone", "row": 38, "col": 47, "kind": "intent_prior", "distance_m": 19.0, "label": "🌧️ 우산 보행자 (중)"},
            {"class": "pedestrian_zone", "row": 35, "col": 62, "kind": "intent_prior", "distance_m": 17.5, "label": "🌧️ 우산 보행자 (우)"},
            {"class": "signal", "row": 47, "col": 40, "kind": "signal", "distance_m": 23.5, "label": "신호등 (정상 가시)"},
        ]
    else:
        raise ValueError(f"unknown scenario: {name}")

    return grid, cls, hotspots


@router.get("/demo")
def occupancy_demo(scenario: str = "truck_occlusion"):
    """BEV occupancy 데모 — 시나리오별 객체별 클래스 라벨 grid 반환.

    시나리오: truck_occlusion / motorcycle_blindspot / signal_occlusion / rainy_intersection
    """
    import numpy as np
    import time

    if scenario not in _SCENARIOS:
        scenario = "truck_occlusion"
    meta = _SCENARIOS[scenario]

    t = time.time()
    phase = (t % 4.0) / 4.0 * 2 * 3.14159

    grid, cls, hotspots = _build_scene(scenario, phase)
    coarse = grid[::2, ::2]
    coarse_cls = cls[::2, ::2]

    return {
        "scenario_id": scenario,
        "shape": list(grid.shape),
        "cell_m": 0.5,
        "forward_m": 40.0,
        "lateral_m": 20.0,
        "grid_b64": occupancy_service._grid_to_base64(grid),
        "grid_flat": [round(float(v), 3) for v in coarse.flatten()],
        "grid_shape_flat": list(coarse.shape),
        "grid_cell_m_flat": 1.0,
        "class_grid_flat": [int(v) for v in coarse_cls.flatten()],
        "class_legend": {
            "0": "free",
            "1": "vehicle/truck/bus",
            "2": "motorcycle/car-blindspot",
            "3": "occlusion/blindspot",
            "4": "pedestrian-zone",
            "5": "signal",
        },
        "occluded_mass": float(grid.sum()),
        "scenario": {
            "title": meta["title"],
            "narrative": meta["narrative"],
            "auraview_advantage": meta["advantage"],
            "ego_speed_kmh": meta["ego_speed_kmh"],
        },
        "hotspots": hotspots,
        "risk_summary": {
            "p_collision": meta["p_collision"],
            "lead_time_s": meta["lead_time_s"],
            "primary_threat": meta["primary_threat"],
            "recommended_action": meta["recommended_action"],
        },
        "alert_text": meta["alert_text"],
        "available_scenarios": list(_SCENARIOS.keys()),
    }
