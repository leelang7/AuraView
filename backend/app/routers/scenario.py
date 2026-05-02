"""
Accident Reenactment endpoints.

  POST /scenario/reenact     video 또는 preset → 재현 영상 mp4 생성
  GET  /scenario/list        최근 생성물 목록
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..services import scenario as scenario_service

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/reenact")
async def reenact(
    video: Optional[UploadFile] = File(None),
    preset: Optional[str] = Form(None),
):
    if not video and not preset:
        raise HTTPException(status_code=400, detail="video 또는 preset 중 하나는 필수")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if video:
        in_path = os.path.join(UPLOAD_DIR, f"{ts}_scn_in.mp4")
        with open(in_path, "wb") as f:
            f.write(await video.read())
        out_name = f"{ts}_reenact"
        try:
            result = scenario_service.reenact_from_video(in_path, out_name=out_name)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"reenactment failed: {exc}")
        return result.to_dict()

    out_name = f"{ts}_synth_{preset}"
    try:
        result = scenario_service.synthesize(preset=preset, out_name=out_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"synthesis failed: {exc}")
    return result.to_dict()


@router.get("/list")
def scenario_list():
    return {"items": scenario_service.list_recent()}


@router.get("/presets")
def scenario_presets():
    return {
        "presets": [
            {"id": "crosswalk_truck", "title": "횡단보도 · 대형차 가림 · 보행자 출현"},
            {"id": "motorcycle_blindspot", "title": "사각지대 · 이륜차 접근"},
            {"id": "signal_occluded", "title": "신호 가림 + 급감속"},
            {"id": "v2v_collab", "title": "⭐ V2V 협업 인지 (마주오는 차 시점)"},
        ]
    }
