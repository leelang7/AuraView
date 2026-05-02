"""
데이터안심구역 반입/조회 엔드포인트.

  POST /dsz/verify          안심구역에서 반출한 결과물(JSON) 해시 검증 + 등록
  GET  /dsz/artifacts       등록된 안심구역 결합분석 결과물 목록
  POST /dsz/join/taas-vds   (시연용) 로컬 가짜 TAAS × VDS 결합 샘플 수행

관련 표준: 국토교통 데이터안심구역 반입·결합·반출 절차.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException, UploadFile, File
import os
from datetime import datetime

from ..services import dsz_adapter
from ..services import pii
from ..services import public_api

router = APIRouter()


@router.get("/artifacts")
def list_artifacts():
    return {"artifacts": dsz_adapter.list_imported()}


@router.post("/verify")
async def verify_artifact(file: UploadFile = File(...)):
    tmp_dir = Path("dsz_exports/_incoming")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = tmp_dir / f"{ts}_{file.filename}"
    path.write_bytes(await file.read())

    try:
        artifact = dsz_adapter.verify_artifact(str(path))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return artifact.to_dict()


@router.post("/join/taas-vds")
def join_taas_vds_demo():
    """
    안심구역 내 결합을 가정한 **로컬 시연용** 경로.
    실제 제출물에서는 DSZ 내부에서 수행된 결과물만 `/dsz/verify`로 등록해야 함.
    """
    taas = public_api.fetch_taas_accidents().get("accidents", [])
    vds = public_api.fetch_vds_traffic().get("list", [])

    # 결합키 포맷 정규화 (가짜 district_code/date_hour/link_id 주입)
    for i, a in enumerate(taas):
        a.setdefault("district_code", "11680")
        a.setdefault("date_hour", "2024-08-14-18")
        a.setdefault("link_id", "1000000100")
    for j, v in enumerate(vds):
        v.setdefault("district_code", "11680")
        v.setdefault("date_hour", "2024-08-14-18")
        v.setdefault("link_id", "1000000100")

    joined = pii.join_taas_vds(taas, vds)
    return {
        "joined_count": len(joined),
        "note": "k-익명성 통과 후 집계 결과만 반환 (시연용)",
        "sample": joined[:5],
    }
