"""
V2V / Bus / Bidirectional 서비스 유닛 테스트.

- HTTP 레이어 우회 (서비스 함수 직접 호출)
- 외부 API 의존 없음 (numpy 만 필요)
"""

from __future__ import annotations

import numpy as np

from app.services import bidirectional as bidir_service
from app.services import bus_aware as bus_service
from app.services import v2v as v2v_service


# ─────────────────────────────────────────────────────────────────────
# v2v.py
# ─────────────────────────────────────────────────────────────────────

def test_v2v_publish_then_fetch():
    iid = "ut-1"
    v2v_service._POOL[iid] = []  # 격리
    res = v2v_service.publish({
        "device_id": "dev-A",
        "intersection_id": iid,
        "lat": 37.56, "lon": 127.04, "heading_deg": 90, "speed_kmh": 24,
        "detections": [],
    })
    assert res["accepted"] is True
    msgs = v2v_service.fetch(iid)
    assert len(msgs) == 1
    assert msgs[0]["heading_deg"] == 90
    # device_id 는 가명화돼서 들어감
    assert msgs[0]["device_id"] != "dev-A"
    assert len(msgs[0]["device_id"]) == 16


def test_v2v_pseudonymize_consistent():
    a = v2v_service.pseudonymize("device-X")
    b = v2v_service.pseudonymize("device-X")
    c = v2v_service.pseudonymize("device-Y")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_v2v_pool_bound():
    """동일 교차로에 32개 초과로 publish 시 오래된 것 자동 정리."""
    iid = "ut-bound"
    v2v_service._POOL[iid] = []
    for i in range(40):
        v2v_service.publish({
            "intersection_id": iid,
            "lat": 37.56, "lon": 127.04, "heading_deg": i * 9,
        })
    msgs = v2v_service.fetch(iid)
    assert len(msgs) <= v2v_service.MAX_PER_INTERSECTION


def test_v2v_merge_into_occupancy_no_peers():
    """peer 없을 때 격자 변경 없음."""
    iid = "ut-empty"
    v2v_service._POOL[iid] = []
    grid = np.zeros((80, 80), dtype=np.float32)
    res = v2v_service.merge_into_occupancy(
        grid, ego_lat=37.56, ego_lon=127.04, ego_heading=270,
        intersection_id=iid, cell_m=0.5, forward_m=40.0, lateral_m=20.0,
    )
    assert res.peers_used == 0
    assert grid.sum() == 0.0


def test_v2v_merge_oncoming_boosts_grid():
    """마주오는 peer 의 detection 이 ego 격자에 가산되는지."""
    iid = "ut-merge"
    v2v_service._POOL[iid] = []
    # ego 는 동→서 방향 (270°), peer 는 서→동 (90°) 마주옴
    v2v_service.publish({
        "intersection_id": iid,
        "lat": 37.5601, "lon": 127.0411, "heading_deg": 90,
        "speed_kmh": 8, "decel_g": 0.3,
        "detections": [{"class": "person", "conf": 0.9,
                         "rel_lat": 0.0, "rel_lon": 0.0, "width_m": 0.6}],
    })
    grid = np.zeros((80, 80), dtype=np.float32)
    res = v2v_service.merge_into_occupancy(
        grid, ego_lat=37.5601, ego_lon=127.0410, ego_heading=270,
        intersection_id=iid, cell_m=0.5, forward_m=40.0, lateral_m=20.0,
    )
    assert res.peers_used >= 1
    # peer 가 마주오는 차이므로 oncoming 카운트 증가
    assert res.oncoming_used >= 1


# ─────────────────────────────────────────────────────────────────────
# bus_aware.py
# ─────────────────────────────────────────────────────────────────────

def test_bus_aware_no_bus():
    ctx = bus_service.analyze(bus_detections=[], ego_lat=37.5, ego_lon=127.0)
    assert ctx.bus_visible is False
    assert ctx.pedestrian_prior_boost == 0.0


def test_bus_aware_dwelling_high_boost():
    """버스 + 정류장 30m 이내 + 자차 정지 → boost 매우 높음."""
    # 동대문역사문화공원 정류장 좌표 사용
    ctx = bus_service.analyze(
        bus_detections=[{"class_name": "bus", "confidence": 0.83}],
        ego_lat=37.5651, ego_lon=127.0073,
        ego_speed_kmh=2.0,
    )
    assert ctx.bus_visible is True
    assert ctx.estimated_state in ("dwelling", "departing", "passing")
    assert ctx.pedestrian_prior_boost > 0.3


def test_bus_aware_no_gps_returns_conservative():
    ctx = bus_service.analyze(
        bus_detections=[{"class_name": "bus", "confidence": 0.8}],
        ego_lat=None, ego_lon=None,
    )
    assert ctx.bus_visible is True
    assert ctx.estimated_state == "unknown_no_gps"
    assert ctx.pedestrian_prior_boost > 0.0
    assert ctx.pedestrian_prior_boost < 0.5


def test_bus_aware_boost_occupancy_modifies_grid():
    grid = np.zeros((80, 80), dtype=np.float32)
    ctx = bus_service.BusContext(pedestrian_prior_boost=0.4)
    cells = bus_service.boost_occupancy(grid, ctx, forward_band=(20, 36), cell_m=0.5)
    assert cells > 0
    assert grid.sum() > 0


# ─────────────────────────────────────────────────────────────────────
# bidirectional.py
# ─────────────────────────────────────────────────────────────────────

def test_bidirectional_oncoming_decel_raises_hazard():
    peers = [
        {"heading_deg": 90, "speed_kmh": 8, "decel_g": 0.4},
        {"heading_deg": 92, "speed_kmh": 5, "decel_g": 0.5},
        {"heading_deg": 88, "speed_kmh": 12, "decel_g": 0.3},
    ]
    res = bidir_service.analyze(peers=peers, ego_heading_deg=270, vds_records=None)
    assert res.oncoming_count == 3
    assert res.oncoming_decel_share >= 0.5
    assert res.hazard_probability >= 0.5
    assert res.recommended_speed_kmh is not None


def test_bidirectional_calm_traffic_low_hazard():
    peers = [
        {"heading_deg": 90, "speed_kmh": 60, "decel_g": 0.0},
        {"heading_deg": 92, "speed_kmh": 58, "decel_g": 0.0},
    ]
    res = bidir_service.analyze(peers=peers, ego_heading_deg=270, vds_records=None)
    assert res.hazard_probability < 0.3


def test_bidirectional_vds_asymmetry_raises_hazard():
    """VDS 상행/하행 속도 차 큼 → 비대칭 → hazard 가산."""
    vds = [
        {"speed": 80, "dir": "up"},
        {"speed": 78, "dir": "up"},
        {"speed": 12, "dir": "down"},
        {"speed": 15, "dir": "down"},
    ]
    res = bidir_service.analyze(peers=[], ego_heading_deg=270, vds_records=vds)
    assert res.speed_asymmetry > 0.4
    assert res.hazard_probability > 0
