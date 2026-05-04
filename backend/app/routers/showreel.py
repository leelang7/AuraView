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


@router.post("/cleanup")
def cleanup(keep: int = 1):
    """오래된 합본 영상 정리 — 최신 keep 개만 남기고 삭제. 기본 keep=1."""
    result = showreel_service.cleanup_old(keep=keep)
    return result


@router.get("/latest")
def latest():
    return showreel_service.latest()


@router.get("/debug-font")
def debug_font():
    """현재 한글 렌더에 쓰이는 폰트 진단 + 강제 다운로드 시도."""
    import glob, os, subprocess
    from pathlib import Path
    backend_root = Path(showreel_service.__file__).resolve().parent.parent.parent
    asset_dir = backend_root / "assets"

    info = {
        "selected": showreel_service._FONT_PATH,
        "backend_root": str(backend_root),
        "cwd": os.getcwd(),
        "asset_dir": str(asset_dir),
        "asset_dir_exists": asset_dir.exists(),
        "asset_dir_contents": [str(p) for p in asset_dir.glob("*")] if asset_dir.exists() else [],
        "candidates_found": [
            p for p in [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            ] if Path(p).exists()
        ],
        "all_fonts_ttf": glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)[:10] +
                        glob.glob("/usr/share/fonts/**/*.otf", recursive=True)[:10] +
                        glob.glob("/usr/share/fonts/**/*.ttc", recursive=True)[:10],
        "korean_glyph_test": None,
        "force_download_attempt": None,
    }

    # Try forcing the download right now
    target = asset_dir / "NotoSansKR-Regular.otf"
    if not (target.exists() and target.stat().st_size > 100_000):
        try:
            asset_dir.mkdir(parents=True, exist_ok=True)
            import urllib.request, time
            t0 = time.time()
            urllib.request.urlretrieve(showreel_service._BUNDLED_FONT_URL, str(target))
            elapsed = time.time() - t0
            sz = target.stat().st_size if target.exists() else 0
            info["force_download_attempt"] = {
                "url": showreel_service._BUNDLED_FONT_URL,
                "elapsed_s": round(elapsed, 2),
                "saved_size": sz,
                "ok": sz > 100_000,
            }
            if sz > 100_000:
                # 모듈 _FONT_PATH 갱신
                showreel_service._FONT_PATH = str(target)
                info["selected"] = showreel_service._FONT_PATH
        except Exception as exc:
            info["force_download_attempt"] = {"error": str(exc)}

    if showreel_service._FONT_PATH:
        try:
            from PIL import ImageFont
            f = ImageFont.truetype(showreel_service._FONT_PATH, 30)
            mask = f.getmask("한") if hasattr(f, "getmask") else None
            info["korean_glyph_test"] = {
                "mask_size": list(mask.size) if mask else None,
                "has_glyph": (mask.size != (0, 0)) if mask else False,
            }
        except Exception as exc:
            info["korean_glyph_test"] = {"error": str(exc)}
    return info


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
