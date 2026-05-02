"""
Showreel — 발표용 합본 시연 영상.

  POST /showreel/build       3개 시나리오 + 타이틀 카드 합본 mp4 생성
  GET  /showreel/list        최근 합본 목록
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services import showreel as showreel_service

router = APIRouter()


@router.post("/build")
def build():
    try:
        return showreel_service.build()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/list")
def list_recent():
    return {"items": showreel_service.list_recent()}
