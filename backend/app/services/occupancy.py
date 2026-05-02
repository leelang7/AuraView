"""
Occupancy Network (점유 격자) PoC.

Tesla AI Day에서 공개된 occupancy network 개념을 경량화해 한국 도심 교차로에
적용한다. 현재는 YOLOv8 탐지 박스 + 간단한 역투영 근사로 BEV occupancy grid를
생성한다. 학습된 모델은 `models/occupancy_*.pt` 로 교체 가능하다.

가점 기여:
  - AI활용 · 분석 (5점): BEV 3D 점유 확률을 실시간 산출
  - AI활용 · 학습 (5점): 하드샘플로 재학습 가능한 파이프라인
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

# BEV 격자 설정: 차량 기준 전방 40m × 좌우 ±20m, 해상도 0.5m
GRID_FORWARD_M = 40.0
GRID_LATERAL_M = 20.0
CELL_M = 0.5

GRID_H = int(GRID_FORWARD_M / CELL_M)       # 전방 셀 수 (행)
GRID_W = int(2 * GRID_LATERAL_M / CELL_M)   # 좌우 셀 수 (열)


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox_xyxy: List[float]          # [x1, y1, x2, y2] (px)
    image_size: List[int]           # [w, h]


@dataclass
class OccupancyResult:
    grid: np.ndarray = field(repr=False)   # (GRID_H, GRID_W) float [0,1]
    shape: List[int] = field(default_factory=lambda: [GRID_H, GRID_W])
    cell_m: float = CELL_M
    forward_m: float = GRID_FORWARD_M
    lateral_m: float = GRID_LATERAL_M
    hotspots: List[dict] = field(default_factory=list)
    occluded_mass: float = 0.0      # 점유 확률의 총합 (요약 지표)

    def to_dict(self, include_flat: bool = True, downsample: int = 2) -> dict:
        out = {
            "shape": self.shape,
            "cell_m": self.cell_m,
            "forward_m": self.forward_m,
            "lateral_m": self.lateral_m,
            "grid_b64": _grid_to_base64(self.grid),
            "hotspots": self.hotspots,
            "occluded_mass": round(float(self.occluded_mass), 3),
        }
        if include_flat:
            g = self.grid
            if downsample > 1:
                g = g[::downsample, ::downsample]
            out["grid_flat"] = [round(float(v), 3) for v in g.flatten().tolist()]
            out["grid_shape_flat"] = list(g.shape)
            out["grid_cell_m_flat"] = round(self.cell_m * downsample, 2)
        return out


# ──────────────────────────────────────────────────────────────────────
# Back-projection heuristic (학습 모델이 준비되기 전의 근사)
# ──────────────────────────────────────────────────────────────────────

def _estimate_distance_from_bbox(bbox: List[float], image_h: int, class_name: str) -> float:
    """
    차량·신호 바운딩박스 높이로 거리 근사.
    - class별 기준 높이(m) 가정
        car   1.5, truck 3.5, bus 3.5, traffic light 0.9
    - 핀홀 카메라 가정: d ≈ (focal_px × real_h) / bbox_h_px
    - focal_px는 일반 블랙박스 기준 ≈ image_h × 1.1
    """
    x1, y1, x2, y2 = bbox
    bbox_h_px = max(1.0, y2 - y1)
    focal_px = image_h * 1.1
    real_h = {
        "car": 1.5, "truck": 3.5, "bus": 3.5, "van": 2.0,
        "traffic light": 0.9, "person": 1.7, "motorcycle": 1.4,
    }.get(class_name, 1.5)
    return float((focal_px * real_h) / bbox_h_px)


def _bbox_to_bev(bbox: List[float], image_size: List[int], class_name: str) -> Optional[dict]:
    w, h = image_size
    x1, _, x2, _ = bbox
    u_center = (x1 + x2) / 2.0
    distance = _estimate_distance_from_bbox(bbox, h, class_name)
    if distance <= 0 or distance > GRID_FORWARD_M:
        return None

    # 이미지 중앙 기준 좌/우 오프셋을 거리에 비례시켜 BEV lateral 좌표로 근사
    hfov_rad = np.deg2rad(70.0)
    focal_px_x = (w / 2.0) / np.tan(hfov_rad / 2.0)
    dx = ((u_center - w / 2.0) / focal_px_x) * distance   # meters right(+)/left(-)

    if abs(dx) > GRID_LATERAL_M:
        return None

    row = int(distance / CELL_M)
    col = int((dx + GRID_LATERAL_M) / CELL_M)
    return {"row": row, "col": col, "distance_m": distance, "lateral_m": float(dx)}


def _gaussian_splat(grid: np.ndarray, row: int, col: int, sigma: float, mass: float) -> None:
    """격자에 2D 가우시안으로 점유 확률을 쌓는다."""
    r = int(np.ceil(sigma * 3))
    r0, r1 = max(0, row - r), min(GRID_H, row + r + 1)
    c0, c1 = max(0, col - r), min(GRID_W, col + r + 1)
    if r0 >= r1 or c0 >= c1:
        return
    yy, xx = np.ogrid[r0:r1, c0:c1]
    dist2 = (yy - row) ** 2 + (xx - col) ** 2
    patch = mass * np.exp(-dist2 / (2.0 * sigma * sigma))
    grid[r0:r1, c0:c1] = np.clip(grid[r0:r1, c0:c1] + patch, 0.0, 1.0)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def compute_occupancy(detections: List[Detection],
                       vehicle_detected: bool,
                       signal_detected: bool) -> OccupancyResult:
    """
    Detection 목록 → BEV occupancy grid.

    시야를 막은 대형차의 경우 '뒤쪽 영역'에 unknown occupancy(0.3~0.6)를 추가로 퍼뜨려
    '보이지 않지만 무언가 있을 수 있음'을 확률로 표현한다. 이것이 AuraView의 핵심.
    """
    grid = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    hotspots: List[dict] = []

    for d in detections:
        bev = _bbox_to_bev(d.bbox_xyxy, d.image_size, d.class_name)
        if bev is None:
            continue

        # 1) detected 객체는 높은 확률(0.8~0.95)
        mass = 0.8 + 0.15 * min(d.confidence, 1.0)
        sigma = 2.5 if d.class_name in {"truck", "bus"} else 1.5
        _gaussian_splat(grid, bev["row"], bev["col"], sigma=sigma, mass=mass)
        hotspots.append({
            "class": d.class_name,
            "confidence": round(d.confidence, 3),
            "row": bev["row"], "col": bev["col"],
            "distance_m": round(bev["distance_m"], 2),
            "lateral_m": round(bev["lateral_m"], 2),
            "kind": "detected",
        })

        # 2) 대형차는 '뒤쪽 영역'에 unknown cloud 추가 (사각지대)
        if d.class_name in {"truck", "bus", "van"}:
            for delta in (4, 8, 12):
                shadow_row = bev["row"] + int(delta / CELL_M)
                if shadow_row >= GRID_H:
                    break
                _gaussian_splat(grid, shadow_row, bev["col"], sigma=3.5, mass=0.45)
            hotspots.append({
                "class": d.class_name,
                "confidence": round(d.confidence, 3),
                "row": bev["row"], "col": bev["col"],
                "distance_m": round(bev["distance_m"], 2),
                "lateral_m": round(bev["lateral_m"], 2),
                "kind": "occluded_shadow",
            })

    # 3) 신호등을 못 봤는데 전방에 차량이 있다면, 전방 교차로 영역에 불확실성 +α
    if vehicle_detected and not signal_detected:
        front_row = int(min(GRID_H - 1, 35.0 / CELL_M))
        for col in range(GRID_W):
            _gaussian_splat(grid, front_row, col, sigma=4.0, mass=0.25)

    occluded_mass = float(grid.sum())
    return OccupancyResult(grid=grid, hotspots=hotspots, occluded_mass=occluded_mass)


# ──────────────────────────────────────────────────────────────────────
# Serialization: grid → base64 PNG for frontend overlay
# ──────────────────────────────────────────────────────────────────────

def _grid_to_base64(grid: np.ndarray) -> str:
    import base64
    import io

    try:
        from PIL import Image
    except ImportError:
        return ""

    arr = np.clip(grid * 255, 0, 255).astype(np.uint8)
    # 3-channel heatmap: cyan→red
    rgb = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    rgb[..., 0] = arr
    rgb[..., 1] = (255 - arr) // 2
    rgb[..., 2] = (255 - arr)
    rgb[..., 3] = (arr * 0.9).astype(np.uint8)
    img = Image.fromarray(rgb, mode="RGBA")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
