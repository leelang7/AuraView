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
import subprocess
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

# 합성 시나리오 출력 해상도 (Full HD)
SYNTH_W = 1920
SYNTH_H = 1080


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


def _write_video(frames: List[np.ndarray], out_path: Path, fps: int = OUTPUT_FPS) -> Path:
    if not frames:
        raise RuntimeError("no frames to write")
    h, w = frames[0].shape[:2]
    # mp4v: 브라우저 호환성을 위해 H.264 우선, 실패하면 mp4v fallback
    temp_path = out_path.with_suffix(".raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(temp_path), fourcc, fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()

    # Try transcode to H.264 for broad browser support
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(temp_path), "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
            check=True, capture_output=True, timeout=90,
        )
        temp_path.unlink(missing_ok=True)
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
    _write_video(frames_out, out_path, fps=SAMPLE_FPS * 2)
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
    """시네마틱 도로 베이스 — 그라디언트 하늘 + 원근 도로 + 대기 원근감 + 차선."""
    s = w / 960.0
    img = np.zeros((h, w, 3), dtype=np.uint8)

    # ── 1) 하늘 — 일출/저녁 무드 그라디언트 (지평선에 따뜻한 톤)
    sky_h = int(h * 0.55)
    for y in range(sky_h):
        t = y / max(1, sky_h)
        # 위쪽: 진한 네이비 → 지평선: 옅은 청록·핑크
        b = int(38 + 100 * t)        # blue
        g = int(28 + 90 * t)         # green
        r = int(22 + 130 * t)        # red (지평선에서 따뜻하게)
        img[y, :] = (b, g, r)

    # ── 2) 도로 — 어두운 아스팔트 + 약한 노이즈 (디테일감)
    cv2.rectangle(img, (0, sky_h), (w, h), (16, 16, 22), -1)
    # 도로에 미세 노이즈 (10% 강도)
    noise = (np.random.rand(h - sky_h, w, 3) * 14).astype(np.int16)
    img[sky_h:, :] = np.clip(img[sky_h:, :].astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # ── 3) 도로 가장자리 (원근 라인) — 그라디언트 두께
    edge_color = (130, 130, 145)
    cv2.line(img, (int(w*0.5), sky_h), (int(w*0.10), h), edge_color, max(2, int(3*s)))
    cv2.line(img, (int(w*0.5), sky_h), (int(w*0.90), h), edge_color, max(2, int(3*s)))

    # ── 4) 중앙 점선 — 원근에 따라 굵어짐
    for i in range(7):
        prog = i / 6.0
        y1 = int(sky_h + prog * (h - sky_h) * 0.95)
        y2 = y1 + int(h * (0.018 + prog * 0.025))
        thick = max(2, int((1 + prog * 4) * s))
        cv2.line(img, (int(w * 0.5), y1), (int(w * 0.5), y2),
                 (215, 215, 110), thick)

    # ── 5) 대기 원근감 (지평선 부근 옅은 안개 layer)
    haze = np.zeros_like(img)
    haze_h = int(h * 0.18)
    for y in range(sky_h - haze_h // 2, sky_h + haze_h // 2):
        if y < 0 or y >= h: continue
        alpha = 1.0 - abs(y - sky_h) / (haze_h / 2)
        haze[y, :] = (int(120 * alpha), int(110 * alpha), int(105 * alpha))
    img = cv2.addWeighted(img, 1.0, haze, 0.45, 0)

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


def _synthesize_crosswalk_truck(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = 240) -> Tuple[List[np.ndarray], List[float]]:
    """대형차가 전방 횡단보도를 가리고 있다가, 보행자가 T=7초에 등장하는 장면."""
    out_frames = []
    risks = []
    for i in range(frames):
        t = i / OUTPUT_FPS     # 초 단위
        img = _draw_scene_base(w, h)

        # 횡단보도 stripes (차 뒤쪽에 있는 것처럼)
        for k in range(6):
            x1 = int(w * 0.20 + k * w * 0.11)
            x2 = x1 + int(w * 0.08)
            y1 = int(h * 0.66)
            y2 = y1 + int(h * 0.03)
            cv2.rectangle(img, (x1, y1), (x2, y2), (220, 220, 220), -1)

        # 전방 트럭: 중앙에서 점점 가까워지며 횡단보도를 가림
        truck_scale = 0.3 + 0.02 * i
        truck_w = int(w * min(0.7, truck_scale))
        truck_h = int(h * min(0.5, truck_scale * 0.85))
        tx = (w - truck_w) // 2
        ty = int(h * 0.58) - int(truck_h * 0.15)
        cv2.rectangle(img, (tx, ty), (tx + truck_w, ty + truck_h), (40, 40, 55), -1)
        cv2.rectangle(img, (tx, ty), (tx + truck_w, ty + truck_h), (180, 80, 80), 2)
        cv2.putText(img, "TRUCK", (tx + 10, ty + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 230), 2)

        # 보행자: T=7초부터 오른쪽에서 횡단 시작 (트럭 뒤에서 나타남)
        ped_visible = t >= 7.0
        if ped_visible:
            prog = min(1.0, (t - 7.0) / 2.0)
            px = int(w * (0.82 - 0.45 * prog))
            py = int(h * 0.70)
            cv2.circle(img, (px, py - 22), 10, (240, 220, 200), -1)
            cv2.rectangle(img, (px - 8, py - 12), (px + 8, py + 18), (220, 60, 60), -1)

        # 합성 risk: 트럭 occlusion 기반으로 증가, 보행자 등장 시 급등
        occlusion = min(1.0, truck_w / (w * 0.7))
        base_risk = occlusion * 0.45
        if ped_visible:
            base_risk = min(0.97, base_risk + 0.35 + 0.3 * ((t - 7.0) / 2.0))
        else:
            # AuraView는 occluded shadow로 미리 서서히 증가
            if t >= 4.0:
                base_risk = min(0.7, base_risk + 0.15 * (t - 4.0))
        base_risk += random.uniform(-0.015, 0.015)
        base_risk = float(max(0.0, min(0.98, base_risk)))
        risks.append(base_risk)

        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _synthesize_motorcycle_blindspot(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = 240) -> Tuple[List[np.ndarray], List[float]]:
    """측면 사각지대에서 이륜차가 추월 접근."""
    out_frames = []
    risks = []
    for i in range(frames):
        t = i / OUTPUT_FPS
        img = _draw_scene_base(w, h)

        # 앞 차량 (우측 차로)
        car_x = int(w * 0.58)
        car_y = int(h * 0.62)
        cv2.rectangle(img, (car_x, car_y), (car_x + int(w*0.18), car_y + int(h*0.16)), (60, 60, 80), -1)

        # 이륜차: T=3초부터 좌측 사각지대에서 서서히 접근
        moto_visible = t >= 3.0
        if moto_visible:
            prog = min(1.0, (t - 3.0) / 5.0)
            mx = int(w * (0.02 + 0.25 * prog))
            my = int(h * (0.65 + 0.12 * prog))
            ms = int(8 + 20 * prog)
            cv2.circle(img, (mx + ms, my), ms, (220, 220, 40), -1)
            cv2.circle(img, (mx + ms, my + int(ms*1.6)), ms, (220, 220, 40), -1)
            cv2.line(img, (mx + ms, my), (mx + ms, my + int(ms*1.6)), (220, 220, 40), 3)

        # risk: occluded 측면에서 서서히 증가 → 가까워지며 급등
        base_risk = 0.12 + 0.04 * t
        if moto_visible:
            base_risk = min(0.96, 0.32 + 0.16 * (t - 3.0))
        base_risk += random.uniform(-0.01, 0.01)
        risks.append(float(max(0.0, min(0.98, base_risk))))
        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _synthesize_signal_occluded(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = 240) -> Tuple[List[np.ndarray], List[float]]:
    """신호등이 전방 버스에 가려져 있다가, 앞차가 급감속하는 장면."""
    out_frames = []
    risks = []
    for i in range(frames):
        t = i / OUTPUT_FPS
        img = _draw_scene_base(w, h)

        # 버스
        bus_w = int(w * 0.55)
        bus_h = int(h * 0.38)
        bx = (w - bus_w) // 2
        by = int(h * 0.40)
        cv2.rectangle(img, (bx, by), (bx + bus_w, by + bus_h), (55, 60, 90), -1)
        cv2.rectangle(img, (bx, by), (bx + bus_w, by + bus_h), (180, 180, 240), 2)
        cv2.putText(img, "BUS", (bx + 16, by + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 230), 2)
        # 버스 브레이크등 점멸 (T>5)
        if t >= 5.0 and (i // 4) % 2 == 0:
            cv2.rectangle(img, (bx + 20, by + bus_h - 14), (bx + 60, by + bus_h - 4), (0, 0, 255), -1)
            cv2.rectangle(img, (bx + bus_w - 60, by + bus_h - 14), (bx + bus_w - 20, by + bus_h - 4), (0, 0, 255), -1)

        # risk: 신호 가림 + 버스 감속 임박
        base_risk = 0.18 + 0.03 * t
        if t >= 5.0:
            base_risk = min(0.95, 0.42 + 0.14 * (t - 5.0))
        base_risk += random.uniform(-0.015, 0.015)
        risks.append(float(max(0.0, min(0.98, base_risk))))
        out_frames.append(_apply_cinematic_post(img))
    return out_frames, risks


def _synthesize_v2v_collab(w: int = SYNTH_W, h: int = SYNTH_H, frames: int = 240) -> Tuple[List[np.ndarray], List[float]]:
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


_PRESETS = {
    "crosswalk_truck": _synthesize_crosswalk_truck,
    "motorcycle_blindspot": _synthesize_motorcycle_blindspot,
    "signal_occluded": _synthesize_signal_occluded,
    "v2v_collab": _synthesize_v2v_collab,
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
    _write_video(rendered, out_path, fps=OUTPUT_FPS)
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
