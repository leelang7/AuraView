"""
발표용 합본 시연 영상 (Showreel) 생성기.

흐름:
  1. 3개 합성 시나리오 자동 생성 (없으면)
  2. 타이틀 카드 1장 + 시나리오별 인트로 카드 + mp4 본편 + 마무리 카드
  3. ffmpeg concat → 1개 mp4

출력 길이: 약 90~120초.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from . import scenario as scenario_service

log = logging.getLogger("auraview.showreel")

OUT_DIR = Path(os.getenv("SHOWREEL_DIR", "uploads/showreel"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080
FPS = 24

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


def build() -> Dict[str, object]:
    """3개 시나리오를 모아 한 편의 합본 영상으로 결합."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) 시나리오 보장
    metas: List[Dict[str, object]] = []
    for preset, title, hook in PRESETS:
        out_name = f"{ts}_pre_{preset}"
        try:
            result = scenario_service.synthesize(preset=preset, out_name=out_name)
            metas.append({"preset": preset, "title": title, "hook": hook, "result": result})
        except Exception as exc:
            log.warning("scenario %s failed: %s", preset, exc)

    if not metas:
        raise RuntimeError("no scenarios produced")

    # 2) 합본 프레임 누적
    frames: List[np.ndarray] = []

    # risk timeline 누적 — 카드 구간은 0, 시나리오 클립은 해당 시나리오의 risk_curve 보간
    risk_timeline: List[float] = []

    intro_a = _draw_card(
        "AuraView", "K-Perception Platform",
        "Tesla-style Occupancy · Fleet · Reenactment",
        duration_s=3.0, accent=(255, 200, 0),
    )
    frames += intro_a
    risk_timeline += [0.0] * len(intro_a)

    intro_b = _draw_card(
        "보이지 않는 공간을 확률로 채운다",
        "Occupancy Network · HydraNet · E2E Risk Transformer",
        "auraview.allthatai.kr",
        duration_s=2.5, accent=(0, 200, 255),
    )
    frames += intro_b
    risk_timeline += [0.0] * len(intro_b)

    for m in metas:
        result = m["result"]  # ReenactmentResult
        lead = float(result.lead_time_s)
        peak = float(result.peak_risk)
        card = _draw_card(
            str(m["title"]),
            f"선행 경고 {lead:.2f}초 · 피크 위험 {peak*100:.1f}%",
            str(m["hook"]),
            duration_s=2.0, accent=(0, 60, 255),
        )
        frames += card
        risk_timeline += [0.0] * len(card)

        clip = _resize_video_frames(Path(result.video_path))
        frames += clip
        # 시나리오 risk_curve 를 클립 길이에 맞춰 보간 (다른 fps 영상 들어와도 OK)
        rc = list(result.risk_curve)
        if rc and len(clip) > 0:
            scale = len(rc) / len(clip)
            risk_timeline += [
                float(rc[min(len(rc) - 1, int(i * scale))]) for i in range(len(clip))
            ]
        else:
            risk_timeline += [0.0] * len(clip)

    # 3) 마무리 카드
    total_lead = sum(float(m["result"].lead_time_s) for m in metas) / max(1, len(metas))
    outro = _draw_card(
        "결론",
        f"평균 선행 경고 {total_lead:.2f}초",
        "auraview.allthatai.kr  ·  github.com/leelang7/AuraView",
        duration_s=3.5, accent=(0, 224, 154),
    )
    frames += outro
    risk_timeline += [0.0] * len(outro)

    # 4) 출력 — scenario._write_video 의 음향 합성 로직 재사용
    from . import scenario as scenario_mod
    raw_path = OUT_DIR / f"{ts}_showreel_raw.mp4"
    out_path = OUT_DIR / f"{ts}_showreel.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(raw_path), fourcc, FPS, (W, H))
    for f in frames:
        vw.write(f)
    vw.release()

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
        "frame_count": len(frames),
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
