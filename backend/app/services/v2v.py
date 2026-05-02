"""
V2V Cross-Vehicle Perception — 차량간 협업 인지.

Tesla 도 못 하는 한국 특화 기술:
  - Tesla FSD = 자기 카메라가 본 것만 인지
  - AuraView V2V = "마주오는 차가 본 것" + "내가 본 것" 을 결합
                    → 내 사각지대를 다른 차의 시점이 메움
                    → 횡단보도에서 버스가 신호등을 가려도, 반대편 차가 "보행자 있음" 알려줌

핵심 메시지 (1차 발행):
  {
    "device_id": "<HMAC 가명>",
    "intersection_id": "1007",
    "ts": ISO,
    "lat": 37.56, "lon": 127.04,
    "heading_deg": 270,        # 0=N, 90=E, 180=S, 270=W
    "speed_kmh": 28.4,
    "detections": [
      {"class":"person","conf":0.87,"rel_lat":+0.00012,"rel_lon":-0.00005,"width_m":0.6}
    ],
    "occluded_mass": 142.3,
    "ttl_s": 8                 # 메시지 유효시간 (낮은 latency 우선)
  }

Fusion 로직:
  1. 같은 intersection_id 의 최근 ttl 안 메시지를 모음
  2. 각 peer 의 detection 을 ego 좌표계로 변환
  3. 두 차의 heading 이 ~180° 차이 (마주오는 차)면 신뢰도 가산
  4. 내 occupancy grid 의 unknown shadow 영역에 peer detection 이 있으면
     → 해당 셀 점유 확률 강하게 (0.9~) 부여 (내가 직접 못 봤지만 다른 차가 봤음)
"""

from __future__ import annotations

import hashlib
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional

# 메모리 풀 (간단 시연용 — 프로덕션은 Redis pub/sub 권장)
_POOL: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
_LOCK = Lock()
DEFAULT_TTL_S = 8
MAX_PER_INTERSECTION = 32

EARTH_R = 6_371_000  # m
DEG_PER_M_LAT = 1.0 / 111_320.0


def pseudonymize(device_id: str) -> str:
    """디바이스 ID 를 V2V 페어링용 단방향 해시로."""
    if not device_id:
        return "anon"
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────
# Pool ops
# ──────────────────────────────────────────────────────────────────────

def publish(message: Dict[str, Any]) -> Dict[str, Any]:
    """V2V 메시지 1건 풀에 게시. ts 누락시 자동 채움."""
    iid = str(message.get("intersection_id") or "unknown")
    if "ts" not in message:
        message = {**message, "ts": datetime.utcnow().isoformat()}
    if "device_id" in message:
        message = {**message, "device_id": pseudonymize(str(message["device_id"]))}
    if "ttl_s" not in message:
        message = {**message, "ttl_s": DEFAULT_TTL_S}

    with _LOCK:
        bucket = _POOL[iid]
        bucket.append(message)
        # bound + expire
        if len(bucket) > MAX_PER_INTERSECTION:
            del bucket[: len(bucket) - MAX_PER_INTERSECTION]
        _expire(iid)
    return {"accepted": True, "intersection_id": iid, "pool_size": len(_POOL[iid])}


def fetch(intersection_id: str) -> List[Dict[str, Any]]:
    with _LOCK:
        _expire(intersection_id)
        return list(_POOL.get(intersection_id, []))


def stats() -> Dict[str, Any]:
    with _LOCK:
        for iid in list(_POOL.keys()):
            _expire(iid)
        out = {iid: len(msgs) for iid, msgs in _POOL.items() if msgs}
        return {
            "intersections_active": len(out),
            "total_messages": sum(out.values()),
            "by_intersection": out,
        }


def _expire(iid: str):
    now = datetime.utcnow()
    bucket = _POOL.get(iid, [])
    fresh = []
    for m in bucket:
        ttl = float(m.get("ttl_s", DEFAULT_TTL_S))
        try:
            ts = datetime.fromisoformat(m["ts"].replace("Z", "+00:00").replace("+00:00", ""))
        except Exception:
            continue
        if (now - ts) <= timedelta(seconds=ttl):
            fresh.append(m)
    _POOL[iid] = fresh


# ──────────────────────────────────────────────────────────────────────
# Geometry helpers
# ──────────────────────────────────────────────────────────────────────

def _bearing_diff_deg(a: float, b: float) -> float:
    d = abs((a - b + 540) % 360 - 180)
    return d  # 0~180


