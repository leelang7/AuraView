"""
Showreel — 발표용 합본 시연 영상.

  POST /showreel/build       3개 시나리오 + 타이틀 카드 합본 mp4 생성
  GET  /showreel/list        최근 합본 목록
  GET  /showreel/latest      최신 합본 메타 (없으면 즉시 빌드)
  GET  /showreel/latest.mp4  최신 합본 mp4 로 302 redirect (슬라이드/키오스크 임베드용)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

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


@router.get("/latest")
def latest():
    """가장 최근 합본 영상 메타 — 없으면 자동 빌드."""
    return showreel_service.latest()


@router.get("/latest.mp4")
def latest_mp4():
    """슬라이드/키오스크 <video> 가 직접 임베드할 수 있는 안정 URL → 최신 영상으로 redirect.

    합본 영상이 아직 없으면 404 (자동 빌드 X — 워커 블로킹 방지).
    """
    meta = showreel_service.latest()
    url = meta.get("video_url") if isinstance(meta, dict) else None
    if not url:
        raise HTTPException(status_code=404, detail="no showreel — POST /showreel/build 로 생성")
    return RedirectResponse(url=url, status_code=302)
