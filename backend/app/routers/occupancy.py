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
    import numpy as np
    fake_grid = np.zeros((80, 80), dtype="float32")
    fake_grid[50:60, 30:50] = 0.9
    fake_grid[60:75, 35:45] = 0.45  # occlusion shadow
    return {
        "shape": list(fake_grid.shape),
        "cell_m": 0.5,
        "forward_m": 40.0,
        "lateral_m": 20.0,
        "grid_b64": occupancy_service._grid_to_base64(fake_grid),
        "hotspots": [{"class": "truck", "row": 55, "col": 40, "kind": "occluded_shadow"}],
        "occluded_mass": float(fake_grid.sum()),
    }
