"""
Accident Reenactment — 사고 재현 영상 생성기.

입력:
  A. 실제 블랙박스 영상 (운전자가 제공) + (선택) 사고 시점
  B. 합성 시나리오 (preset 이름) — 영상 없이 procedural 생성

출력:
  mp4 파일 + 프레임별 risk curve + 선행 경고 시간(lead_time_s)

핵심 메시지:
  "AuraView가 있었다면 이 사고는 {lead_time_s}초 먼저 경고할 수 있었다."
"""

from __future__ import annotations

import logging
import math
import os
import random
import struct
import subprocess
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .hydranet import get_default as get_hydranet
from . import occupancy as occupancy_service
from . import risk_transformer as risk_service

log = logging.getLogger("auraview.scenario")

OUT_DIR = Path(os.getenv("SCENARIO_DIR", "uploads/scenarios"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

RISK_THRESHOLD = 0.45   # 이 값 이상이 되는 프레임 = 경고
SAMPLE_FPS = 8          # 8fps로 샘플링해 추론 (비용 절감)
OUTPUT_FPS = 24         # cinematic — 24fps

# 합성 시나리오 출력 해상도 — env 로 조정 가능 (소형 인스턴스 대응)
# SHOWREEL_W/H 와 동일 변수 사용 (한 영상 흐름이라 일관 유지)
# 기본 960×540 + 120 frames ≈ 187MB/시나리오 (1GB EC2 OOM 회피, 한 번에 한 시나리오만)
SYNTH_W = int(os.getenv("SHOWREEL_W", "960"))
SYNTH_H = int(os.getenv("SHOWREEL_H", "540"))
SYNTH_FRAMES = int(os.getenv("SHOWREEL_SCENARIO_FRAMES", "120"))


@dataclass
class ReenactmentResult:
    video_url: str
    video_path: str
    frame_count: int
    risk_curve: List[float] = field(default_factory=list)
    lead_time_s: float = 0.0
    peak_risk: float = 0.0
    name: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "video_url": self.video_url,
            "video_path": self.video_path,
            "frame_count": self.frame_count,
            "risk_curve": [round(v, 3) for v in self.risk_curve],
            "lead_time_s": round(self.lead_time_s, 2),
            "peak_risk": round(self.peak_risk, 3),
            "name": self.name,
            "created_at": self.created_at,
        }


# ──────────────────────────────────────────────────────────────────────
# Rendering helpers
# ──────────────────────────────────────────────────────────────────────

def _draw_hud(frame: np.ndarray, risk: float, t_s: float, peak_t: Optional[float]) -> np.ndarray:
    """프레임 상단 HUD 오버레이 — 위험도·남은 시간·경고. (해상도 자동 스케일)"""
    h, w = frame.shape[:2]
    s = w / 960.0   # 기준 폭 960 → 1920 면 s=2.0
    overlay = frame.copy()

    # 상단 패널
    cv2.rectangle(overlay, (0, 0), (w, int(h * 0.16)), (6, 10, 18), -1)
    frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)

    # 위험 바
    bar_w = int(w * 0.9)
    bar_x = int(w * 0.05)
    bar_y = int(h * 0.11)
    bar_h = max(8, int(8 * s))
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (40, 60, 80), -1)
    fill = int(bar_w * min(1.0, risk))
    color = (0, 255, 0)
    if risk > 0.35: color = (0, 200, 255)
    if risk > 0.55: color = (0, 160, 255)
    if risk > 0.75: color = (0, 60, 255)
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill, bar_y + bar_h), color, -1)

    # 텍스트
    cv2.putText(frame, f"AURAVIEW  |  RISK  {risk*100:5.1f}%",
                (bar_x, bar_y - int(8 * s)), cv2.FONT_HERSHEY_SIMPLEX, 0.72 * s, (235, 240, 245), max(2, int(2 * s)))
    if peak_t is not None and t_s < peak_t:
        lead = peak_t - t_s
        msg = f"EARLY WARNING  T-{lead:0.1f}s"
        cv2.putText(frame, msg, (bar_x, int(h * 0.055)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8 * s, (0, 100, 255), max(2, int(2 * s)))

    # 위험 높으면 하단 경고
    if risk > RISK_THRESHOLD:
        overlay2 = frame.copy()
        cv2.rectangle(overlay2, (0, int(h * 0.82)), (w, h), (0, 0, 80), -1)
        frame = cv2.addWeighted(overlay2, 0.45, frame, 0.55, 0)
        cv2.putText(frame, "! COLLISION RISK — BRAKE !",
                    (int(w * 0.08), int(h * 0.92)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1 * s, (0, 60, 255), max(3, int(3 * s)))
    return frame


def _write_audio_track(risks: List[float], fps: int, out_wav: Path) -> bool:
    """
    위험도 곡선에 맞춰 procedural 경고음 WAV 생성.

    규칙:
      risk < 0.45  : 무음
      0.45~0.75   : 880Hz, 0.10s beep, 0.60s 간격
      ≥ 0.75      : 1320Hz, 0.10s beep, 0.25s 간격
    """
    sr = 44100
    total_samples = int(len(risks) / fps * sr)
    if total_samples <= 0:
        return False

    audio = np.zeros(total_samples, dtype=np.float32)
    last_beep_t = -10.0

    for i, r in enumerate(risks):
        if r < 0.45:
            continue
        t_now = i / fps
        if r >= 0.75:
            interval = 0.25
            freq = 1320
            amp = 0.45
            beep_dur = 0.09
        else:
            interval = 0.60
            freq = 880
            amp = 0.32
            beep_dur = 0.10

        if t_now - last_beep_t < interval:
            continue
        last_beep_t = t_now

        s = int(t_now * sr)
        e = min(total_samples, s + int(beep_dur * sr))
        if e <= s:
            continue
        n = e - s
        tt = np.arange(n) / sr
        wave_v = np.sin(2 * np.pi * freq * tt) * amp
        # 페이드 in/out (10ms each)
        fade = int(sr * 0.01)
        if n > 2 * fade:
            wave_v[:fade] *= np.linspace(0, 1, fade)
            wave_v[-fade:] *= np.linspace(1, 0, fade)
        audio[s:e] += wave_v.astype(np.float32)

    # clip + 16bit PCM 저장
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return True


def _write_video(frames: List[np.ndarray], out_path: Path, fps: int = OUTPUT_FPS,
                 risks: Optional[List[float]] = None) -> Path:
    if not frames:
        raise RuntimeError("no frames to write")
    h, w = frames[0].shape[:2]
    temp_path = out_path.with_suffix(".raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(temp_path), fourcc, fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()

    # 위험 곡선이 있으면 procedural 경고음 트랙 생성
    audio_wav: Optional[Path] = None
    if risks:
        try:
            audio_wav = out_path.with_suffix(".wav")
            ok = _write_audio_track(risks, fps, audio_wav)
            if not ok:
                audio_wav = None
        except Exception as exc:
            log.warning("audio track gen failed: %s", exc)
            audio_wav = None

    # H.264 + (있으면) AAC mux
    if audio_wav and audio_wav.exists():
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_path),
            "-i", str(audio_wav),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", str(temp_path),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out_path),
        ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        temp_path.unlink(missing_ok=True)
        if audio_wav:
            audio_wav.unlink(missing_ok=True)
    except Exception as exc:
        log.warning("ffmpeg transcode skipped (%s) — serving raw mp4v", exc)
        temp_path.replace(out_path)
    return out_path


# ──────────────────────────────────────────────────────────────────────
# A. 실제 영상 기반 재현
# ──────────────────────────────────────────────────────────────────────

def reenact_from_video(video_path: str, out_name: str) -> ReenactmentResult:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("cannot open video")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_stride = max(1, int(round(src_fps / SAMPLE_FPS)))

    hydranet = get_hydranet()
    frames_out: List[np.ndarray] = []
    risk_curve: List[float] = []
    timestamps: List[float] = []

    idx = 0
    tmp_frame_path = OUT_DIR / f"_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % src_stride != 0:
            idx += 1
            continue

        cv2.imwrite(str(tmp_frame_path), frame)
        try:
            pred = hydranet.infer(str(tmp_frame_path))
        except Exception as exc:
            log.warning("hydranet infer failed: %s", exc)
            pred = type("P", (), {"detections": [], "vru_detections": [], "signals": []})()

        dets = [
            occupancy_service.Detection(
                class_name=d["class_name"], confidence=d["confidence"],
                bbox_xyxy=d["bbox_xyxy"], image_size=d["image_size"])
            for d in getattr(pred, "detections", [])
        ]
        occ = occupancy_service.compute_occupancy(
            detections=dets,
            vehicle_detected=bool(getattr(pred, "detections", [])),
            signal_detected=bool(getattr(pred, "signals", [])),
        )
        risk = risk_service.predict(risk_service.RiskInput(
            duration=1.0 + idx / max(src_fps, 1),
            vehicle_cnt=len(getattr(pred, "detections", [])),
            vru_cnt=len(getattr(pred, "vru_detections", [])),
            occluded_mass=occ.occluded_mass,
            signal_state="stop-And-Remain" if not getattr(pred, "signals", []) else "",
            obstacle_type="truck" if any(d["class_name"] == "truck" for d in getattr(pred, "detections", [])) else "",
        ))
        risk_curve.append(risk.p_collision)
        timestamps.append(idx / src_fps)

        idx += 1

    cap.release()
    tmp_frame_path.unlink(missing_ok=True)

    if not risk_curve:
        raise RuntimeError("no frames sampled")

    peak_idx = int(np.argmax(risk_curve))
    peak_t = timestamps[peak_idx]
    peak_risk = float(risk_curve[peak_idx])

    # lead_time: RISK_THRESHOLD 첫 초과 시점 → peak 시점
    lead_time_s = 0.0
    for i, v in enumerate(risk_curve):
        if v >= RISK_THRESHOLD:
            lead_time_s = max(0.0, peak_t - timestamps[i])
            break

    # 두 번째 pass: HUD 오버레이 렌더
    cap = cv2.VideoCapture(video_path)
    idx = 0
    sample_i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % src_stride != 0:
            idx += 1
            continue
        r = risk_curve[sample_i]
        t_s = timestamps[sample_i]
        frames_out.append(_draw_hud(frame, r, t_s, peak_t))
        sample_i += 1
        idx += 1
    cap.release()

    out_path = OUT_DIR / f"{out_name}.mp4"
    _write_video(frames_out, out_path, fps=SAMPLE_FPS * 2, risks=risk_curve)
    return ReenactmentResult(
        video_url=f"/uploads/scenarios/{out_path.name}",
        video_path=str(out_path),
        frame_count=len(frames_out),
        risk_curve=risk_curve,
        lead_time_s=lead_time_s,
        peak_risk=peak_risk,
        name=out_name,
    )


# ──────────────────────────────────────────────────────────────────────
# B. Procedural 합성 시나리오
# ──────────────────────────────────────────────────────────────────────

def _draw_scene_base(w: int, h: int) -> np.ndarray:
    """CARLA-풍 도시 도로 베이스 — 그라디언트 하늘+태양 + 빌딩 실루엣 + 다중차로 + 대기 원근."""
    s = w / 960.0
    img = np.zeros((h, w, 3), dtype=np.uint8)
    sky_h = int(h * 0.55)

    # ── 1) 하늘 — 도시 황혼 그라디언트 + 태양
    for y in range(sky_h):
        t = y / max(1, sky_h)
        # 위쪽: 진한 네이비 → 지평선: 따뜻한 핑크/오렌지
        b = int(38 + 95 * t)
        g = int(28 + 85 * t)
        r = int(22 + 140 * t)
        img[y, :] = (b, g, r)

    # 태양 — 우상단에서 빛나는 원
    sun_x = int(w * 0.78)
    sun_y = int(sky_h * 0.55)
    sun_r = max(20, int(40 * s))
    # 헤일로
    halo = np.zeros_like(img)
    cv2.circle(halo, (sun_x, sun_y), sun_r * 4, (160, 200, 240), -1)
    halo = cv2.GaussianBlur(halo, (0, 0), sigmaX=40 * s, sigmaY=40 * s)
    img = cv2.addWeighted(img, 1.0, halo, 0.30, 0)
    cv2.circle(img, (sun_x, sun_y), sun_r, (200, 220, 250), -1)

    # ── 2) 빌딩 실루엣 (지평선) — 가짜 도시 스카이라인
    rng = np.random.RandomState(42)  # 같은 빌딩 패턴 재현
    bx = 0
    while bx < w:
        bw = rng.randint(int(40 * s), int(120 * s))
        bh = rng.randint(int(40 * s), int(110 * s))
        b_top = sky_h - bh
        # 실루엣 어두운 색 (대기원근으로 회보랏빛)
        cv2.rectangle(img, (bx, b_top), (bx + bw, sky_h), (50, 45, 60), -1)
        # 창문 점등 (몇 개만)
        for _ in range(rng.randint(2, 6)):
            wx = bx + rng.randint(4, max(5, bw - 8))
            wy = b_top + rng.randint(8, max(9, bh - 8))
            ww = rng.randint(2, max(3, int(6 * s)))
            wh = rng.randint(2, max(3, int(6 * s)))
            light = (rng.randint(120, 220), rng.randint(170, 240), rng.randint(220, 255))
            cv2.rectangle(img, (wx, wy), (wx + ww, wy + wh), light, -1)
        bx += bw + rng.randint(2, 8)

    # ── 3) 도로 — 어두운 아스팔트 + 노이즈
    cv2.rectangle(img, (0, sky_h), (w, h), (18, 18, 24), -1)
    noise = (np.random.rand(h - sky_h, w, 3) * 14).astype(np.int16)
    img[sky_h:, :] = np.clip(img[sky_h:, :].astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # ── 4) 다중 차로 — 4 차선 (중앙선 노란색 + 차선 흰색 점선)
    # 4 차로: 외측 -0.35 / -0.12 / 0.12 / 0.35 (vanishing point=0.5)
    lane_offsets = [-0.35, -0.12, 0.12, 0.35]
    for off in lane_offsets:
        far_x = int(w * (0.5 + off * 0.35))
        near_x = int(w * (0.5 + off))
        cv2.line(img, (far_x, sky_h), (near_x, h), (90, 90, 100), max(1, int(1.5 * s)))

    # 점선 차선 (중앙 2개 차로 사이) — 원근감 두께 변화
    for i in range(8):
        prog = i / 7.0
        y1 = int(sky_h + prog * (h - sky_h) * 0.95)
        y2 = y1 + int(h * (0.012 + prog * 0.030))
        # 좌측 점선
        x1 = int(w * (0.5 + (-0.12) * (0.35 + prog * 0.65)))
        thick = max(2, int((1 + prog * 4) * s))
        cv2.line(img, (x1, y1), (x1, y2), (215, 215, 110), thick)
        # 우측 점선
        x2 = int(w * (0.5 + 0.12 * (0.35 + prog * 0.65)))
        cv2.line(img, (x2, y1), (x2, y2), (215, 215, 110), thick)
        # 중앙선 (이중황색)
        cx = int(w * 0.5)
        cv2.line(img, (cx, y1), (cx, y2), (180, 200, 110), max(2, int((1 + prog * 3) * s)))

    # ── 5) 대기 원근 (지평선 안개)
    haze = np.zeros_like(img)
    haze_h = int(h * 0.20)
    for y in range(sky_h - haze_h // 2, sky_h + haze_h // 2):
        if y < 0 or y >= h: continue
        alpha = 1.0 - abs(y - sky_h) / (haze_h / 2)
        haze[y, :] = (int(130 * alpha), int(120 * alpha), int(115 * alpha))
    img = cv2.addWeighted(img, 1.0, haze, 0.50, 0)

    return img


def _draw_vehicle(img: np.ndarray, cx: int, cy: int, scale: float,
                  body_color: Tuple[int, int, int] = (60, 70, 90),
                  vehicle_type: str = "car",
                  brake: bool = False) -> np.ndarray:
    """3D-풍 차량 후방 뷰 — 사다리꼴 body + 창 + 후미등 + 바퀴 + 그림자."""
    s = scale
    h, w = img.shape[:2]

    # 크기 (rear view: 트럭은 더 큼)
    if vehicle_type == "truck":
        body_w = int(160 * s); body_h = int(140 * s); cabin_h = int(40 * s)
        type_label = "TRUCK"
    elif vehicle_type == "bus":
        body_w = int(180 * s); body_h = int(150 * s); cabin_h = int(50 * s)
        type_label = "BUS"
    else:
        body_w = int(110 * s); body_h = int(80 * s); cabin_h = int(28 * s)
        type_label = ""

    bw = body_w; bh = body_h
    # 사다리꼴 body — 위쪽 약간 좁게 (3D 원근)
    top_w = int(bw * 0.92)
    top_y = cy - bh // 2
    bot_y = cy + bh // 2
    pts = np.array([
        [cx - top_w // 2, top_y],
        [cx + top_w // 2, top_y],
        [cx + bw // 2, bot_y],
        [cx - bw // 2, bot_y],
    ], dtype=np.int32)

    # 그림자 (블러)
    shadow_pts = pts.copy()
    shadow_pts[:, 1] += int(8 * s)
    shadow = np.zeros_like(img)
    cv2.fillPoly(shadow, [shadow_pts], (0, 0, 0))
    shadow = cv2.GaussianBlur(shadow, (0, 0), sigmaX=8 * s, sigmaY=4 * s)
    img = cv2.addWeighted(img, 1.0, shadow, 0.55, 0)

    # body
    cv2.fillPoly(img, [pts], body_color)
    # 위쪽 하이라이트 (광택)
    high_pts = np.array([
        [cx - top_w // 2 + int(4 * s), top_y + int(2 * s)],
        [cx + top_w // 2 - int(4 * s), top_y + int(2 * s)],
        [cx + top_w // 2 - int(4 * s), top_y + int(8 * s)],
        [cx - top_w // 2 + int(4 * s), top_y + int(8 * s)],
    ], dtype=np.int32)
    high_color = tuple(min(255, int(c * 1.4)) for c in body_color)
    cv2.fillPoly(img, [high_pts], high_color)

    # 창 (rear window) — 차량 상단 1/3
    win_top = top_y + int(8 * s)
    win_bot = top_y + cabin_h
    win_pts = np.array([
        [cx - top_w // 2 + int(8 * s), win_top],
        [cx + top_w // 2 - int(8 * s), win_top],
        [cx + top_w // 2 - int(12 * s), win_bot],
        [cx - top_w // 2 + int(12 * s), win_bot],
    ], dtype=np.int32)
    cv2.fillPoly(img, [win_pts], (10, 12, 20))

    # 후미등 (좌우) — 빨강, 브레이크면 더 밝게
    tail_y = bot_y - int(18 * s)
    tail_w = int(18 * s)
    tail_h = int(8 * s)
    tail_color = (40, 60, 240) if brake else (40, 50, 180)
    cv2.rectangle(img, (cx - bw // 2 + int(6 * s), tail_y),
                  (cx - bw // 2 + int(6 * s) + tail_w, tail_y + tail_h), tail_color, -1)
    cv2.rectangle(img, (cx + bw // 2 - int(6 * s) - tail_w, tail_y),
                  (cx + bw // 2 - int(6 * s), tail_y + tail_h), tail_color, -1)
    if brake:
        # 브레이크 글로우
        glow = np.zeros_like(img)
        cv2.rectangle(glow, (cx - bw // 2, tail_y - int(4 * s)),
                      (cx + bw // 2, tail_y + tail_h + int(4 * s)), (40, 60, 240), -1)
        glow = cv2.GaussianBlur(glow, (0, 0), sigmaX=6 * s, sigmaY=3 * s)
        img = cv2.addWeighted(img, 1.0, glow, 0.45, 0)

    # 바퀴 (좌우) — 어두운 타원
    wheel_r = max(3, int(10 * s))
    cv2.ellipse(img, (cx - bw // 2 + int(8 * s), bot_y - int(4 * s)),
                (wheel_r, max(2, int(6 * s))), 0, 0, 360, (12, 12, 16), -1)
    cv2.ellipse(img, (cx + bw // 2 - int(8 * s), bot_y - int(4 * s)),
                (wheel_r, max(2, int(6 * s))), 0, 0, 360, (12, 12, 16), -1)

    # 라벨 (TRUCK/BUS — 원근에 따라 표시)
    if type_label and bw > 80:
        cv2.putText(img, type_label, (cx - int(28 * s), top_y + int(20 * s)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55 * s, (190, 200, 220), max(1, int(s)))

    return img


def _apply_cinematic_post(frame: np.ndarray) -> np.ndarray:
    """프레임 단위 후처리 — 비네트 + 색감 보정 + 살짝 글로우."""
    h, w = frame.shape[:2]
    s = w / 960.0

    # ── 비네트 (가장자리 어둡게)
    yy, xx = np.ogrid[:h, :w]
    cy, cx = h / 2, w / 2
    dx = (xx - cx) / cx
    dy = (yy - cy) / cy
    dist2 = dx * dx + dy * dy
    vignette_mask = np.clip(1.0 - dist2 * 0.55, 0.45, 1.0).astype(np.float32)
    out = frame.astype(np.float32)
    out *= vignette_mask[..., None]

    # ── 약한 cinematic 글로우 (밝은 영역 블러 + 가산)
    bright = np.clip(out - 200, 0, 255).astype(np.uint8)
    glow = cv2.GaussianBlur(bright, (0, 0), sigmaX=8 * s, sigmaY=8 * s)
    out = np.clip(out + glow * 0.35, 0, 255)

    # ── 약한 teal-orange 컬러 그레이딩 (그림자에 청록, 하이라이트 따뜻하게)
    shadow_mask = np.clip(1.0 - out.mean(axis=2, keepdims=True) / 255.0, 0, 1)
    out[..., 0] += shadow_mask[..., 0] * 6   # B 가산 (그림자 청록)
    out[..., 2] += (1 - shadow_mask[..., 0]) * 4  # R 가산 (하이라이트 따뜻)
    out = np.clip(out, 0, 255).astype(np.uint8)

    return out


def _synthesize_crosswalk_truck(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = SYNTH_FRAMES) -> Tuple[List[np.ndarray], List[float]]:
    """대형차가 전방 횡단보도를 가리고 있다가, 보행자가 T=7초에 등장하는 장면."""
    out_frames = []
    risks = []
    s_global = w / 960.0
    sky_h = int(h * 0.55)
    for i in range(frames):
        t = i / OUTPUT_FPS
        img = _draw_scene_base(w, h)

        # 횡단보도 stripes (트럭 앞쪽 도로 위, 원근감) — 사다리꼴 stripe
        for k in range(6):
            prog_x = (k - 2.5) / 6.0
            far_x = int(w * 0.5 + prog_x * w * 0.18)
            near_x = int(w * 0.5 + prog_x * w * 0.45)
            stripe_far_y = int(h * 0.62)
            stripe_near_y = int(h * 0.72)
            stripe_w_far = int(w * 0.045)
            stripe_w_near = int(w * 0.075)
            pts = np.array([
                [far_x - stripe_w_far // 2, stripe_far_y],
                [far_x + stripe_w_far // 2, stripe_far_y],
                [near_x + stripe_w_near // 2, stripe_near_y],
                [near_x - stripe_w_near // 2, stripe_near_y],
            ], dtype=np.int32)
            cv2.fillPoly(img, [pts], (200, 200, 200))

        # 좌측 차로의 다른 차 (씬 밀도)
        side_scale = 0.4 + 0.005 * i
        img = _draw_vehicle(img, int(w * 0.18), int(h * (0.62 + 0.005 * i)),
                            scale=min(0.7, side_scale * s_global), body_color=(180, 80, 60))

        # 전방 트럭 — 중앙, 점점 접근
        truck_scale = 0.55 + 0.018 * i
        truck_cx = int(w * 0.5)
        truck_cy = int(h * (0.55 + 0.015 * i))
        img = _draw_vehicle(img, truck_cx, truck_cy,
                            scale=min(1.4, truck_scale * s_global),
                            body_color=(35, 38, 50), vehicle_type="truck")

        # 보행자: T=5초부터 오른쪽에서 횡단 시작 (트럭 뒤에서)
        ped_visible = t >= 5.0
        if ped_visible:
            prog = min(1.0, (t - 5.0) / 3.0)
            px = int(w * (0.82 - 0.40 * prog))
            py = int(h * 0.74)
            ped_s = max(1.0, s_global * 1.2)
            # 그림자
            cv2.ellipse(img, (px, py + int(20 * ped_s)),
                        (int(14 * ped_s), int(5 * ped_s)), 0, 0, 360, (0, 0, 0), -1)
            # 머리
            cv2.circle(img, (px, py - int(24 * ped_s)), int(10 * ped_s), (170, 180, 200), -1)
            # 몸통 (재킷)
            cv2.rectangle(img, (px - int(9 * ped_s), py - int(14 * ped_s)),
                          (px + int(9 * ped_s), py + int(18 * ped_s)),
                          (60, 80, 220), -1)
            # 다리
            cv2.line(img, (px - int(4 * ped_s), py + int(18 * ped_s)),
                     (px - int(4 * ped_s), py + int(28 * ped_s)),
                     (40, 40, 60), max(2, int(3 * ped_s)))
            cv2.line(img, (px + int(4 * ped_s), py + int(18 * ped_s)),
                     (px + int(4 * ped_s), py + int(28 * ped_s)),
                     (40, 40, 60), max(2, int(3 * ped_s)))

        # risk
        occlusion = min(1.0, truck_scale / 1.4)
        base_risk = occlusion * 0.45
        if ped_visible:
            base_risk = min(0.97, base_risk + 0.35 + 0.3 * ((t - 5.0) / 2.0))
        else:
            if t >= 2.5:
                base_risk = min(0.7, base_risk + 0.15 * (t - 2.5))
        base_risk += random.uniform(-0.015, 0.015)
        risks.append(float(max(0.0, min(0.98, base_risk))))
        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _synthesize_motorcycle_blindspot(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = SYNTH_FRAMES) -> Tuple[List[np.ndarray], List[float]]:
    """측면 사각지대에서 이륜차가 추월 접근."""
    out_frames = []
    risks = []
    s_global = w / 960.0
    for i in range(frames):
        t = i / OUTPUT_FPS
        img = _draw_scene_base(w, h)

        # 앞 차량 (우측 차로) — 중간 거리
        img = _draw_vehicle(img, int(w * 0.62), int(h * 0.62),
                            scale=0.7 * s_global, body_color=(55, 65, 85))
        # 추가 차량 (반대편 차로)
        img = _draw_vehicle(img, int(w * 0.30), int(h * 0.58),
                            scale=0.45 * s_global, body_color=(180, 80, 70))

        # 이륜차: T=3초부터 좌측 사각지대에서 서서히 접근
        moto_visible = t >= 2.5
        if moto_visible:
            prog = min(1.0, (t - 2.5) / 2.5)
            mx = int(w * (0.05 + 0.35 * prog))
            my = int(h * (0.66 + 0.10 * prog))
            ms = max(2, int((8 + 22 * prog) * s_global))
            # 그림자
            cv2.ellipse(img, (mx + ms, my + int(ms * 2.2)),
                        (int(ms * 1.4), int(ms * 0.4)), 0, 0, 360, (0, 0, 0), -1)
            # 후륜
            cv2.circle(img, (mx + ms, my + int(ms * 1.7)), ms, (20, 20, 25), -1)
            cv2.circle(img, (mx + ms, my + int(ms * 1.7)), int(ms * 0.5), (60, 60, 70), -1)
            # 전륜
            cv2.circle(img, (mx + ms, my), ms, (20, 20, 25), -1)
            cv2.circle(img, (mx + ms, my), int(ms * 0.5), (60, 60, 70), -1)
            # 차체 (시트 + 라이더)
            cv2.line(img, (mx + ms, my + int(ms * 0.2)),
                     (mx + ms, my + int(ms * 1.6)), (200, 50, 50), max(2, int(ms * 0.5)))
            # 라이더 머리
            cv2.circle(img, (mx + ms, my - int(ms * 0.6)), int(ms * 0.6), (40, 30, 30), -1)
            # 헤드라이트 글로우 (위협감)
            if prog > 0.3:
                glow = np.zeros_like(img)
                cv2.circle(glow, (mx + ms, my), int(ms * 1.2), (80, 220, 240), -1)
                glow = cv2.GaussianBlur(glow, (0, 0), sigmaX=4, sigmaY=4)
                img = cv2.addWeighted(img, 1.0, glow, 0.45, 0)

        # risk
        base_risk = 0.10 + 0.025 * t
        if moto_visible:
            base_risk = min(0.96, 0.30 + 0.15 * (t - 2.5))
        base_risk += random.uniform(-0.01, 0.01)
        risks.append(float(max(0.0, min(0.98, base_risk))))
        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _synthesize_signal_occluded(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = SYNTH_FRAMES) -> Tuple[List[np.ndarray], List[float]]:
    """신호등이 전방 버스에 가려져 있다가, 앞차가 급감속하는 장면."""
    out_frames = []
    risks = []
    s_global = w / 960.0
    for i in range(frames):
        t = i / OUTPUT_FPS
        img = _draw_scene_base(w, h)

        # 신호등 (좌상단 polleta)— 버스 뒤에 가려질 위치
        sig_x = int(w * 0.42)
        sig_y = int(h * 0.30)
        cv2.line(img, (sig_x, int(h * 0.56)), (sig_x, sig_y), (40, 40, 50), max(2, int(3 * s_global)))
        cv2.rectangle(img, (sig_x - int(14 * s_global), sig_y - int(34 * s_global)),
                      (sig_x + int(14 * s_global), sig_y + int(8 * s_global)), (25, 25, 30), -1)
        # 빨간불 (가려져야 의미 있음)
        cv2.circle(img, (sig_x, sig_y - int(20 * s_global)), int(7 * s_global), (60, 60, 240), -1)

        # 전방 버스 — 점점 접근, 신호 가림
        bus_scale = 0.85 + 0.012 * i
        img = _draw_vehicle(img, int(w * 0.5), int(h * (0.50 + 0.012 * i)),
                            scale=min(1.6, bus_scale * s_global),
                            body_color=(60, 80, 130), vehicle_type="bus",
                            brake=(t >= 4.5))

        # risk: 신호 가림 + 버스 감속 임박
        base_risk = 0.18 + 0.025 * t
        if t >= 4.5:
            base_risk = min(0.95, 0.45 + 0.14 * (t - 4.5))
        base_risk += random.uniform(-0.015, 0.015)
        risks.append(float(max(0.0, min(0.98, base_risk))))
        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _synthesize_v2v_collab(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = SYNTH_FRAMES) -> Tuple[List[np.ndarray], List[float]]:
    """
    V2V 협업 인지 시연 시나리오.

    스토리:
      T=0~4s : 전방에 큰 트럭이 횡단보도를 가림. ego 의 카메라로는 보행자 보이지 않음.
                 risk 천천히 증가하지만 임계 미만.
      T=4s   : 마주오는 차로부터 V2V 메시지 수신 — "내 시점에 보행자 있음".
                 ego HUD 에 'V2V RECEIVED' 배지 + 트럭 너머에 사이안 dashed circle (가상 보행자) 표시.
                 risk 즉시 점프.
      T=4s~7s: dashed circle 이 점점 ego 쪽으로 다가옴 (마주오는 차의 시점에서 본 보행자가 길을 건넘).
      T=7s   : 실제 보행자가 트럭 옆으로 나타남 — V2V 예측과 일치 → risk 피크.
                 lead time = 7s - 4s = 3s (V2V 가 없었으면 lead time = ~0).
    """
    out_frames = []
    risks = []
    for i in range(frames):
        t = i / OUTPUT_FPS
        img = _draw_scene_base(w, h)

        # 횡단보도
        for k in range(6):
            x1 = int(w * 0.20 + k * w * 0.11)
            x2 = x1 + int(w * 0.08)
            y1 = int(h * 0.66)
            y2 = y1 + int(h * 0.03)
            cv2.rectangle(img, (x1, y1), (x2, y2), (220, 220, 220), -1)

        # 전방 트럭 (정지 상태로 횡단보도 가림)
        truck_w = int(w * 0.55)
        truck_h = int(h * 0.42)
        tx = (w - truck_w) // 2
        ty = int(h * 0.48)
        cv2.rectangle(img, (tx, ty), (tx + truck_w, ty + truck_h), (38, 38, 52), -1)
        cv2.rectangle(img, (tx, ty), (tx + truck_w, ty + truck_h), (170, 80, 80), 2)
        cv2.putText(img, "TRUCK", (tx + 12, ty + int(36 * w / 960)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7 * w / 960, (200, 200, 230), 2)

        # 마주오는 차 (작게 옆에 표시 — 시연용)
        on_w = int(w * 0.10)
        on_h = int(h * 0.10)
        ox = int(w * 0.78)
        oy = int(h * 0.40)
        cv2.rectangle(img, (ox, oy), (ox + on_w, oy + on_h), (60, 80, 110), -1)
        cv2.putText(img, "ONCOMING", (ox - int(20 * w / 960), oy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45 * w / 960, (150, 200, 255), 1)

        # T >= 4s: V2V 수신 표시 + 가상 보행자 dashed circle
        v2v_active = t >= 4.0
        if v2v_active:
            # 우상단 V2V 배지
            badge_w = int(w * 0.30)
            badge_h = int(h * 0.07)
            bx = w - badge_w - int(w * 0.04)
            by = int(h * 0.20)
            cv2.rectangle(img, (bx, by), (bx + badge_w, by + badge_h),
                          (40, 80, 130), -1)
            cv2.rectangle(img, (bx, by), (bx + badge_w, by + badge_h),
                          (255, 200, 0), 2)
            cv2.putText(img, "V2V  RECEIVED",
                        (bx + int(14 * w / 960), by + int(45 * h / 540)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7 * w / 960,
                        (220, 235, 255), 2)

            # 가상 보행자 (트럭 너머, 시간이 흐를수록 ego 쪽으로 이동)
            prog = min(1.0, (t - 4.0) / 3.0)
            ped_x = int(tx + truck_w * 0.58 - int(w * 0.18) * prog)
            ped_y = int(ty + truck_h * 0.66 + int(h * 0.07) * prog)
            radius = int(38 * w / 960)
            # 사이안 점선 원 (V2V 예측 보행자)
            for ang in range(0, 360, 24):
                ar = math.radians(ang)
                p1 = (int(ped_x + radius * math.cos(ar)),
                      int(ped_y + radius * math.sin(ar)))
                p2 = (int(ped_x + (radius + 4) * math.cos(ar + math.radians(14))),
                      int(ped_y + (radius + 4) * math.sin(ar + math.radians(14))))
                cv2.line(img, p1, p2, (255, 220, 80), 3)
            # 'V2V' 라벨
            cv2.putText(img, "V2V",
                        (ped_x - int(22 * w / 960), ped_y - radius - int(8 * h / 540)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6 * w / 960, (255, 220, 80), 2)

        # T >= 7s: 실제 보행자 등장
        ped_visible = t >= 7.0
        if ped_visible:
            prog = min(1.0, (t - 7.0) / 1.5)
            px = int(tx + truck_w * 0.45 - int(w * 0.10) * prog)
            py = int(ty + truck_h * 0.85)
            cv2.circle(img, (px, py - int(28 * h / 540)), int(13 * w / 960), (240, 220, 200), -1)
            cv2.rectangle(img, (px - int(11 * w / 960), py - int(15 * h / 540)),
                          (px + int(11 * w / 960), py + int(22 * h / 540)),
                          (220, 60, 60), -1)

        # ── Risk ──
        # 트럭 가림 → baseline 0.20
        # T=4s V2V 수신 → 즉시 0.55 점프
        # T=4s~7s : 0.55 → 0.85 (V2V 가 다가오는 보행자 추적)
        # T>=7s : 실제 등장 → 0.95+
        if t < 4.0:
            base = 0.18 + 0.04 * t                       # 0.18 → 0.34
        elif t < 7.0:
            jump = 0.55 + (t - 4.0) / 3.0 * 0.30         # 0.55 → 0.85
            base = jump
        else:
            base = min(0.97, 0.85 + (t - 7.0) * 0.12)
        base += random.uniform(-0.012, 0.012)
        risks.append(float(max(0.0, min(0.98, base))))

        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _add_rain_overlay(img: np.ndarray, intensity: float = 1.0) -> np.ndarray:
    """우천 효과 — 빗줄기 + 회색조 + 시야 흐림."""
    h, w = img.shape[:2]
    out = img.astype(np.float32)
    # 회색-청색 톤으로 desaturate
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR).astype(np.float32)
    out = cv2.addWeighted(out, 0.5, gray3, 0.5, 0)
    out *= 0.78  # 어둡게
    out[..., 0] += 18  # B 살짝 강조

    # 빗줄기 (대각선 짧은 선 ~ 200개)
    n = int(180 * intensity)
    rain_layer = np.zeros((h, w, 3), dtype=np.uint8)
    for _ in range(n):
        x = int(np.random.rand() * w)
        y = int(np.random.rand() * h * 0.85)
        ln = int(8 + np.random.rand() * 20)
        cv2.line(rain_layer, (x, y), (x - 4, y + ln), (220, 220, 230), 1)
    out = np.clip(out + rain_layer.astype(np.float32) * 0.55, 0, 255)

    return out.astype(np.uint8)


def _synthesize_rainy_intersection(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = SYNTH_FRAMES) -> Tuple[List[np.ndarray], List[float]]:
    """
    우천 + 혼잡 교차로. 시야가 흐리고 대형차가 잠시 멈춘 사이 보행자가 우산 쓰고 횡단.
    T=5s 우산 보행자 등장. 우천 occlusion 으로 인해 lead time 짧음.
    """
    out_frames = []
    risks = []
    for i in range(frames):
        t = i / OUTPUT_FPS
        img = _draw_scene_base(w, h)

        # 횡단보도
        for k in range(6):
            x1 = int(w * 0.20 + k * w * 0.11)
            x2 = x1 + int(w * 0.08)
            y1 = int(h * 0.66)
            y2 = y1 + int(h * 0.03)
            cv2.rectangle(img, (x1, y1), (x2, y2), (180, 180, 180), -1)

        # 정차한 차들 (양쪽으로 두 대)
        for ox in [int(w * 0.15), int(w * 0.62)]:
            cv2.rectangle(img, (ox, int(h * 0.55)), (ox + int(w * 0.22), int(h * 0.78)),
                          (44, 44, 60), -1)

        # 우산 보행자 — T=5s 부터 등장 (우산은 검정 반원)
        if t >= 5.0:
            prog = min(1.0, (t - 5.0) / 2.5)
            px = int(w * (0.78 - 0.50 * prog))
            py = int(h * 0.74)
            # 우산 (반원)
            cv2.ellipse(img, (px, py - int(48 * h / 540)),
                        (int(28 * w / 960), int(20 * h / 540)),
                        0, 180, 360, (28, 28, 32), -1)
            cv2.ellipse(img, (px, py - int(48 * h / 540)),
                        (int(28 * w / 960), int(20 * h / 540)),
                        0, 180, 360, (180, 180, 200), 2)
            # 우산 손잡이
            cv2.line(img, (px, py - int(48 * h / 540)), (px, py - int(8 * h / 540)),
                     (170, 170, 190), 2)
            # 사람
            cv2.circle(img, (px, py - int(8 * h / 540)), int(8 * w / 960), (240, 220, 200), -1)
            cv2.rectangle(img, (px - int(9 * w / 960), py),
                          (px + int(9 * w / 960), py + int(28 * h / 540)),
                          (60, 80, 130), -1)

        # 우천 효과 — 매 프레임 randomization
        img = _add_rain_overlay(img, intensity=1.0)

        # Risk: 우천 baseline 0.32 → T=5s 보행자 등장 후 급상승
        if t < 5.0:
            base = 0.32 + 0.05 * t
        else:
            base = min(0.95, 0.62 + (t - 5.0) * 0.20)
        base += random.uniform(-0.015, 0.015)
        risks.append(float(max(0.0, min(0.97, base))))

        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _synthesize_night_blindspot(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = SYNTH_FRAMES) -> Tuple[List[np.ndarray], List[float]]:
    """야간 사각지대 — 어두운 도로, 헤드라이트 콘, 가려진 보행자."""
    out_frames = []
    risks = []
    for i in range(frames):
        t = i / OUTPUT_FPS
        # 아주 어두운 베이스
        img = np.full((h, w, 3), 8, dtype=np.uint8)
        img[:int(h * 0.55), :] = (16, 14, 18)   # 야간 하늘
        img[int(h * 0.55):, :] = (12, 11, 14)   # 도로

        # 헤드라이트 콘 (ego 차에서 전방으로 두 갈래)
        ego_y = h
        for cx_off in [-int(w * 0.10), int(w * 0.10)]:
            cone = np.zeros((h, w, 3), dtype=np.uint8)
            apex = (int(w / 2 + cx_off), ego_y)
            far_l = (int(w * 0.25), int(h * 0.55))
            far_r = (int(w * 0.75), int(h * 0.55))
            pts = np.array([apex, far_l, far_r], dtype=np.int32)
            cv2.fillPoly(cone, [pts], (180, 200, 230))
            cone = cv2.GaussianBlur(cone, (0, 0), sigmaX=80 * w / 960, sigmaY=80 * w / 960)
            img = cv2.add(img, (cone * 0.35).astype(np.uint8))

        # 횡단보도 (헤드라이트 영역 안에서만 보임)
        for k in range(6):
            x1 = int(w * 0.30 + k * w * 0.08)
            x2 = x1 + int(w * 0.06)
            y1 = int(h * 0.66)
            y2 = y1 + int(h * 0.025)
            cv2.rectangle(img, (x1, y1), (x2, y2), (160, 165, 175), -1)

        # 마주오는 차 (헤드라이트 두 점)
        on_x = int(w * 0.70)
        on_y = int(h * 0.50)
        cv2.circle(img, (on_x, on_y), int(10 * w / 960), (235, 240, 245), -1)
        cv2.circle(img, (on_x + int(40 * w / 960), on_y), int(10 * w / 960), (235, 240, 245), -1)
        # 글로우
        for r_off in (16, 26, 38):
            cv2.circle(img, (on_x, on_y), int(r_off * w / 960), (90, 110, 130), 1)
            cv2.circle(img, (on_x + int(40 * w / 960), on_y), int(r_off * w / 960), (90, 110, 130), 1)

        # 사이드 사각지대 보행자 — T=4s 부터 좌측 어두운 곳에서 다가옴
        if t >= 4.0:
            prog = min(1.0, (t - 4.0) / 4.0)
            px = int(w * (0.04 + 0.30 * prog))
            py = int(h * (0.78 - 0.04 * prog))
            # 그림자에서 점점 드러남
            alpha = min(1.0, prog * 1.5)
            color = (int(40 + 100 * alpha), int(50 + 100 * alpha), int(90 + 100 * alpha))
            cv2.circle(img, (px, py - int(20 * h / 540)), int(9 * w / 960), color, -1)
            cv2.rectangle(img, (px - int(8 * w / 960), py - int(10 * h / 540)),
                          (px + int(8 * w / 960), py + int(20 * h / 540)),
                          (int(60 * alpha), int(60 * alpha), int(120 * alpha)), -1)

        # 약한 비넷·노이즈
        noise = (np.random.rand(h, w, 3) * 6).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        # Risk: 어두움 baseline 0.25 → T=4s 부터 보행자 진입 → 급상승
        if t < 4.0:
            base = 0.25 + 0.04 * t
        else:
            base = min(0.96, 0.50 + (t - 4.0) * 0.16)
        base += random.uniform(-0.012, 0.012)
        risks.append(float(max(0.0, min(0.97, base))))

        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


_PRESETS = {
    "crosswalk_truck": _synthesize_crosswalk_truck,
    "motorcycle_blindspot": _synthesize_motorcycle_blindspot,
    "signal_occluded": _synthesize_signal_occluded,
    "v2v_collab": _synthesize_v2v_collab,
    "rainy_intersection": _synthesize_rainy_intersection,
    "night_blindspot": _synthesize_night_blindspot,
}


def synthesize(preset: str, out_name: str) -> ReenactmentResult:
    if preset not in _PRESETS:
        raise ValueError(f"unknown preset: {preset}")

    frames, risks = _PRESETS[preset]()
    rendered = []
    peak_idx = int(np.argmax(risks))
    peak_t = peak_idx / OUTPUT_FPS
    for i, (f, r) in enumerate(zip(frames, risks)):
        t = i / OUTPUT_FPS
        rendered.append(_draw_hud(f, r, t, peak_t))

    lead_time_s = 0.0
    for i, v in enumerate(risks):
        if v >= RISK_THRESHOLD:
            lead_time_s = max(0.0, peak_t - (i / OUTPUT_FPS))
            break

    out_path = OUT_DIR / f"{out_name}.mp4"
    _write_video(rendered, out_path, fps=OUTPUT_FPS, risks=risks)
    return ReenactmentResult(
        video_url=f"/uploads/scenarios/{out_path.name}",
        video_path=str(out_path),
        frame_count=len(rendered),
        risk_curve=risks,
        lead_time_s=lead_time_s,
        peak_risk=float(max(risks)),
        name=out_name,
    )


def list_recent(limit: int = 20) -> List[dict]:
    items = []
    for p in sorted(OUT_DIR.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        items.append({
            "name": p.stem,
            "video_url": f"/uploads/scenarios/{p.name}",
            "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            "size_kb": round(p.stat().st_size / 1024, 1),
        })
    return items
