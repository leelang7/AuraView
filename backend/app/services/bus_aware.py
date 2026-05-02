"""
Bus-Aware Pedestrian Prior — 버스가 신호등을 가린 상황 특화 인지.

핵심 가설:
  - HydraNet 이 전방에 "bus" 검출 → 그 너머 보행자 위험 ↑
  - 버스 정류장이 근처에 있다면 버스가 정차 중 / 정차 후 출발 ↑
  - 정차 후 출발 시점에 "버스 뒤에서 보행자가 길 건너기" 패턴이 사고 다발

데이터 소스:
  - K-MaaS 또는 서울/부산 등 BIS API 의 정류장 좌표 + 노선
  - 자체 사고 학습 prior

본 모듈은 외부 API 키 미설정 시 시연용 fallback 정류장 데이터로 동작.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("auraview.bus_aware")

ALLOW_FALLBACK = os.getenv("ALLOW_FALLBACK", "1") == "1"

# 시연용 서울 시내 주요 정류장 (간소화)
_DEMO_STOPS = [
    {"id": "100400118", "name": "동대문역사문화공원", "lat": 37.5651, "lon": 127.0073},
    {"id": "100400119", "name": "동대문역",          "lat": 37.5717, "lon": 127.0095},
    {"id": "104000201", "name": "테헤란로 입구",      "lat": 37.5044, "lon": 127.0470},
    {"id": "104000202", "name": "강남역",            "lat": 37.4979, "lon": 127.0276},
    {"id": "120000301", "name": "광화문",            "lat": 37.5717, "lon": 126.9764},
    {"id": "120000302", "name": "종로4가",          "lat": 37.5703, "lon": 126.9908},
    {"id": "121000401", "name": "홍대입구",          "lat": 37.5571, "lon": 126.9241},
    {"id": "104000203", "name": "역삼역",            "lat": 37.5006, "lon": 127.0362},
]


@dataclass
class BusContext:
    bus_visible: bool = False
    bus_count: int = 0
    nearest_stop_id: Optional[str] = None
    nearest_stop_name: Optional[str] = None
    distance_to_stop_m: float = float("inf")
    estimated_state: str = "unknown"   # approaching / dwelling / departing / passing
    pedestrian_prior_boost: float = 0.0  # 0~0.6
    boost_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bus_visible": self.bus_visible,
            "bus_count": self.bus_count,
            "nearest_stop": (
                {"id": self.nearest_stop_id, "name": self.nearest_stop_name,
                 "distance_m": round(self.distance_to_stop_m, 1)}
                if self.nearest_stop_id else None
            ),
            "estimated_state": self.estimated_state,
            "pedestrian_prior_boost": round(self.pedestrian_prior_boost, 3),
            "boost_reason": self.boost_reason,
        }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_nearby_stops(lat: float, lon: float, radius_m: float = 80.0) -> List[Dict[str, Any]]:
    """좌표 인근 정류장 — K-MaaS / BIS API 호출 또는 fallback."""
    # TODO: 실제 K-MaaS 발급 후 채움.
    if ALLOW_FALLBACK:
        nearby = []
        for s in _DEMO_STOPS:
            d = _haversine_m(lat, lon, s["lat"], s["lon"])
            if d <= radius_m * 6:  # 시연용 더 넉넉
                nearby.append({**s, "distance_m": d})
        nearby.sort(key=lambda x: x["distance_m"])
        return nearby
    return []


def analyze(bus_detections: List[Dict[str, Any]],
            ego_lat: Optional[float], ego_lon: Optional[float],
            ego_speed_kmh: Optional[float] = None) -> BusContext:
    """
    HydraNet 이 본 bus 검출 + ego 위치 + 속도 → BusContext.

    bus_detections 항목 예: {"class_name":"bus","confidence":0.78,"bbox_xyxy":[...]}
    """
    ctx = BusContext()
    bus_count = sum(1 for d in bus_detections if d.get("class_name") == "bus")
    ctx.bus_visible = bus_count > 0
    ctx.bus_count = bus_count
    if not ctx.bus_visible:
        return ctx

    if ego_lat is None or ego_lon is None:
        ctx.estimated_state = "unknown_no_gps"
        ctx.pedestrian_prior_boost = 0.18
        ctx.boost_reason = "버스 검출 (위치 없음, 보수적 prior)"
        return ctx

    stops = fetch_nearby_stops(ego_lat, ego_lon, radius_m=120.0)
    if stops:
        nearest = stops[0]
        ctx.nearest_stop_id = nearest["id"]
        ctx.nearest_stop_name = nearest["name"]
        ctx.distance_to_stop_m = nearest["distance_m"]

        # 상태 추정 (간이): 거리 + 자차 속도로
        d = nearest["distance_m"]
        if d <= 30:
            ctx.estimated_state = "dwelling"
            ctx.pedestrian_prior_boost = 0.55
            ctx.boost_reason = "전방 버스 + 정류장 근접 (~30m) — 정차 후 보행자 횡단 위험 매우 높음"
        elif d <= 80:
            ctx.estimated_state = "departing"
            ctx.pedestrian_prior_boost = 0.42
            ctx.boost_reason = "버스가 정류장 출발 직후 — 뒤에서 보행자 횡단 패턴 다발"
        else:
            ctx.estimated_state = "passing"
            ctx.pedestrian_prior_boost = 0.22
            ctx.boost_reason = "버스 시야 가림 — 정류장에서 떨어져 통과 중"
    else:
        ctx.estimated_state = "passing"
        ctx.pedestrian_prior_boost = 0.20
        ctx.boost_reason = "버스 시야 가림 (정류장 정보 없음)"

    # 자차가 거의 정지 + 버스 검출 → 보행자 횡단 가능성 ↑
    if ego_speed_kmh is not None and ego_speed_kmh < 5.0:
        ctx.pedestrian_prior_boost = min(0.6, ctx.pedestrian_prior_boost + 0.10)
        ctx.boost_reason += " · 자차 정지"

    return ctx


def boost_occupancy(grid, bus_ctx: BusContext, forward_band=(20, 36), cell_m: float = 0.5):
    """
    BusContext 의 boost 를 occupancy grid 의 '버스 너머 영역' 에 가산.
    """
    if bus_ctx.pedestrian_prior_boost <= 0:
        return 0
    import numpy as np
    rows, cols = grid.shape
    r0 = max(0, int(forward_band[0] / cell_m))
    r1 = min(rows, int(forward_band[1] / cell_m))
    if r0 >= r1: return 0
    boost = bus_ctx.pedestrian_prior_boost
    grid[r0:r1, :] = np.clip(grid[r0:r1, :] + boost * 0.5, 0.0, 1.0)
    return (r1 - r0) * cols
