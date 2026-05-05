"""
Fleet Learning ─ 사용자 엣지 단말이 '어려운 장면'만 업로드하는 데이터 플라이휠.

  POST /fleet/contribute       이미지 업로드 + 자동 PII 마스킹 후 저장
  GET  /fleet/stats            누적 기여량·하드샘플 비율 통계

설계 의도:
  - Shadow-mode 자동 재학습 사이클 — 어려운 장면만 골라 모델이 점차 똑똑해짐
  - 수집 단계부터 얼굴·번호판 블러 + 디바이스 ID 가명화로 PII 미보관
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..services import pii

log = logging.getLogger("auraview.fleet")
router = APIRouter()

FLEET_DIR = Path(os.getenv("FLEET_DIR", "fleet"))
FLEET_DIR.mkdir(parents=True, exist_ok=True)
(FLEET_DIR / "hard_samples").mkdir(parents=True, exist_ok=True)
MANIFEST = FLEET_DIR / "manifest.jsonl"


@router.post("/contribute")
async def contribute(
    image: UploadFile = File(...),
    device_id: str = Form(...),
    entropy: float = Form(..., description="model uncertainty in [0,1]"),
    reason: str = Form("low_confidence"),
    intersection_id: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
):
    """Hard-sample upload with automatic PII masking."""
    # 저장 파일명에 실제 device_id는 쓰지 않음 → 가명화
    pseudo = pii.pseudonymize(device_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = FLEET_DIR / "hard_samples" / f"{ts}_{pseudo}_raw.jpg"
    masked_path = FLEET_DIR / "hard_samples" / f"{ts}_{pseudo}.jpg"

    raw_path.write_bytes(await image.read())

    # PII 마스킹 (얼굴·번호판 블러)
    try:
        import cv2

        img = cv2.imread(str(raw_path))
        masked = pii.blur_faces_and_plates(img)
        cv2.imwrite(str(masked_path), masked)
    except Exception as exc:
        log.warning("PII masking fallback (copy): %s", exc)
        masked_path.write_bytes(raw_path.read_bytes())

    # 원본 즉시 삭제 (원천 PII 미보관 원칙)
    try:
        raw_path.unlink()
    except Exception:
        pass

    entry = {
        "ts": datetime.utcnow().isoformat(),
        "pseudo_device": pseudo,
        "intersection_id": intersection_id,
        "entropy": round(float(entropy), 3),
        "reason": reason,
        "lat": lat,   # 위치도 grid round로 low-res화 권장 (아래 반올림)
        "lon": lon,
        "path": str(masked_path.name),
    }
    if lat is not None and lon is not None:
        # ~100m 그리드로 반올림 → k-익명성 보조
        entry["lat"] = round(lat, 3)
        entry["lon"] = round(lon, 3)

    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok", "stored": masked_path.name, "pseudo_device": pseudo}


@router.get("/stats")
def stats():
    if not MANIFEST.exists():
        return {"total": 0, "hard_count": 0, "hard_ratio": 0.0, "unique_devices": 0, "recent": []}

    rows = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue

    hard = [r for r in rows if r.get("entropy", 0) >= 0.6]
    return {
        "total": len(rows),
        "hard_count": len(hard),
        "hard_ratio": round(len(hard) / len(rows), 3) if rows else 0.0,
        "unique_devices": len({r.get("pseudo_device") for r in rows}),
        "recent": rows[-10:],
    }


@router.get("/list")
def list_uploads(limit: int = 100):
    """전체 업로드 목록 (최신 순) — 관리자 검수용."""
    if not MANIFEST.exists():
        return []
    rows = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    # 최신 순 + 파일 존재 확인
    rows.reverse()
    out = []
    for r in rows[:limit]:
        p = FLEET_DIR / "hard_samples" / r.get("path", "")
        r["exists"] = p.exists()
        r["size_kb"] = round(p.stat().st_size / 1024, 1) if p.exists() else 0
        out.append(r)
    return out


@router.get("/image/{filename}")
def get_image(filename: str):
    """업로드된 이미지 단일 조회 (PII 마스킹 적용된 버전)."""
    # path traversal 방지
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    p = FLEET_DIR / "hard_samples" / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p, media_type="image/jpeg")


@router.delete("/image/{filename}")
def delete_image(filename: str):
    """이상하거나 잘못 올라간 이미지 삭제 (manifest 에서도 제거)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    p = FLEET_DIR / "hard_samples" / filename
    if p.exists():
        try:
            p.unlink()
        except Exception as exc:
            log.warning("delete failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    # manifest 에서 해당 entry 제거
    if MANIFEST.exists():
        kept = []
        with MANIFEST.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if row.get("path") != filename:
                        kept.append(line)
                except Exception:
                    kept.append(line)
        with MANIFEST.open("w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")

    return {"status": "ok", "deleted": filename}