def _meters_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine."""
    if None in (lat1, lon1, lat2, lon2):
        return float("inf")
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1); dp = math.radians(lat2 - lat1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _to_ego_bev(peer_lat: float, peer_lon: float, peer_heading: float,
                ego_lat: float, ego_lon: float, ego_heading: float) -> Dict[str, float]:
    """
    Peer 의 GPS 위치를 ego BEV 좌표로 (forward_m, lateral_m) 변환.
    forward+ = ego 진행방향, lateral+ = ego 의 우측.
    """
    dx_m = (peer_lon - ego_lon) / DEG_PER_M_LAT * math.cos(math.radians(ego_lat))
    dy_m = (peer_lat - ego_lat) / DEG_PER_M_LAT
    h = math.radians(ego_heading)
    forward = math.cos(h) * dy_m + math.sin(h) * dx_m
    lateral = -math.sin(h) * dy_m + math.cos(h) * dx_m
    return {"forward_m": forward, "lateral_m": lateral}


# ──────────────────────────────────────────────────────────────────────
# Fusion
# ──────────────────────────────────────────────────────────────────────

@dataclass
class V2VFusionResult:
    peers_used: int = 0
    oncoming_used: int = 0           # heading 이 마주오는 (≈180°) peer
    boosted_cells: int = 0           # occupancy grid 에 보강된 셀 수
    added_mass: float = 0.0          # boost로 늘어난 occluded_mass 총합
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def merge_into_occupancy(local_grid, ego_lat: float, ego_lon: float, ego_heading: float,
                         intersection_id: str,
                         cell_m: float, forward_m: float, lateral_m: float) -> V2VFusionResult:
    """
    ego 의 occupancy grid 에 V2V 풀의 peer 정보를 가산.

    grid: numpy 2D (rows=forward bins, cols=lateral bins)
    """
    import numpy as np
    rows, cols = local_grid.shape
    res = V2VFusionResult()

    peers = fetch(intersection_id)
    if not peers:
        res.note = "no peers"
        return res

    for peer in peers:
        plat = peer.get("lat"); plon = peer.get("lon")
        ph = float(peer.get("heading_deg", 0.0))
        if plat is None or plon is None:
            continue
        rel = _to_ego_bev(plat, plon, ph, ego_lat, ego_lon, ego_heading)
        # peer 가 같은 교차로 ~ 100m 안쪽인지 확인
        if abs(rel["forward_m"]) > forward_m + 30 or abs(rel["lateral_m"]) > lateral_m + 30:
            continue
        is_oncoming = _bearing_diff_deg(ph, ego_heading) > 130   # 130~180°
        weight_boost = 0.95 if is_oncoming else 0.75

        if is_oncoming:
            res.oncoming_used += 1
        res.peers_used += 1

        # peer 의 detection 을 ego BEV 좌표로 투영 (peer 가 자기 좌표계로 보낸 rel_lat/rel_lon 활용)
        for d in peer.get("detections", []):
            d_lat = plat + float(d.get("rel_lat", 0))
            d_lon = plon + float(d.get("rel_lon", 0))
            ego_bev = _to_ego_bev(d_lat, d_lon, ph, ego_lat, ego_lon, ego_heading)
            f = ego_bev["forward_m"]
            l = ego_bev["lateral_m"]
            if f < 0 or f >= forward_m: continue
            if abs(l) >= lateral_m: continue
            r = int(f / cell_m)
            c = int((l + lateral_m) / cell_m)
            if not (0 <= r < rows and 0 <= c < cols): continue

            cls = d.get("class", "unknown")
            base_conf = float(d.get("conf", 0.5))
            mass = base_conf * weight_boost
            sigma = 2.0 if cls == "person" else 2.5

            # 가우시안 splat
            rad = int(np.ceil(sigma * 3))
            r0, r1 = max(0, r - rad), min(rows, r + rad + 1)
            c0, c1 = max(0, c - rad), min(cols, c + rad + 1)
            yy, xx = np.ogrid[r0:r1, c0:c1]
            patch = mass * np.exp(-((yy - r) ** 2 + (xx - c) ** 2) / (2 * sigma * sigma))
            before = local_grid[r0:r1, c0:c1].copy()
            local_grid[r0:r1, c0:c1] = np.clip(local_grid[r0:r1, c0:c1] + patch, 0.0, 1.0)
            res.boosted_cells += int(((local_grid[r0:r1, c0:c1] - before) > 0.05).sum())
            res.added_mass += float((local_grid[r0:r1, c0:c1] - before).sum())

    res.note = f"{res.oncoming_used} oncoming · {res.peers_used - res.oncoming_used} same-direction"
    return res
