"""
발표용 합본 시연 영상 (Showreel) 생성기.

흐름:
  1. 3개 합성 시나리오 자동 생성 (없으면)
  2. 타이틀 카드 1장 + 시나리오별 인트로 카드 + mp4 본편 + 마무리 카드
  3. ffmpeg concat → 1개 mp4

출력 길이: 약 90~120초.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from . import scenario as scenario_service

log = logging.getLogger("auraview.showreel")

OUT_DIR = Path(os.getenv("SHOWREEL_DIR", "uploads/showreel"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
JOB_DIR = OUT_DIR / "_jobs"
JOB_DIR.mkdir(parents=True, exist_ok=True)

W = int(os.getenv("SHOWREEL_W", "1280"))
H = int(os.getenv("SHOWREEL_H", "720"))
FPS = int(os.getenv("SHOWREEL_FPS", "24"))
# 한 합본에 들어갈 시나리오 수 — 작은 EC2 (1~2GB RAM) 에서 OOM 방지를 위해 기본 3.
MAX_SCENARIOS = int(os.getenv("SHOWREEL_MAX_SCENARIOS", "3"))

# 동시 빌드 1건만 허용 — 락 파일 방식
_BUILD_LOCK = threading.Lock()

PRESETS: List[Tuple[str, str, str]] = [
    ("crosswalk_truck",
     "횡단보도 · 대형차 가림 · 보행자 출현",
     "AuraView 가 있었다면 N초 먼저 경고했을까?"),
    ("motorcycle_blindspot",
     "사각지대 · 이륜차 접근",
     "Occupancy Network 가 보이지 않는 영역을 확률로 채운다"),
    ("signal_occluded",
     "신호 가림 + 전방 급감속",
     "공공 신호 API 와 결합해 가려진 신호를 복원"),
    ("v2v_collab",
     "⭐ V2V 협업 인지 — 마주오는 차의 시점",
     "Tesla 도 못 하는 한국 도로 협업: 다른 차의 시점이 내 사각지대를 메운다"),
    ("rainy_intersection",
     "🌧️ 우천 + 우산 보행자",
     "시야 가림 환경에서도 보행자 의도 추적"),
    ("night_blindspot",
     "🌙 야간 사각지대 + 마주오는 헤드라이트",
     "어두운 도로의 그림자 영역까지 occupancy 로 채운다"),
]


def _draw_card(title: str, sub: str = "", footer: str = "", duration_s: float = 2.5,
               accent: Tuple[int, int, int] = (255, 200, 0)) -> List[np.ndarray]:
    """단순한 다크 타이틀 카드 프레임 시퀀스. (1920x1080 기준)"""
    s = W / 960.0   # 스케일 팩터
    frames = int(duration_s * FPS)
    out: List[np.ndarray] = []
    for i in range(frames):
        img = np.zeros((H, W, 3), dtype=np.uint8)
        # 그라디언트 배경
        for y in range(H):
            t = y / H
            img[y, :] = (int(8 + 18 * t), int(12 + 18 * t), int(20 + 24 * t))

        # 좌측 액센트 바
        cv2.rectangle(img, (int(40 * s), int(100 * s)), (int(54 * s), H - int(100 * s)), accent, -1)

        # 페이드 인
        alpha = min(1.0, i / max(1, FPS // 2))

        # title
        title_color = tuple(int(c * alpha) for c in (235, 240, 250))
        cv2.putText(img, title, (int(80 * s), int(H * 0.42)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.3 * s, title_color, max(2, int(2 * s)), cv2.LINE_AA)
        if sub:
            sub_color = tuple(int(c * alpha) for c in (140, 200, 230))
            cv2.putText(img, sub, (int(80 * s), int(H * 0.52)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7 * s, sub_color, max(1, int(1 * s)), cv2.LINE_AA)
        if footer:
            footer_color = tuple(int(c * alpha) for c in (110, 140, 170))
            cv2.putText(img, footer, (int(80 * s), int(H * 0.92)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55 * s, footer_color, max(1, int(1 * s)), cv2.LINE_AA)

        # 하단 브랜드
        brand_text = "AURAVIEW  K-PERCEPTION"
        cv2.putText(img, brand_text, (W - int(360 * s), H - int(24 * s)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55 * s, (100, 200, 255), max(1, int(1 * s)), cv2.LINE_AA)
        out.append(img)
    return out


def _ensure_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _resize_video_frames(path: Path) -> List[np.ndarray]:
    """(legacy) 전체 프레임 일괄 적재 — 메모리 부담 큼. _stream_video_frames 권장."""
    cap = cv2.VideoCapture(str(path))
    out: List[np.ndarray] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame.shape[:2] != (H, W):
            frame = cv2.resize(frame, (W, H))
        out.append(frame)
    cap.release()
    return out


def _stream_video_frames(path: Path):
    """제너레이터 — 한 프레임씩 yield (메모리 절약)."""
    cap = cv2.VideoCapture(str(path))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[:2] != (H, W):
                frame = cv2.resize(frame, (W, H))
            yield frame
    finally:
        cap.release()


def _count_video_frames(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()


def build(limit: Optional[int] = None) -> Dict[str, object]:
    """N개 시나리오를 모아 한 편의 합본 영상으로 결합.

    limit 미지정 시 SHOWREEL_MAX_SCENARIOS (기본 3) — 작은 EC2 OOM 방지.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    n = max(1, min(int(limit) if limit else MAX_SCENARIOS, len(PRESETS)))
    presets = PRESETS[:n]

    # 1) 시나리오 보장
    metas: List[Dict[str, object]] = []
    for preset, title, hook in presets:
        out_name = f"{ts}_pre_{preset}"
        try:
            result = scenario_service.synthesize(preset=preset, out_name=out_name)
            metas.append({"preset": preset, "title": title, "hook": hook, "result": result})
        except Exception as exc:
            log.warning("scenario %s failed: %s", preset, exc)

    if not metas:
        raise RuntimeError("no scenarios produced")

    # 2) 출력 비디오 라이터 먼저 열고 즉시 스트리밍 — 메모리에 누적 X (작은 EC2 OOM 방지)
    raw_path = OUT_DIR / f"{ts}_showreel_raw.mp4"
    out_path = OUT_DIR / f"{ts}_showreel.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(raw_path), fourcc, FPS, (W, H))

    risk_timeline: List[float] = []
    frame_count = 0

    def _emit_card(*args, **kwargs):
        nonlocal frame_count
        for f in _draw_card(*args, **kwargs):
            vw.write(f)
            risk_timeline.append(0.0)
            frame_count += 1

    # 인트로 A
    _emit_card(
        "AuraView", "K-Perception Platform",
        "Tesla-style Occupancy · Fleet · Reenactment",
        duration_s=3.0, accent=(255, 200, 0),
    )
    # 인트로 B
    _emit_card(
        "보이지 않는 공간을 확률로 채운다",
        "Occupancy Network · HydraNet · E2E Risk Transformer",
        "auraview.allthatai.kr",
        duration_s=2.5, accent=(0, 200, 255),
    )

    for m in metas:
        result = m["result"]  # ReenactmentResult
        lead = float(result.lead_time_s)
        peak = float(result.peak_risk)
        _emit_card(
            str(m["title"]),
            f"선행 경고 {lead:.2f}초 · 피크 위험 {peak*100:.1f}%",
            str(m["hook"]),
            duration_s=2.0, accent=(0, 60, 255),
        )

        clip_path = Path(result.video_path)
        clip_len = _count_video_frames(clip_path) or 1
        rc = list(result.risk_curve)
        scale = (len(rc) / clip_len) if rc else 0.0
        for i, frame in enumerate(_stream_video_frames(clip_path)):
            vw.write(frame)
            if rc:
                risk_timeline.append(float(rc[min(len(rc) - 1, int(i * scale))]))
            else:
                risk_timeline.append(0.0)
            frame_count += 1

    # 3) 마무리 카드
    total_lead = sum(float(m["result"].lead_time_s) for m in metas) / max(1, len(metas))
    _emit_card(
        "결론",
        f"평균 선행 경고 {total_lead:.2f}초",
        "auraview.allthatai.kr  ·  github.com/leelang7/AuraView",
        duration_s=3.5, accent=(0, 224, 154),
    )

    vw.release()
    from . import scenario as scenario_mod

    audio_wav: Optional[Path] = None
    if _ensure_ffmpeg_available():
        try:
            audio_wav = OUT_DIR / f"{ts}_showreel.wav"
            scenario_mod._write_audio_track(risk_timeline, FPS, audio_wav)
        except Exception as exc:
            log.warning("audio gen failed: %s", exc)
            audio_wav = None

        cmd_base = ["ffmpeg", "-y", "-i", str(raw_path)]
        if audio_wav and audio_wav.exists():
            cmd_base += ["-i", str(audio_wav), "-c:a", "aac", "-b:a", "96k", "-shortest"]
        cmd_base += [
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_path),
        ]
        try:
            subprocess.run(cmd_base, check=True, capture_output=True, timeout=240)
            raw_path.unlink(missing_ok=True)
            if audio_wav and audio_wav.exists():
                audio_wav.unlink(missing_ok=True)
        except Exception as exc:
            log.warning("ffmpeg transcode failed: %s", exc)
            raw_path.replace(out_path)
    else:
        raw_path.replace(out_path)

    return {
        "video_url": f"/uploads/showreel/{out_path.name}",
        "video_path": str(out_path),
        "frame_count": frame_count,
        "scenarios": [
            {
                "preset": m["preset"], "title": m["title"],
                "lead_time_s": float(m["result"].lead_time_s),
                "peak_risk": float(m["result"].peak_risk),
            } for m in metas
        ],
        "average_lead_time_s": round(total_lead, 2),
        "created_at": datetime.utcnow().isoformat(),
    }


