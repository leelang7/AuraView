"""YOLO11 도로 사용자 검출 + 실검출 기반 BEV 투영.

ML Kit/YOLOv8 대비 업그레이드:
  - YOLO11n (5.4MB, 모바일 TFLite ~3MB) — person/car/truck/bus/motorcycle/bicycle 정확 분류
  - 검출 결과를 occupancy.py 기하 투영으로 BEV 점유 격자에 올림 (스크립트 아님, 실검출 기반)

ultralytics 미설치 환경에서도 import 가 깨지지 않도록 lazy 로드.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import numpy as np

log = logging.getLogger(__name__)

# 모델 경로: 번들된 가중치 우선(CWD 무관, repo 기준 절대경로), 없으면 이름으로(자동 다운로드)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MODEL_PATH_CANDIDATES = [
    os.path.join(_REPO_ROOT, "models", "yolo11n.pt"),
    os.path.join("models", "yolo11n.pt"),
    "yolo11n.pt",
]

# COCO 80 → 도로 사용자 매핑 (관심 클래스만)
_ROAD_CLASS = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    9: "traffic_light",
    11: "stop_sign",
}
# 위험도(보행 약자 우선) 가중 — BEV 점유 mass 에 반영
_RISK_WEIGHT = {
    "person": 1.0, "bicycle": 0.9, "motorcycle": 0.85,
    "car": 0.6, "bus": 0.7, "truck": 0.7,
    "traffic_light": 0.0, "stop_sign": 0.0,
}

_model = None


def _lazy_load():
    global _model
    if _model is not None:
        return
    from ultralytics import YOLO  # heavy import
    path = next((p for p in _MODEL_PATH_CANDIDATES if os.path.exists(p)), _MODEL_PATH_CANDIDATES[-1])
    _model = YOLO(path)
    log.info("YOLO11 loaded: %s", path)


def available() -> bool:
    try:
        _lazy_load()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("YOLO11 unavailable: %s", exc)
        return False


def detect(image_path: str, conf: float = 0.30, imgsz: int = 640) -> Dict[str, Any]:
    """이미지 1장 → 도로 사용자 검출 목록 + 요약.

    반환: {ok, model, image_size, count, detections:[{cls, conf, box:[x,y,w,h], risk}], summary, ms}
    """
    import time
    try:
        _lazy_load()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "model": "yolo11n", "error": f"ultralytics 미설치: {exc}",
                "count": 0, "detections": []}

    t0 = time.time()
    res = _model.predict(source=image_path, conf=conf, imgsz=imgsz, verbose=False)[0]
    ih, iw = res.orig_shape

    dets: List[Dict[str, Any]] = []
    summary: Dict[str, int] = {}
    for b in res.boxes:
        c = int(b.cls.item())
        if c not in _ROAD_CLASS:
            continue
        name = _ROAD_CLASS[c]
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
        dets.append({
            "cls": name,
            "conf": round(float(b.conf.item()), 3),
            "box": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
            "risk": _RISK_WEIGHT.get(name, 0.5),
        })
        summary[name] = summary.get(name, 0) + 1

    return {
        "ok": True,
        "model": "yolo11n",
        "image_size": [iw, ih],
        "count": len(dets),
        "detections": dets,
        "summary": summary,
        "ms": round((time.time() - t0) * 1000, 1),
    }


def detect_to_bev(image_path: str, conf: float = 0.30, grid: int = 40,
                  forward_m: float = 40.0, lateral_m: float = 20.0) -> Dict[str, Any]:
    """검출 결과를 BEV 점유 격자로 투영 (실검출 기반 — 스크립트 아님).

    카메라 핀홀 모델(HFOV 70°)로 bbox 하단 중앙 → (전방거리, 횡방향) 추정 후
    gaussian splat 으로 점유 mass 적립. 사람/이륜에 가중.
    """
    d = detect(image_path, conf=conf)
    if not d.get("ok"):
        return {**d, "bev": None}

    iw, ih = d["image_size"]
    g = np.zeros((grid, grid), dtype="float32")
    cls_g = np.zeros((grid, grid), dtype="int8")  # 0 free,1 vehicle,2 vru,3 occlusion,5 signal
    hfov = np.deg2rad(70.0)
    focal = (iw / 2.0) / np.tan(hfov / 2.0)
    placed = []

    for det in d["detections"]:
        name = det["cls"]
        if name in ("traffic_light", "stop_sign"):
            continue
        x, y, w, h = det["box"]
        cx = x + w / 2.0
        # 전방 거리: bbox 높이/클래스 실제 높이 기반 근사 (핀홀)
        real_h = {"person": 1.7, "bicycle": 1.5, "motorcycle": 1.5,
                  "car": 1.5, "bus": 3.2, "truck": 3.5}.get(name, 1.6)
        dist = float(np.clip(real_h * focal / max(h, 1.0), 1.0, forward_m))
        # 횡방향(좌우): 광선 각도
        ang = (cx - iw / 2.0) / focal
        lateral = float(np.clip(dist * ang, -lateral_m, lateral_m))
        # ★ 실측 치수: bbox 폭(px) → 실제 폭(m) = w_px/focal × 거리 (핀홀)
        #   길이는 클래스 표준 종횡비로 폭에서 추정 (단일 프레임 깊이 한계)
        meas_w = float(w / focal * dist)
        clamp_w = {"person": (0.4, 0.8), "bicycle": (0.4, 0.8), "motorcycle": (0.5, 1.0),
                   "car": (1.6, 2.1), "bus": (2.3, 2.7), "truck": (2.0, 2.7)}.get(name, (1.6, 2.1))
        w_m = float(np.clip(meas_w, *clamp_w))
        ratio = {"car": 2.4, "truck": 3.0, "bus": 4.3, "motorcycle": 2.5,
                 "bicycle": 2.6, "person": 1.0}.get(name, 2.4)
        l_m = round(w_m * ratio, 2)
        # 격자 좌표
        row = int(np.clip(grid - 1 - (dist / forward_m) * (grid - 1), 0, grid - 1))
        col = int(np.clip((lateral + lateral_m) / (2 * lateral_m) * (grid - 1), 0, grid - 1))
        mass = _RISK_WEIGHT.get(name, 0.5)
        _splat(g, row, col, sigma=1.4, mass=mass)
        cls_g[row, col] = 2 if name in ("person", "bicycle", "motorcycle") else 1
        placed.append({"cls": name, "row": row, "col": col,
                       "distance_m": round(dist, 1), "lateral_m": round(lateral, 1),
                       "width_m": round(w_m, 2), "length_m": l_m})

    occ_mass = float(g.sum())
    return {
        "ok": True,
        "model": "yolo11n",
        "source": "live_detection",          # ★ 스크립트/하드코딩 아님
        "grid_shape": [grid, grid],
        "cell_m": round(forward_m / grid, 3),
        "forward_m": forward_m,
        "lateral_m": lateral_m,
        "grid_flat": [round(float(v), 3) for v in g.flatten()],
        "class_grid_flat": [int(v) for v in cls_g.flatten()],
        "occupied_mass": round(occ_mass, 2),
        "placed": placed,
        "summary": d["summary"],
        "ms": d["ms"],
    }


def _splat(grid: np.ndarray, row: int, col: int, sigma: float, mass: float) -> None:
    r = int(np.ceil(sigma * 3))
    r0, r1 = max(0, row - r), min(grid.shape[0], row + r + 1)
    c0, c1 = max(0, col - r), min(grid.shape[1], col + r + 1)
    if r0 >= r1 or c0 >= c1:
        return
    yy, xx = np.ogrid[r0:r1, c0:c1]
    dist2 = (yy - row) ** 2 + (xx - col) ** 2
    patch = mass * np.exp(-dist2 / (2.0 * sigma * sigma))
    grid[r0:r1, c0:c1] = np.clip(grid[r0:r1, c0:c1] + patch, 0.0, 1.0)
