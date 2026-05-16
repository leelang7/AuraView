"""
Bus-Aware Pedestrian Prior — 버스가 신호등을 가린 상황 특화 인지.

핵심 가설:
  - HydraNet 이 전방에 "bus" 검출 → 그 너머 보행자 위험 ↑
  - 버스 정류장이 근처에 있다면 버스가 정차 중 / 정차 후 출발 ↑
  - 정차 후 출발 시점에 "버스 뒤에서 보행자가 길 건너기" 패턴이 사고 다발

데이터 소스 (v2 2026-05-15 BIS 실시간 위치 통합 완료):
  - 서울시 BIS 실시간 버스 위치 (openapi.seoul.go.kr/SearchBusInfoServiceWGS84)
  - 국토부 K-MaaS / 한국교통안전공단 BIS API (정류장 좌표 + 노선)
  - 자체 사고 학습 prior

본 모듈은 외부 API 키 (`BIS_KEY`) 미설정 시 시연용 fallback 정류장+버스 fixture 로 동작.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("auraview.bus_aware")

ALLOW_FALLBACK = os.getenv("ALLOW_FALLBACK", "1") == "1"
DEFAULT_TIMEOUT = float(os.getenv("PUBLIC_API_TIMEOUT", "3.0"))

# BIS 실시간 버스 위치 API (서울)
BIS_BASE_URL = os.getenv("BIS_BASE_URL", "http://openapi.seoul.go.kr:8088")
BIS_KEY = os.getenv("BIS_KEY", os.getenv("BIKE_KEY", ""))

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

# 시연용 BIS 실시간 버스 위치 — 정류장 30~120m 반경에 분포
# 각 버스의 stopFlag: 1=정차중, 0=주행중. 출발 직후 (stopFlag=0 + 정류장 근처) 가 가장 위험.
_DEMO_LIVE_BUSES = [
    {"plainNo": "서울74사1024", "routeId": "100100094", "routeName": "152",  "lat": 37.5650, "lon": 127.0075, "speed_kmh":  0, "stopFlag": 1, "nextStop": "100400118"},
    {"plainNo": "서울74사1142", "routeId": "100100118", "routeName": "271",  "lat": 37.5719, "lon": 127.0091, "speed_kmh":  4, "stopFlag": 0, "nextStop": "100400119"},
    {"plainNo": "서울75사2087", "routeId": "100100007", "routeName": "146",  "lat": 37.5042, "lon": 127.0468, "speed_kmh":  0, "stopFlag": 1, "nextStop": "104000201"},
    {"plainNo": "서울75사1018", "routeId": "100100201", "routeName": "9404", "lat": 37.4977, "lon": 127.0274, "speed_kmh":  3, "stopFlag": 0, "nextStop": "104000202"},
    {"plainNo": "서울74사3091", "routeId": "100100018", "routeName": "150",  "lat": 37.5716, "lon": 126.9767, "speed_kmh": 12, "stopFlag": 0, "nextStop": "120000301"},
    {"plainNo": "서울74사4011", "routeId": "100100199", "routeName": "270",  "lat": 37.5572, "lon": 126.9239, "speed_kmh":  0, "stopFlag": 1, "nextStop": "121000401"},
]

# (lat, lon, ts) cache — 동일 좌표 1초 내 재호출 방지
_BUS_CACHE: Dict[str, Dict[str, Any]] = {}


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
    # v2 2026-05-15: BIS 실시간 버스 위치 통합
    live_bus_count_nearby: int = 0          # 100m 내 실시간 버스 대수
    live_buses: List[Dict[str, Any]] = field(default_factory=list)  # plainNo·route·distance·stopFlag
    live_data_mode: str = "stub"            # "live" | "stub" | "error"
    boost_source: str = "rule"              # "rule" | "bis_live" — 정확도 출처

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
            "live_bus_count_nearby": self.live_bus_count_nearby,
            "live_buses": self.live_buses,
            "live_data_mode": self.live_data_mode,
            "boost_source": self.boost_source,
        }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_nearby_stops(lat: float, lon: float, radius_m: float = 80.0) -> List[Dict[str, Any]]:
    """좌표 인근 정류장 — BIS API 호출 또는 fallback fixture.

    v2 2026-05-15: 서울시 BIS API (openapi.seoul.go.kr/getStationsByPosList) 호출 시도 후
    실패 시 _DEMO_STOPS fallback. BIS_KEY 미설정 시 즉시 fallback.
    """
    if BIS_KEY:
        try:
            url = f"{BIS_BASE_URL}/{BIS_KEY}/json/SearchSTNBYPOS/1/30/{lon}/{lat}/{int(radius_m)}"
            r = requests.get(url, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            data = r.json() or {}
            rows = (data.get("SearchSTNBYPOS") or {}).get("row") or []
            nearby = []
            for s in rows:
                try:
                    nearby.append({
                        "id":   str(s.get("STATION_ID") or s.get("STOP_ID") or ""),
                        "name": s.get("STATION_NM_KOR") or s.get("STOP_NAME") or "",
                        "lat":  float(s.get("Y") or s.get("LAT") or 0),
                        "lon":  float(s.get("X") or s.get("LON") or 0),
                        "distance_m": float(s.get("DIST") or _haversine_m(lat, lon, float(s.get("Y", 0)), float(s.get("X", 0)))),
                    })
                except Exception:
                    continue
            nearby.sort(key=lambda x: x["distance_m"])
            if nearby:
                return nearby
        except Exception as exc:
            log.warning("BIS stops API failed at (%s,%s): %s", lat, lon, exc)

    if ALLOW_FALLBACK:
        nearby = []
        for s in _DEMO_STOPS:
            d = _haversine_m(lat, lon, s["lat"], s["lon"])
            if d <= radius_m * 6:  # 시연용 더 넉넉
                nearby.append({**s, "distance_m": d})
        nearby.sort(key=lambda x: x["distance_m"])
        return nearby
    return []


def fetch_live_buses_nearby(lat: float, lon: float, radius_m: float = 150.0) -> Dict[str, Any]:
    """반경 N m 내 실시간 버스 위치 — BIS 노선조회 API 또는 fallback fixture.

    v2 2026-05-15 신규.
    반환: {"mode": "live"|"stub"|"error", "buses": [...], "count": int}
    각 버스: plainNo, routeName, lat, lon, speed_kmh, stopFlag(1정차/0주행), distance_m
    """
    cache_key = f"{round(lat, 4)}_{round(lon, 4)}"
    cached = _BUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < 1.0:
        return cached["data"]

    if BIS_KEY:
        try:
            # SearchBusInfoServiceWGS84 — 가장 가까운 정류장의 실시간 버스 도착
            # 실제 운영에서는 정류장→버스 도착정보 다단 호출이 필요. 여기서는 단순 데모.
            url = f"{BIS_BASE_URL}/{BIS_KEY}/json/getBusPosByVehId/1/30/{lon}/{lat}"
            r = requests.get(url, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            data = r.json() or {}
            rows = (data.get("ServiceResult") or data.get("itemList") or [])
            buses = []
            for b in (rows if isinstance(rows, list) else []):
                try:
                    blat, blon = float(b.get("gpslati") or 0), float(b.get("gpslong") or 0)
                    d = _haversine_m(lat, lon, blat, blon)
                    buses.append({
                        "plainNo": b.get("vehicleno") or b.get("plainNo") or "",
                        "routeName": b.get("routenm") or b.get("ROUTE_NM") or "",
                        "lat": blat, "lon": blon,
                        "speed_kmh": float(b.get("vehSpeed") or b.get("SPEED") or 0),
                        "stopFlag": int(b.get("stopFlag") or b.get("STOP_FLAG") or 0),
                        "distance_m": round(d, 1),
                    })
                except Exception:
                    continue
            buses = [b for b in buses if b["distance_m"] <= radius_m]
            buses.sort(key=lambda x: x["distance_m"])
            res = {"mode": "live", "buses": buses, "count": len(buses)}
            _BUS_CACHE[cache_key] = {"ts": time.time(), "data": res}
            return res
        except Exception as exc:
            log.warning("BIS bus-position API failed at (%s,%s): %s", lat, lon, exc)
            if not ALLOW_FALLBACK:
                return {"mode": "error", "buses": [], "count": 0, "detail": str(exc)[:120]}

    # fallback (시연용 fixture)
    buses = []
    for b in _DEMO_LIVE_BUSES:
        d = _haversine_m(lat, lon, b["lat"], b["lon"])
        if d <= radius_m:
            buses.append({**b, "distance_m": round(d, 1)})
    buses.sort(key=lambda x: x["distance_m"])
    res = {"mode": "stub", "buses": buses, "count": len(buses)}
    _BUS_CACHE[cache_key] = {"ts": time.time(), "data": res}
    return res


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

    # v2 2026-05-15: BIS 실시간 버스 위치 기반 정밀화
    #   ego 위치 100m 내 실제 stopFlag=1(정차중) 버스가 있으면 dwelling 으로 확정,
    #   stopFlag=0 + 정류장 30~80m 이고 speed≤5 면 'departing' 으로 확정 → boost 정확도 ↑.
    live = fetch_live_buses_nearby(ego_lat, ego_lon, radius_m=150.0)
    ctx.live_data_mode = live.get("mode", "stub")
    nearby_live = live.get("buses", []) or []
    ctx.live_bus_count_nearby = sum(1 for b in nearby_live if b.get("distance_m", 999) <= 100)
    ctx.live_buses = [
        {"plainNo": b.get("plainNo"), "routeName": b.get("routeName"),
         "distance_m": b.get("distance_m"), "speed_kmh": b.get("speed_kmh"),
         "stopFlag": b.get("stopFlag")}
        for b in nearby_live[:5]
    ]

    if nearby_live:
        nearest_bus = nearby_live[0]
        stop_flag = nearest_bus.get("stopFlag", 0)
        bus_speed = nearest_bus.get("speed_kmh", 0)
        bus_d = nearest_bus.get("distance_m", 999)
        if stop_flag == 1 and bus_d <= 60:
            ctx.estimated_state = "dwelling"
            ctx.pedestrian_prior_boost = max(ctx.pedestrian_prior_boost, 0.58)
            ctx.boost_reason = (f"BIS LIVE: 전방 {bus_d:.0f}m 버스 정차중 ({nearest_bus.get('routeName','?')}) — 보행자 횡단 위험 최대"
                                f" [mode={ctx.live_data_mode}]")
            ctx.boost_source = "bis_live"
        elif stop_flag == 0 and 0 < bus_speed <= 10 and bus_d <= 100:
            ctx.estimated_state = "departing"
            ctx.pedestrian_prior_boost = max(ctx.pedestrian_prior_boost, 0.50)
            ctx.boost_reason = (f"BIS LIVE: 전방 {bus_d:.0f}m 버스 출발 직후 ({nearest_bus.get('routeName','?')}, {bus_speed:.0f}km/h)"
                                f" — 뒤에서 보행자 횡단 패턴"
                                f" [mode={ctx.live_data_mode}]")
            ctx.boost_source = "bis_live"

    # 자차가 거의 정지 + 버스 검출 → 보행자 횡단 가능성 ↑
    if ego_speed_kmh is not None and ego_speed_kmh < 5.0:
        ctx.pedestrian_prior_boost = min(0.65, ctx.pedestrian_prior_boost + 0.10)
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