def _job_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def _write_job(job_id: str, data: Dict[str, object]) -> None:
    try:
        _job_path(job_id).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.warning("job write failed: %s", exc)


def read_job(job_id: str) -> Optional[Dict[str, object]]:
    p = _job_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _run_build_async(job_id: str, limit: Optional[int]) -> None:
    started = datetime.utcnow().isoformat()
    _write_job(job_id, {"job_id": job_id, "status": "running", "started_at": started, "limit": limit})
    if not _BUILD_LOCK.acquire(blocking=False):
        _write_job(job_id, {
            "job_id": job_id, "status": "rejected",
            "started_at": started, "error": "another build is in progress",
        })
        return
    try:
        result = build(limit=limit)
        _write_job(job_id, {
            "job_id": job_id, "status": "done",
            "started_at": started,
            "finished_at": datetime.utcnow().isoformat(),
            "result": result,
        })
    except Exception as exc:
        log.exception("showreel build failed: %s", exc)
        _write_job(job_id, {
            "job_id": job_id, "status": "error",
            "started_at": started,
            "finished_at": datetime.utcnow().isoformat(),
            "error": str(exc),
        })
    finally:
        try:
            _BUILD_LOCK.release()
        except RuntimeError:
            pass


def enqueue_build(limit: Optional[int] = None) -> Dict[str, object]:
    """비동기 빌드 큐잉 — HTTP 워커 블로킹 방지. job_id 반환."""
    job_id = uuid.uuid4().hex[:12]
    started = datetime.utcnow().isoformat()
    _write_job(job_id, {"job_id": job_id, "status": "queued", "started_at": started, "limit": limit})
    t = threading.Thread(target=_run_build_async, args=(job_id, limit), daemon=True)
    t.start()
    return {"job_id": job_id, "status": "queued", "limit": limit or MAX_SCENARIOS}


def latest():
    """가장 최근 showreel 메타. 없으면 placeholder 응답 (자동 빌드 안 함 — 워커 블로킹 방지)."""
    items = sorted(OUT_DIR.glob("*showreel*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not items:
        return {
            "name": None,
            "video_url": None,
            "created_at": None,
            "size_kb": 0,
            "age_hours": None,
            "note": "아직 빌드된 합본 영상 없음. POST /showreel/build 로 생성 (1~3분 소요).",
        }
    p = items[0]
    return {
        "name": p.stem,
        "video_url": f"/uploads/showreel/{p.name}",
        "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        "size_kb": round(p.stat().st_size / 1024, 1),
        "age_hours": round((datetime.now().timestamp() - p.stat().st_mtime) / 3600, 1),
    }


def list_recent(limit: int = 10):
    items = []
    for p in sorted(OUT_DIR.glob("*showreel*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        items.append({
            "name": p.stem,
            "video_url": f"/uploads/showreel/{p.name}",
            "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            "size_kb": round(p.stat().st_size / 1024, 1),
        })
    return items
