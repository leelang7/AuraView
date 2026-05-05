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
    "right_turn_pedestrian": {
        "title": "우회전 진행 중 우측 횡단보도 보행자 — A필러 사각",
        "narrative": "ego 우회전 진행 중, 가로 도로 우측 횡단보도를 건너는 보행자 3명. A필러로 운전자 미인지 + ego 회전 경로와 정확히 충돌.",
        "advantage": "BEV 우측 횡단보도 prior + 회전 경로 sweep zone — 사각 100% 커버 (한국 대법 판례: 우회전 시 보행자 우선)",
        "ego_speed_kmh": 12,
        "p_collision": 0.81,
        "lead_time_s": 2.6,
        "primary_threat": "우측 횡단보도 보행자 (회전 경로 위)",
        "recommended_action": "즉시 정지 + 보행자 통과 후 진행",
        "alert_text": "🚸 우회전 보행자 발견 — 즉시 정지",
    },
}


def _build_scene(name: str, phase: float):
    """시나리오 이름 + phase(0~2π) → (grid prob, class_grid, hotspots).

    class_grid: 0=free, 1=truck/bus, 2=motorcycle/car, 3=occlusion, 4=pedestrian, 5=signal

    좌표: 80×80, 0.5m/cell, ego facing +row 방향 (row 0 = ego, row 79 = far 40m)
    차로: col 32~38 (좌차로 ego 진행), col 38~44 (우차로 ego 진행)
    ego 위치: row 0, col 39 (자차 차로 우측)

    차량 형상 가이드 (진행방향 +row, 가로 +col):
      트럭: 16 rows × 5 cols (8m × 2.5m)
      버스: 22 rows × 6 cols (11m × 3m)
      차량: 9 rows × 4 cols (4.5m × 2m)
      이륜: 5 rows × 2 cols (2.5m × 1m)
    """
    import numpy as np

    grid = np.zeros((80, 80), dtype="float32")
    cls = np.zeros((80, 80), dtype="int8")  # class label per cell

    if name == "truck_occlusion":
        # 트럭 — 우측 차로 (col 38~43, 8m 길이) 전방 11~19m
        truck_off = int(np.sin(phase) * 0.8)
        grid[22:38, 38 + truck_off:43 + truck_off] = 0.92
        cls[22:38, 38 + truck_off:43 + truck_off] = 1
        # 트럭 뒤 occlusion shadow (트럭 뒤 가려진 영역, 동일 col, row 38~58)
        grid[38:58, 38 + truck_off:43 + truck_off] = 0.55
        cls[38:58, 38 + truck_off:43 + truck_off] = 3
        # 횡단보도 부근 보행자 zone (row 50~55, col 35~46)
        ped_intensity = 0.55 + 0.15 * (np.cos(phase) + 1) * 0.5
        grid[50:55, 35:46] = ped_intensity; cls[50:55, 35:46] = 4
        # 좌측 차로 차량 (col 33~37, row 18~27)
        grid[18:27, 33:37] = 0.85; cls[18:27, 33:37] = 1
        # 좌측 옆 차로 이륜차 (col 30~32, 진행방향 길게 row 14~19)
        moto_progress = (np.sin(phase * 0.5) + 1) * 0.5
        moto_row = int(12 + moto_progress * 6)
        grid[moto_row:moto_row + 5, 30:32] = 0.85
        cls[moto_row:moto_row + 5, 30:32] = 2
        # 신호등 (트럭 뒤 멀리 row 60~62, col 38~40)
        grid[60:62, 38:40] = 0.40 + 0.15 * abs(np.sin(phase * 1.5))
        cls[60:62, 38:40] = 5
        hotspots = [
            {"class": "truck", "row": 30, "col": 40, "kind": "object", "distance_m": 15.0, "label": "전방 트럭 (시야 가림)"},
            {"class": "occlusion", "row": 48, "col": 40, "kind": "occluded_shadow", "distance_m": 24.0, "label": "트럭 뒤 unknown 영역"},
            {"class": "vehicle", "row": 22, "col": 35, "kind": "object", "distance_m": 11.0, "label": "좌측 차로 차량"},
            {"class": "motorcycle", "row": moto_row + 2, "col": 31, "kind": "object", "distance_m": 8.0, "label": "🏍️ 좌측 옆 이륜차"},
            {"class": "pedestrian_zone", "row": 53, "col": 40, "kind": "intent_prior", "distance_m": 26.5, "label": "⭐ 횡단보도 보행자 likely"},
            {"class": "signal_occluded", "row": 61, "col": 39, "kind": "signal_shadow", "distance_m": 30.5, "label": "신호등 (가림)"},
        ]

    elif name == "motorcycle_blindspot":
        # 자차 좌측 사각지대 영역 — 옆구리 (row 4~14, col 32~36)
        grid[4:14, 32:36] = 0.30; cls[4:14, 32:36] = 3
        # 좌측 사각지대 이륜차 — 자차 옆구리 (col 32~34, 진행방향 row 4~9 빠르게 접근)
        moto_progress = (phase / (2 * 3.14159))
        moto_row = int(2 + moto_progress * 8)
        grid[moto_row:moto_row + 5, 32:34] = 0.92
        cls[moto_row:moto_row + 5, 32:34] = 2
        # 우측 차로 차량 (col 41~45, row 18~27)
        grid[18:27, 41:45] = 0.85; cls[18:27, 41:45] = 1
        # 좌측 차로 차량 (사각지대 너머, col 33~37, row 22~31)
        grid[22:31, 33:37] = 0.78; cls[22:31, 33:37] = 1
        # 전방 신호등 (col 38~40, row 50~52)
        grid[50:52, 38:40] = 0.78; cls[50:52, 38:40] = 5
        hotspots = [
            {"class": "motorcycle", "row": moto_row + 2, "col": 33, "kind": "object", "distance_m": 4.0, "label": "⚠️ 좌측 사각지대 이륜차 (4m)"},
            {"class": "blindspot_zone", "row": 9, "col": 34, "kind": "blindspot", "distance_m": 4.5, "label": "백미러 사각지대 영역"},
            {"class": "vehicle", "row": 22, "col": 43, "kind": "object", "distance_m": 11.0, "label": "우측 차로 차량"},
            {"class": "vehicle", "row": 26, "col": 35, "kind": "object", "distance_m": 13.0, "label": "좌측 차로 차량"},
            {"class": "signal", "row": 51, "col": 39, "kind": "signal", "distance_m": 25.5, "label": "전방 신호등"},
        ]

    elif name == "signal_occlusion":
        # 버스 — 우측 차로 (col 38~44, 11m 길이, 전방 18~29m → row 36~58)
        bus_off = int(np.sin(phase * 0.8) * 0.5)
        grid[36:58, 38 + bus_off:44 + bus_off] = 0.94
        cls[36:58, 38 + bus_off:44 + bus_off] = 1
        # 버스 뒤 가려진 신호등 (row 64~66, col 38~40, 멀리 32m)
        sig_state = (phase % 2) > 1
        grid[64:66, 38:40] = 0.88 if sig_state else 0.60
        cls[64:66, 38:40] = 5
        # 좌측 차로 차량 (col 33~37, row 22~31)
        grid[22:31, 33:37] = 0.82; cls[22:31, 33:37] = 1
        # 우측 끼어드는 배달 오토바이 (col 45~47, row 16~21)
        moto_progress = (np.sin(phase * 0.6) + 1) * 0.5
        moto_row = int(14 + moto_progress * 6)
        grid[moto_row:moto_row + 5, 45:47] = 0.85
        cls[moto_row:moto_row + 5, 45:47] = 2
        # 우측 인도 정류장 보행자 zone (col 50~57, row 44~50)
        grid[44:50, 50:57] = 0.55; cls[44:50, 50:57] = 4
        hotspots = [
            {"class": "bus", "row": 47, "col": 41, "kind": "object", "distance_m": 23.5, "label": "전방 버스 (신호 가림)"},
            {"class": "signal_occluded", "row": 65, "col": 39, "kind": "signal_shadow", "distance_m": 32.5, "label": "🚦 적색 신호 (버스 뒤·API 복원)"},
            {"class": "vehicle", "row": 26, "col": 35, "kind": "object", "distance_m": 13.0, "label": "좌측 차로 차량"},
            {"class": "motorcycle", "row": moto_row + 2, "col": 46, "kind": "object", "distance_m": 9.5, "label": "🏍️ 우측 끼어들기 이륜차"},
            {"class": "pedestrian_zone", "row": 47, "col": 53, "kind": "intent_prior", "distance_m": 23.5, "label": "정류장 보행자 likely"},
        ]

    elif name == "rainy_intersection":
        # 노면 반사 — 약한 noise
        np.random.seed(int(phase * 100) % 1000)
        grid += np.random.rand(80, 80) * 0.08
        # 전방 차량 (우차로 col 38~42, row 24~33)
        grid[24:33, 38:42] = 0.85; cls[24:33, 38:42] = 1
        # 좌측 차로 차량 (col 33~37, row 28~37)
        grid[28:37, 33:37] = 0.80; cls[28:37, 33:37] = 1
        # 신호등 (col 38~40, row 50~52)
        grid[50:52, 38:40] = 0.78; cls[50:52, 38:40] = 5
        # 횡단보도 부근 우산 보행자 (3명, row 48~52)
        for (pc, pr) in [(33, 48), (39, 50), (46, 49)]:
            grid[pr:pr + 4, pc:pc + 3] = 0.65
            cls[pr:pr + 4, pc:pc + 3] = 4
        # 우천 배달 오토바이 (col 30~32 좌측 옆 차로, 흔들림)
        wobble = int(np.sin(phase * 1.2) * 0.5)
        moto_row = int(13 + (np.cos(phase * 0.4) + 1) * 4)
        grid[moto_row:moto_row + 5, 30 + wobble:32 + wobble] = 0.85
        cls[moto_row:moto_row + 5, 30 + wobble:32 + wobble] = 2
        hotspots = [
            {"class": "vehicle", "row": 28, "col": 40, "kind": "object", "distance_m": 14.0, "label": "전방 차량"},
            {"class": "vehicle", "row": 32, "col": 35, "kind": "object", "distance_m": 16.0, "label": "좌측 차로 차량"},
            {"class": "motorcycle", "row": moto_row + 2, "col": 31, "kind": "object", "distance_m": 9.0, "label": "🏍️ 배달 이륜 (우천 미끄럼)"},
            {"class": "pedestrian_zone", "row": 50, "col": 34, "kind": "intent_prior", "distance_m": 25.0, "label": "🌧️ 우산 보행자 (좌)"},
            {"class": "pedestrian_zone", "row": 52, "col": 40, "kind": "intent_prior", "distance_m": 26.0, "label": "🌧️ 우산 보행자 (중)"},
            {"class": "pedestrian_zone", "row": 51, "col": 47, "kind": "intent_prior", "distance_m": 25.5, "label": "🌧️ 우산 보행자 (우)"},
            {"class": "signal", "row": 51, "col": 39, "kind": "signal", "distance_m": 25.5, "label": "신호등"},
        ]
    elif name == "right_turn_pedestrian":
        # ego 우회전 시나리오 — 핵심 3가지
        # 1) ego 우측 A필러 사각지대 (운전자 못 보는 영역)
        # 2) 우측 횡단보도 보행자 (회전 경로 위 — 정지 필요)
        # 3) 마주오는 차량 (북→남, ego 도로 반대편 차로) — 회전 시 양보 또는 충돌 위험

        # A. ego 우측 A필러 사각지대
        grid[16:48, 50:58] = 0.30; cls[16:48, 50:58] = 3

        # B. 우측 횡단보도 보행자 (북→남 횡단)
        ped_progress = (np.sin(phase * 0.5) + 1) * 0.5
        ped_row = int(50 + ped_progress * 12)
        grid[ped_row:ped_row + 3, 52:54] = 0.92
        cls[ped_row:ped_row + 3, 52:54] = 4

        # C. 마주오는 차량 (반대편 차로) — 북에서 남으로
        # ★ 중앙선 (col 39~40) 침범 X — col 31~36 으로 안전 거리 확보
        # 차로: col 31~36 (5 cols = 2.5m, ego 도로 좌측 차로)
        oncoming_progress = (phase / (2 * 3.14159)) % 1
        oncoming_row = int(70 - oncoming_progress * 70)
        if 0 <= oncoming_row <= 68:
            r1 = max(0, oncoming_row)
            r2 = min(80, oncoming_row + 12)
            grid[r1:r2, 31:36] = 0.92  # col 31~35 (중앙선 col 39 와 거리 확보)
            cls[r1:r2, 31:36] = 1

        hotspots = [
            {"class": "blindspot_zone", "row": 32, "col": 54, "kind": "blindspot", "distance_m": 16.0,
             "label": "⚠️ 우측 A필러 사각지대"},
            {"class": "pedestrian_zone", "row": ped_row + 1, "col": 53, "kind": "intent_prior",
             "distance_m": (ped_row + 1) * 0.5, "label": "🚸 우측 횡단보도 보행자 (회전 경로)"},
            {"class": "vehicle", "row": oncoming_row + 6, "col": 33, "kind": "object",
             "distance_m": max(0, (oncoming_row + 6) * 0.5), "label": "🚗 마주오는 차량 (북→남)"},
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
