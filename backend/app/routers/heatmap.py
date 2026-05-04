"""
TAAS 사고 히트맵 — Leaflet.heat 호환 좌표·강도 배열 반환.

  GET /heatmap/taas?bbox=...&year=2024
      서울 시내 등 bbox 범위 내 TAAS 사고이력 → [[lat, lon, weight], ...]

기능: TAAS 사고 분포의 시각적 융합 (메인 지도 토글).
"""

from __future__ import annotations

import random
from typing import Optional

from fastapi import APIRouter, Query

from ..services import public_api

router = APIRouter()


# 시연용 합성 사고 핫스팟 (TAAS 키 미발급 시 fallback)
_SEOUL_HOTSPOTS = [
    (37.5611, 127.0410, 1.0),  # 강남
    (37.5601, 127.0400, 0.85),
    (37.5045, 127.0490, 0.95),  # 잠실
    (37.5111, 126.9821, 0.7),   # 신촌
    (37.5521, 126.9388, 0.75),  # 마포·홍대
    (37.5661, 126.9784, 0.8),   # 광화문
    (37.5811, 127.0124, 0.9),   # 종로 4가
    (37.4921, 127.0331, 0.6),   # 강남구청
    (37.5301, 126.9990, 0.65),  # 한강대교
    (37.5191, 127.0431, 0.7),   # 청담
    (37.5841, 127.0561, 0.9),   # 청량리
    (37.5391, 127.0081, 0.6),   # 약수
    (37.5481, 126.9711, 0.75),  # 공덕
    (37.5081, 127.0631, 0.85),  # 잠실역 인근
    (37.5141, 127.1031, 1.0),   # 강동
]


def _expand_hotspots(seed_pts, n_per_seed=6, jitter=0.005):
    """heatmap 풍부하게 보이도록 각 시드 주변에 점 6개씩 무작위 산포."""
    out = []
    for lat, lon, w in seed_pts:
        for _ in range(n_per_seed):
            jl = lat + (random.random() - 0.5) * jitter * 2
            jn = lon + (random.random() - 0.5) * jitter * 2
            jw = max(0.2, min(1.0, w + (random.random() - 0.5) * 0.3))
            out.append([round(jl, 5), round(jn, 5), round(jw, 3)])
        out.append([lat, lon, w])  # 원점도 포함
    return out


@router.get("/taas")
def taas_heatmap(
    bbox_min_lat: Optional[float] = Query(None),
    bbox_max_lat: Optional[float] = Query(None),
    bbox_min_lon: Optional[float] = Query(None),
    bbox_max_lon: Optional[float] = Query(None),
    year: int = Query(2024, ge=2010, le=2030),
):
    """
    Leaflet.heat 가 받을 수 있는 [[lat, lon, intensity], ...] 형식 반환.
    TAAS 키가 없거나 응답 비면 시연용 합성 핫스팟 fallback.
    """
    bbox = None
    if None not in (bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon):
        bbox = {
            "minLat": bbox_min_lat, "maxLat": bbox_max_lat,
            "minLon": bbox_min_lon, "maxLon": bbox_max_lon,
        }

    raw = public_api.fetch_taas_accidents(bbox=bbox, year=year)
    accidents = raw.get("accidents", []) if isinstance(raw, dict) else []

    # 실 데이터가 있으면 정규화
    points = []
    for a in accidents:
        lat = a.get("lat") or a.get("latitude")
        lon = a.get("lon") or a.get("longitude")
        if lat is None or lon is None:
            continue
        sev = (a.get("severity") or "").lower()
        weight = 0.5
        if "사망" in sev or "killed" in sev: weight = 1.0
        elif "중상" in sev: weight = 0.85
        elif "경상" in sev: weight = 0.55
        points.append([float(lat), float(lon), weight])

    # 너무 sparse 하면 (≤ 3 포인트) 시연용 hotspot 으로 augment — 시각적 의미 확보
    if len(points) <= 3:
        random.seed(42)
        seed_points = points if points else []
        # 기존 실 데이터 보존 + 합성 hotspot 산포
        synthetic = _expand_hotspots(_SEOUL_HOTSPOTS, n_per_seed=8, jitter=0.004)
        points = seed_points + synthetic

    return {
        "year": year,
        "bbox": bbox,
        "count": len(points),
        "max_weight": max((p[2] for p in points), default=1.0),
        "points": points,
        "source": "TAAS open API + Seoul hotspots augmentation" if accidents else "시연용 합성 (TAAS 키 미설정 시)",
    }
