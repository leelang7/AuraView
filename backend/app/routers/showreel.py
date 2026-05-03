"""
Showreel — 발표용 합본 시연 영상.

  POST /showreel/build              비동기 빌드 큐잉 → job_id 반환 (202)
                                    Query: ?limit=N (기본 SHOWREEL_MAX_SCENARIOS=3)
  GET  /showreel/jobs/{job_id}      특정 빌드 작업 상태 (queued/running/done/error)
  GET  /showreel/list               최근 합본 목록
  GET  /showreel/latest             최신 합본 메타 (없으면 placeholder, 자동 빌드 X)
  GET  /showreel/latest.mp4         최신 합본 mp4 로 302 redirect — 슬라이드/키오스크 임베드
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from ..services import showreel as showreel_service

router = APIRouter()


@router.post("/build")
def build(limit: Optional[int] = None):
    """비동기 빌드 큐잉 — HTTP 워커 블로킹 방지 (소형 EC2 OOM 회피)."""
    try:
        job = showreel_service.enqueue_build(limit=limit)
        return JSONResponse(content=job, status_code=202)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = showreel_service.read_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/list")
def list_recent():
    return {"items": showreel_service.list_recent()}


@router.get("/latest")
def latest():
    return showreel_service.latest()


@router.get("/latest.mp4")
def latest_mp4():
    """슬라이드/키오스크 <video> 안정 임베드 URL → 최신 영상으로 redirect.

    합본 없으면 404 (자동 빌드 X — 워커 블로킹 방지).
    """
    meta = showreel_service.latest()
    url = meta.get("video_url") if isinstance(meta, dict) else None
    if not url:
        raise HTTPException(status_code=404, detail="no showreel — POST /showreel/build 로 생성")
    return RedirectResponse(url=url, status_code=302)
