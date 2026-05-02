"""
Collaborative Perception 엔드포인트 — V2V + Bus + Bidirectional.

  POST /collab/v2v/broadcast              내 detection 결과를 V2V 풀에 게시
  GET  /collab/v2v/intersection/{id}      해당 교차로의 최근 V2V 메시지
  GET  /collab/v2v/stats                  V2V 풀 통계

  POST /collab/bus-context                현장 bus 검출 + 내 위치 → 정류장 prior 분석
  POST /collab/bidirectional              V2V peers + VDS → 상행/하행 위험 추정

  POST /collab/fused-occupancy            업로드 1장 → HydraNet + Occupancy + V2V + Bus + Bidir
                                          모두 결합한 최종 점유격자 + 위험확률
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile

from ..services import bidirectional as bidir_service
from ..services import bus_aware as bus_service
from ..services import intent as intent_service
from ..services import occupancy as occupancy_service
from ..services import public_api
from ..services import risk_transformer as risk_service
from ..services import v2v as v2v_service
from ..services.hydranet import get_default as get_hydranet

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────────
# V2V
# ─────────────────────────────────────────────────────────────────

@router.post("/v2v/broadcast")
def v2v_broadcast(payload: Dict[str, Any] = Body(...)):
    if "intersection_id" not in payload:
        raise HTTPException(400, detail="intersection_id required")
    return v2v_service.publish(payload)


@router.get("/v2v/intersection/{intersection_id}")
def v2v_intersection(intersection_id: str):
    msgs = v2v_service.fetch(intersection_id)
    return {"intersection_id": intersection_id, "count": len(msgs), "messages": msgs}


@router.get("/v2v/stats")
def v2v_stats():
    return v2v_service.stats()


@router.post("/v2v/seed-demo")
def v2v_seed_demo(intersection_id: str = "1007", lat: float = 37.5601, lon: float = 127.0410):
    """시연용: 같은 교차로에 마주오는 차 2대 + 같은 방향 1대 가짜 메시지 게시."""
    import random
    msgs = [
        {  # 마주오는 차 1 — 보행자 본 상태
            "device_id": "demo-peer-A", "intersection_id": intersection_id,
            "lat": lat + 0.0003, "lon": lon - 0.0001, "heading_deg": 90,
            "speed_kmh": 12.0, "decel_g": 0.32,
            "detections": [{"class": "person", "conf": 0.91, "rel_lat": -0.00006, "rel_lon": 0.00002, "width_m": 0.6}],
            "occluded_mass": 70.0,
        },
        {  # 마주오는 차 2 — 정지
            "device_id": "demo-peer-B", "intersection_id": intersection_id,
            "lat": lat + 0.0004, "lon": lon - 0.00015, "heading_deg": 95,
            "speed_kmh": 0.5, "decel_g": 0.45,
            "detections": [{"class": "person", "conf": 0.78, "rel_lat": -0.00005, "rel_lon": 0.00001, "width_m": 0.55}],
            "occluded_mass": 90.0,
        },
        {  # 같은 방향 차
            "device_id": "demo-peer-C", "intersection_id": intersection_id,
            "lat": lat - 0.0002, "lon": lon + 0.00005, "heading_deg": 270,
            "speed_kmh": 24.0, "decel_g": 0.05,
            "detections": [],
            "occluded_mass": 35.0,
        },
    ]
    [v2v_service.publish(m) for m in msgs]
    return {"seeded": len(msgs), "intersection_id": intersection_id}


# ─────────────────────────────────────────────────────────────────
# Bus context
# ─────────────────────────────────────────────────────────────────

@router.post("/bus-context")
def bus_context(payload: Dict[str, Any] = Body(...)):
    """
    payload = {
      "bus_detections": [{"class_name":"bus","confidence":0.78,"bbox_xyxy":[...]}, ...],
      "ego_lat": 37.56, "ego_lon": 127.04, "ego_speed_kmh": 4.0
    }
    """
    bus_dets = payload.get("bus_detections", [])
    ctx = bus_service.analyze(
        bus_detections=bus_dets,
        ego_lat=payload.get("ego_lat"),
        ego_lon=payload.get("ego_lon"),
        ego_speed_kmh=payload.get("ego_speed_kmh"),
    )
    return ctx.to_dict()


# ─────────────────────────────────────────────────────────────────
# Bidirectional
# ─────────────────────────────────────────────────────────────────

@router.post("/bidirectional")
def bidirectional(payload: Dict[str, Any] = Body(...)):
    """
    payload = {"intersection_id":"1007", "ego_heading_deg":270}
    """
    iid = payload.get("intersection_id", "")
    peers = v2v_service.fetch(iid) if iid else []
    vds_raw = public_api.fetch_vds_traffic()
    vds_list = vds_raw.get("list", []) if isinstance(vds_raw, dict) else []
    return bidir_service.analyze(
        peers=peers,
        ego_heading_deg=payload.get("ego_heading_deg"),
        vds_records=vds_list,
    ).to_dict()


# ─────────────────────────────────────────────────────────────────
# Fused Occupancy (E2E demo)
# ─────────────────────────────────────────────────────────────────

@router.post("/fused-occupancy")
async def fused_occupancy(
    image: UploadFile = File(...),
    intersection_id: str = Form("1007"),
    ego_lat: float = Form(37.5601),
    ego_lon: float = Form(127.0410),
    ego_heading_deg: float = Form(270.0),
    ego_speed_kmh: float = Form(4.0),
    duration: float = Form(3.0),
    obstacle_type: str = Form("bus"),
    signal_state: str = Form("stop-And-Remain"),
):
    """이미지 1장 + V2V + Bus + Bidirectional 모든 신호를 결합한 최종 occupancy + risk."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(UPLOAD_DIR, f"{ts}_fused.jpg")
    with open(save_path, "wb") as f:
        f.write(await image.read())

    # 1) HydraNet
    hyd = get_hydranet()
    pred = hyd.infer(save_path)

    # 2) Bus context
    bus_ctx = bus_service.analyze(
        bus_detections=pred.detections,
        ego_lat=ego_lat, ego_lon=ego_lon, ego_speed_kmh=ego_speed_kmh,
    )

    # 3) Local occupancy
    dets = [
        occupancy_service.Detection(
            class_name=d["class_name"], confidence=d["confidence"],
            bbox_xyxy=d["bbox_xyxy"], image_size=d["image_size"]
        )
        for d in pred.detections
    ] + [
        occupancy_service.Detection(
            class_name=d["class_name"], confidence=d["confidence"],
            bbox_xyxy=d["bbox_xyxy"], image_size=d["image_size"]
        )
        for d in pred.vru_detections
    ]
    occ = occupancy_service.compute_occupancy(
        detections=dets,
        vehicle_detected=len(pred.detections) > 0,
        signal_detected=len(pred.signals) > 0,
    )

    # 4) Bus prior 가산
    bus_boosted_cells = bus_service.boost_occupancy(occ.grid, bus_ctx)

    # 5) V2V 결합
    v2v_res = v2v_service.merge_into_occupancy(
        occ.grid, ego_lat=ego_lat, ego_lon=ego_lon, ego_heading=ego_heading_deg,
        intersection_id=intersection_id,
        cell_m=occ.cell_m, forward_m=occ.forward_m, lateral_m=occ.lateral_m,
    )

    # 6) Bidirectional
    peers = v2v_service.fetch(intersection_id)
    vds_raw = public_api.fetch_vds_traffic()
    vds_list = vds_raw.get("list", []) if isinstance(vds_raw, dict) else []
    bidir = bidir_service.analyze(
        peers=peers, ego_heading_deg=ego_heading_deg, vds_records=vds_list,
    )

    # 7) Intent
    intent = intent_service.predict_intent(
        occupancy_grid=occ.grid,
        taas_accident_count=2,
        signal_state=signal_state,
        vru_seen=len(pred.vru_detections),
    )

    # 8) Risk — V2V/Bus/Bidir 신호 가산
    risk = risk_service.predict(risk_service.RiskInput(
        duration=duration,
        vehicle_cnt=len(pred.detections),
        vru_cnt=len(pred.vru_detections),
        occluded_mass=occ.occluded_mass + v2v_res.added_mass,
        signal_state=signal_state,
        obstacle_type=obstacle_type,
        taas_nearby=2,
        incident_flag=bidir.hazard_probability > 0.45,
    ))
    # bidirectional/bus 가 위험을 명시적으로 가산
    p_collision = min(0.99, risk.p_collision + 0.20 * bidir.hazard_probability + 0.15 * bus_ctx.pedestrian_prior_boost)

    return {
        "hydranet": pred.summary(),
        "bus_context": bus_ctx.to_dict(),
        "v2v": {**v2v_res.to_dict(), "peer_count": len(peers)},
        "bidirectional": bidir.to_dict(),
        "intent": intent.to_dict(),
        "occupancy": occ.to_dict(),
        "risk_local_only": risk.to_dict(),
        "risk_fused": {
            "p_collision": round(p_collision, 4),
            "lift_from_v2v_bus_bidir": round(p_collision - risk.p_collision, 4),
            "explanation": (
                f"local p={risk.p_collision:.3f} + bus prior +{0.15 * bus_ctx.pedestrian_prior_boost:.3f} "
                f"+ bidirectional +{0.20 * bidir.hazard_probability:.3f} → fused {p_collision:.3f}"
            ),
        },
        "boosted_cells": {
            "bus": bus_boosted_cells,
            "v2v": v2v_res.boosted_cells,
        },
    }
