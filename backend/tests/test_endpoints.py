"""
AuraView 핵심 엔드포인트 통합 테스트.

이 테스트는 외부 API · 모델 가중치 · 디스크 쓰기 없이 실행 가능하도록 작성됨.
다만 cv2 / numpy / Pillow 등 의존성은 필요. CI 워크플로 ci.yml 의 minimal deps 환경에서는
cv2 가 없을 수 있어 scenario / showreel 라우터는 skip 처리.
"""

from __future__ import annotations

import os

os.environ.setdefault("ALLOW_FALLBACK", "1")
os.environ.setdefault("SERVICE_KEY", "test-stub")
os.environ.setdefault("PUBLIC_API_TIMEOUT", "0.3")  # 테스트 환경에서 외부 API 빠르게 fallback

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_alive():
    r = client.get("/")
    assert r.status_code == 200
    assert "AuraView" in r.text or "message" in r.text


def test_fusion_sources_lists_twentythree():
    """2026-05-25 v10: 23종 → 24종 확장 (USGS 지진 추가).
    이전 23종 모두 포함 + earthquake 신규. 카운트 ≥ 23 (확장 호환)."""
    r = client.get("/fusion/sources")
    assert r.status_code == 200
    body = r.json()
    assert body.get("count") >= 23
    ids = {s["id"] for s in body["sources"]}
    assert {"signal", "vds", "incidents", "taas", "its", "dsz",
            "weather", "medical", "bike",
            "school_zone", "black_ice", "pedestrian_hotspot",
            "air_quality", "school_route", "ev_charger",
            "road_surface", "vehicle_inspection",
            "dtg", "nfa_dispatch",
            "road_age", "av_hub",
            "police_cam", "crosswalk"} <= ids
    # v10 신규: earthquake (count ≥ 24 가 됨)
    if body.get("count") >= 24:
        assert "earthquake" in ids
    assert body.get("schema_version", "").startswith("fusion.v")


def test_fusion_intersection_returns_six_keys():
    r = client.get("/fusion/intersection/1007")
    assert r.status_code == 200
    body = r.json()
    sources = body.get("sources", {})
    for key in ["signal", "vds", "incidents", "accidents_history", "its_link"]:
        assert key in sources, f"missing fusion source: {key}"


def test_fusion_intersection_returns_twentythree_sources_v9():
    """2026-05-21 v9: 23종 (경찰청 단속CCTV + 횡단보도 GIS 추가) + sources_fused == 23."""
    r = client.get("/fusion/intersection/1007")
    assert r.status_code == 200
    body = r.json()
    sources = body.get("sources", {})
    for key in ["signal", "vds", "incidents", "accidents_history", "its_link",
                "dsz_analysis", "weather", "medical", "bike",
                "school_zone", "black_ice", "pedestrian_hotspot",
                "air_quality", "school_route", "ev_charger",
                "road_surface", "vehicle_inspection",
                "dtg", "nfa_dispatch",
                "road_age", "av_hub",
                "police_cam", "crosswalk"]:
        assert key in sources, f"missing fusion source: {key}"
    summary = body.get("fusion_summary", {})
    assert summary.get("sources_fused") == 23
    assert summary.get("schema_version", "").startswith("fusion.v9-23src")
    for k in ["weather_raining", "wet_road_risk_boost", "nearest_ER_load",
              "severity_multiplier", "bike_lane_risk_boost",
              "in_school_zone", "school_zone_multiplier",
              "black_ice_risk", "freeze_risk_boost",
              "in_pedestrian_hotspot", "ped_hotspot_boost",
              "pm10_avg", "air_quality_risk_boost",
              "on_school_route", "walk_route_boost",
              "near_ev_station", "ev_dwelling_likelihood",
              # v8/v9 신규
              "enforcement_cam_count", "enforcement_risk_boost", "is_enforcement_hotzone",
              "crosswalk_count_within_radius", "approaching_crosswalk",
              "crosswalk_pedestrian_boost", "school_zone_crosswalk_count"]:
        assert k in summary, f"missing fusion_summary field: {k}"


def test_location_accuracy_rural_gps_no_false_alarms():
    """v12.20+: 임의 GPS (집/원거리) 에서 거짓 알람 없어야 한다."""
    r = client.get("/fusion/intersection/gps-38200-128500")
    assert r.status_code == 200
    body = r.json()
    summary = body.get("fusion_summary", {})
    # 위치 인식 stub: 신호 unknown, TAAS 0, ER 0, 단속/횡단 모두 0
    sig = body.get("sources", {}).get("signal", {}).get("data", {}).get("body", {}).get("items", {}).get("item", {}).get("stPdsgSttsNm")
    assert sig == "unknown", f"임의 GPS 에서 신호 stub 가 'unknown' 이 아닌 거짓 값 반환: {sig}"
    assert summary.get("taas_accidents_nearby") == 0, "임의 GPS 에서 TAAS 가짜 사고"
    assert summary.get("nearest_ER_load") == 0.0, "임의 GPS 에서 ER 가짜 포화도"
    assert summary.get("enforcement_cam_count") == 0
    assert summary.get("crosswalk_count_within_radius") == 0
    # 위험 점수도 매우 낮아야 (LOW)
    assert summary.get("risk_level") == "LOW"
    assert summary.get("fusion_risk_score", 1.0) < 0.10


def test_fleet_verify_location_accuracy_component():
    """v12.20: /fleet/verify 에 location_accuracy 컴포넌트 신설."""
    r = client.get("/fleet/verify")
    assert r.status_code == 200
    body = r.json()
    comps = body.get("components", {})
    assert "location_accuracy" in comps, "verify 응답에 location_accuracy 누락"
    loc = comps["location_accuracy"]
    assert loc.get("ok") is True, f"location_accuracy ok=False: {loc.get('note')}"
    assert loc.get("home_like_signal") == "unknown"
    assert loc.get("home_like_taas_nearby") == 0
    assert loc.get("home_like_er_load") == 0.0


def test_fetch_police_cams_location_filtering():
    """v12.21: fetch_police_cams 는 반경 800m 내 단속카메라만 반환 + boost 계산."""
    from app.services.public_api import fetch_police_cams
    # 한양대역 (1007) 근처 — 1대 매칭 예상
    near = fetch_police_cams(lat=37.5547, lon=127.1295, radius_m=800.0)
    d_near = near.get("derived", {})
    assert d_near.get("cam_count_within_radius") >= 1, "한양대 근처 단속카메라 미감지"
    assert d_near.get("enforcement_risk_boost") > 0, "boost 미산정"
    # 강원 임의 GPS — 0대
    rural = fetch_police_cams(lat=38.2, lon=128.5, radius_m=800.0)
    d_rural = rural.get("derived", {})
    assert d_rural.get("cam_count_within_radius") == 0, "원거리에서 잘못된 단속카메라 반환"
    assert d_rural.get("enforcement_risk_boost") == 0.0
    assert d_rural.get("is_enforcement_hotzone") is False


def test_fetch_crosswalk_gis_approach_alert():
    """v12.23: fetch_crosswalk_gis approaching_crosswalk 50m 임계 동작 검증."""
    from app.services.public_api import fetch_crosswalk_gis
    # 한양대역 횡단보도 정중앙 — 50m 내 (approaching=True)
    on_cw = fetch_crosswalk_gis(lat=37.5547, lon=127.1295, radius_m=300.0)
    d_on = on_cw.get("derived", {})
    assert d_on.get("approaching_crosswalk") is True, "횡단보도 50m 임박 미감지"
    assert d_on.get("crosswalk_count_within_radius") >= 1
    # 강원 임의 GPS — 0건
    rural = fetch_crosswalk_gis(lat=38.2, lon=128.5, radius_m=300.0)
    d_rural = rural.get("derived", {})
    assert d_rural.get("crosswalk_count_within_radius") == 0
    assert d_rural.get("approaching_crosswalk") is False
    assert d_rural.get("crosswalk_pedestrian_boost") == 0.0


def test_fetch_emergency_capacity_rural_gps_no_hospital():
    """v12.20: fetch_emergency_capacity 임의 원거리 GPS → 반경 5km 내 병원 없음 → er_load=0."""
    from app.services.public_api import fetch_emergency_capacity
    # 강원 임의 GPS (서울 병원 fixture 와 무관)
    r = fetch_emergency_capacity(lat=38.2, lon=128.5, radius_km=5.0)
    d = r.get("derived", {})
    assert d.get("nearest_ER_load") == 0.0
    assert d.get("severity_multiplier") == 1.0
    assert d.get("nearest_eta_min") == 0
    assert r.get("filter_applied") == "lat/lon"


def test_fusion_intersection_bbox_taas_filtering():
    """v12.20: bbox 파라미터로 TAAS 사고를 위치 인식 필터 — 강원 bbox → 0건."""
    r = client.get("/fusion/intersection/test-strange",
                   params={
                       "bbox_min_lat": 38.0, "bbox_max_lat": 38.5,
                       "bbox_min_lon": 128.0, "bbox_max_lon": 128.7,
                   })
    assert r.status_code == 200
    body = r.json()
    summary = body.get("fusion_summary", {})
    # 강원 bbox 안에 서울 사고 fixture 가 없으므로 0
    assert summary.get("taas_accidents_nearby") == 0
    assert summary.get("nearest_ER_load") == 0.0


def test_policy_stats_hotspots_iid_drill_down():
    """v12.56: /policy/stats top_hotspots 8개에 iid 매핑 — risk-breakdown drill 가능."""
    r = client.get("/policy/stats")
    assert r.status_code == 200
    body = r.json()
    hotspots = body.get("top_hotspots", [])
    iid_count = sum(1 for h in hotspots if h.get("iid"))
    assert iid_count >= 8, f"top hotspots 의 iid 매핑 부족: {iid_count}"
    known_iids = {"1007", "2024", "3015", "4011", "5006", "6022", "7045", "8033"}
    mapped = {h["iid"] for h in hotspots if "iid" in h}
    assert known_iids <= mapped, f"known intersection 누락: {known_iids - mapped}"


def test_fusion_risk_breakdown_decomposition():
    """v12.49: /fusion/risk-breakdown/{iid} 23 소스 contribution 분해."""
    r = client.get("/fusion/risk-breakdown/1007")
    assert r.status_code == 200
    body = r.json()
    assert body.get("intersection_id") == "1007"
    assert body.get("schema_version", "").startswith("fusion.v9-23src")
    assert "final_risk_score" in body
    assert "raw_weighted_sum" in body
    items = body.get("components_sorted_by_contribution", [])
    # v8/v9 23 소스 중 risk_score 계산에 포함되는 19종 (DSZ/ITS/신호는 별개)
    assert len(items) >= 18, f"breakdown components too few: {len(items)}"
    # 모든 항목 contribution == value × weight
    for c in items:
        expected = round((c["value"] or 0) * (c["weight"] or 0), 4)
        assert abs(c["contribution"] - expected) < 1e-6, f"contribution mismatch for {c['id']}"
    # 정렬 — contribution 내림차순
    for i in range(len(items) - 1):
        assert items[i]["contribution"] >= items[i+1]["contribution"]
    # 한양대 1007 (서울 알려진 교차로) — final risk > 0
    assert (body["final_risk_score"] or 0) > 0


def test_fusion_risk_breakdown_rural_gps_zero():
    """v12.49: 임의 원거리 GPS 에서 risk-breakdown 의 raw_weighted_sum 매우 낮음."""
    r = client.get("/fusion/risk-breakdown/gps-38200-128500")
    assert r.status_code == 200
    body = r.json()
    assert body.get("final_risk_score", 1.0) < 0.10
    assert body.get("risk_level") == "LOW"


def test_fleet_demo_tour_single_url_validation():
    """v12.36: /fleet/demo-tour 단일 URL 로 8 known + 2 rural GPS 동시 검증."""
    r = client.get("/fleet/demo-tour")
    assert r.status_code == 200
    body = r.json()
    s = body.get("summary", {})
    assert s.get("known_intersection_count") == 8
    assert s.get("rural_gps_count") == 2
    assert s.get("schema_consistent") is True, "schema 가 위치별 다름"
    assert s.get("rural_no_false_alarms") is True, "rural GPS 에서 거짓 알람 발생"
    assert s.get("known_intersections_active") is True, "known 교차로 비활성"
    assert s.get("overall_ok") is True
    # known/rural 데이터 구조 검증
    for k in body["known_intersections"]:
        if "error" in k:
            continue
        assert k["sources_fused"] == 23
        assert k["signal_state"] != "unknown"
    for r2 in body["rural_gps_locations"]:
        if "error" in r2:
            continue
        assert r2["signal_state"] == "unknown"
        assert r2["taas_accidents_nearby"] == 0
        assert r2["nearest_ER_load"] == 0.0
        assert r2["risk_level"] == "LOW"


def test_fusion_air_quality_endpoint():
    r = client.get("/fusion/air-quality", params={"sido": "서울"})
    assert r.status_code == 200
    j = r.json()
    if "derived" in j:
        assert "air_quality_risk_boost" in j["derived"]


def test_fusion_school_route_endpoint():
    r = client.get("/fusion/school-route", params={"lat": 37.5081, "lon": 127.0440})
    assert r.status_code == 200
    j = r.json()
    assert "derived" in j
    assert "walk_route_boost" in j["derived"]


def test_fusion_ev_charger_endpoint():
    r = client.get("/fusion/ev-charger", params={"lat": 37.5665, "lon": 126.9780})
    assert r.status_code == 200
    j = r.json()
    assert "derived" in j
    assert "ev_dwelling_likelihood" in j["derived"]


def test_fusion_road_surface_endpoint():
    """v5 2026-05-18: RWIS 도로 노면 상태."""
    r = client.get("/fusion/road-surface", params={"lat": 37.5665, "lon": 126.9780, "radius_m": 5000})
    assert r.status_code == 200
    j = r.json()
    assert "derived" in j
    assert "surface_risk_boost" in j["derived"]
    assert j["derived"]["nearest_surface"] in ("dry", "wet", "snow", "frost", "ice")


def test_fusion_vehicle_inspection_endpoint():
    """v5 2026-05-18: KOTSA 시군구별 자동차검사 부적합률."""
    r = client.get("/fusion/vehicle-inspection", params={"district": "강남구"})
    assert r.status_code == 200
    j = r.json()
    assert "derived" in j
    assert "fail_rate_district" in j["derived"]
    assert "inspection_risk_boost" in j["derived"]


def test_fusion_school_zone_endpoint():
    r = client.get("/fusion/school-zone", params={"lat": 37.5081, "lon": 127.0440, "radius_m": 1000})
    assert r.status_code == 200
    j = r.json()
    assert "derived" in j
    assert "school_zone_multiplier" in j["derived"]
    assert j["derived"]["school_zone_multiplier"] in (1.0, 1.2, 1.5)


def test_fusion_black_ice_derives_from_weather():
    r = client.get("/fusion/black-ice", params={"lat": 37.5665, "lon": 126.9780})
    assert r.status_code == 200
    j = r.json()
    assert "derived" in j
    assert "black_ice_severity" in j["derived"]
    assert j["derived"]["black_ice_severity"] in ("none", "low", "medium", "high")
    assert "freeze_risk_boost" in j["derived"]


def test_fusion_pedestrian_hotspots_endpoint():
    r = client.get("/fusion/pedestrian-hotspots", params={"lat": 37.5720, "lon": 126.9769, "radius_m": 2000})
    assert r.status_code == 200
    j = r.json()
    if "hotspots" in j:
        assert isinstance(j["hotspots"], list)
        assert "derived" in j
        assert "ped_hotspot_boost" in j["derived"]


def test_fusion_weather_endpoint():
    r = client.get("/fusion/weather", params={"nx": 60, "ny": 127})
    assert r.status_code == 200
    j = r.json()
    derived = j.get("derived", {}) or j.get("body", {}).get("derived", {})
    if derived:
        # stub mode 일 때는 derived 키가 있어야 함
        assert "wet_road_risk_boost" in derived or "is_raining" in derived


def test_fusion_medical_endpoint():
    r = client.get("/fusion/medical", params={"lat": 37.5665, "lon": 126.9780})
    assert r.status_code == 200
    j = r.json()
    if "hospitals" in j:  # stub mode
        assert isinstance(j["hospitals"], list)
        assert len(j["hospitals"]) >= 1
        assert "derived" in j
        assert "severity_multiplier" in j["derived"]


def test_fusion_bike_endpoint():
    r = client.get("/fusion/bike", params={"num_of_rows": 10})
    assert r.status_code == 200
    j = r.json()
    if "stations" in j:  # stub mode
        assert isinstance(j["stations"], list)
        assert len(j["stations"]) >= 1
        assert "derived" in j


def test_ai_v2_metric_endpoint():
    """v2 metric 엔드포인트 — 학습 됐으면 available=True, 미학습 시 명시적 안내."""
    r = client.get("/ai/v2-metric")
    assert r.status_code == 200
    j = r.json()
    assert "available" in j
    if j["available"]:
        assert "metrics" in j
        assert "auc" in j["metrics"]
        assert j.get("schema_version", "").startswith("fusion.v2-9src")
    else:
        assert "training_script" in j
        assert "notebooks/train_risk_transformer_v2_9src.py" in j["training_script"]


def test_ai_v1_vs_v2_comparison():
    """v1 vs v2 비교 — 두 metric 다 있으면 delta_pct 계산, v2 미학습이면 안내."""
    r = client.get("/ai/v1-vs-v2")
    assert r.status_code == 200
    j = r.json()
    assert "available" in j
    if j["available"]:
        assert "v1" in j and "v2" in j and "table" in j
        assert j["v1"]["features"] == 10
        assert j["v2"]["features"] == 13


def test_ai_collab_bus_live_endpoint():
    """BIS 실시간 버스 엔드포인트 (Cycle 4 신규)."""
    r = client.get("/collab/bus-live", params={"lat": 37.5651, "lon": 127.0073, "radius_m": 200})
    assert r.status_code == 200
    j = r.json()
    assert j["mode"] in ("live", "stub", "error")
    assert "buses" in j and isinstance(j["buses"], list)
    assert j["count"] == len(j["buses"])


def test_fleet_stats_shape():
    r = client.get("/fleet/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body and "hard_count" in body and "recent" in body


def test_kmaas_alternatives():
    r = client.get(
        "/kmaas/alternatives",
        params={
            "origin_lat": 37.56, "origin_lon": 127.04,
            "dest_lat": 37.57, "dest_lon": 126.98,
            "risk": 11.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "alternatives" in body
    assert len(body["alternatives"]) >= 1


def test_kmaas_operator_report_shape():
    r = client.get("/kmaas/operator-report")
    assert r.status_code == 200
    body = r.json()
    assert "transit_operator_summary" in body
    assert "rider_summary" in body


def test_dsz_artifacts_endpoint():
    r = client.get("/dsz/artifacts")
    assert r.status_code == 200
    assert "artifacts" in r.json()


def test_dsz_join_demo_returns_anon_rows():
    r = client.post("/dsz/join/taas-vds")
    assert r.status_code == 200
    body = r.json()
    assert "joined_count" in body
    # 결합 행 자체는 fallback 데이터에 따라 0 일 수도 있지만 응답 형식 보장


def test_heatmap_taas_fallback_points():
    r = client.get("/heatmap/taas")
    assert r.status_code == 200
    body = r.json()
    assert "points" in body and len(body["points"]) > 0
    # 각 point 는 [lat, lon, weight]
    for p in body["points"][:5]:
        assert len(p) == 3


def test_reports_generate_with_seed_data():
    r = client.post("/reports/generate", params={"top": 5})
    assert r.status_code == 200
    body = r.json()
    assert "html_url" in body and "json_url" in body
    assert body["entries"] >= 1


def test_occupancy_demo_grid_present():
    """occupancy.demo 는 numpy/PIL 의존. 없을 때 skip."""
    pytest.importorskip("numpy")
    r = client.get("/occupancy/demo")
    assert r.status_code == 200
    body = r.json()
    assert "shape" in body and body["shape"] == [80, 80]


def test_signals_endpoint_returns_dict():
    r = client.get("/signals/1007")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_intersections_list_endpoint():
    # DB 에 데이터가 없을 수도 있지만 200 응답 + 리스트 형태 보장
    r = client.get("/intersections/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ─────────────────────────────────────────────────────────────────
# Collaborative Perception (V2V + Bus + Bidirectional)
# ─────────────────────────────────────────────────────────────────

def test_v2v_seed_and_fetch():
    seed = client.post(
        "/collab/v2v/seed-demo",
        params={"intersection_id": "test-1", "lat": 37.56, "lon": 127.04},
    )
    assert seed.status_code == 200
    body = seed.json()
    assert body["seeded"] >= 3
    listing = client.get("/collab/v2v/intersection/test-1")
    assert listing.status_code == 200
    msgs = listing.json()["messages"]
    assert len(msgs) >= 3


def test_v2v_stats():
    r = client.get("/collab/v2v/stats")
    assert r.status_code == 200
    body = r.json()
    assert "intersections_active" in body and "total_messages" in body


def test_bus_context_endpoint():
    r = client.post(
        "/collab/bus-context",
        json={
            "bus_detections": [
                {"class_name": "bus", "confidence": 0.83, "bbox_xyxy": [100, 100, 600, 400]}
            ],
            "ego_lat": 37.5651, "ego_lon": 127.0073,
            "ego_speed_kmh": 3.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["bus_visible"] is True
    assert body["pedestrian_prior_boost"] > 0


def test_bus_context_no_bus():
    r = client.post(
        "/collab/bus-context",
        json={"bus_detections": [], "ego_lat": 37.5, "ego_lon": 127.0, "ego_speed_kmh": 50},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["bus_visible"] is False
    assert body["pedestrian_prior_boost"] == 0.0


def test_bidirectional_after_seed():
    client.post("/collab/v2v/seed-demo", params={"intersection_id": "bidir-test"})
    r = client.post(
        "/collab/bidirectional",
        json={"intersection_id": "bidir-test", "ego_heading_deg": 270},
    )
    assert r.status_code == 200
    body = r.json()
    # 시드 차 3대 중 2대 마주오는 + 감속 → hazard 가 어느 정도 잡혀야
    assert body["oncoming_count"] >= 1
    assert "hazard_probability" in body


# ── /impact + /positioning + freshness 회귀 보호 ─────────────────────

def test_impact_default_returns_headline():
    r = client.get("/impact")
    assert r.status_code == 200
    body = r.json()
    assert "preventability" in body
    assert 0.0 <= body["preventability"] <= 0.85
    assert "projected_prevented" in body
    assert "headline" in body["projected_prevented"]
    assert "annual_baseline" in body
    assert body["annual_baseline"]["accidents_total"] > 0
    assert "methodology" in body
    assert len(body["methodology"]["sources"]) >= 2


def test_impact_scenarios_three_levels():
    r = client.get("/impact/scenarios")
    assert r.status_code == 200
    body = r.json()
    assert len(body["scenarios"]) == 3
    coverages = [s["coverage"] for s in body["scenarios"]]
    assert coverages == sorted(coverages)
    # 모든 시나리오에 예방 사고 수 양수
    for s in body["scenarios"]:
        assert s["prevented_accidents"] >= 0
        assert s["prevented_deaths"] >= 0


def test_impact_lead_time_param_changes_preventability():
    r1 = client.get("/impact", params={"lead": 1.0, "coverage": 0.10}).json()
    r2 = client.get("/impact", params={"lead": 3.5, "coverage": 0.10}).json()
    assert r2["preventability"] > r1["preventability"]
    assert r2["projected_prevented"]["prevented_accidents"] > r1["projected_prevented"]["prevented_accidents"]


def test_positioning_tesla_comparison():
    r = client.get("/positioning/tesla-vs-auraview")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) >= 5   # 7 rows (5 original + 2 competition v0.6)
    for row in body["rows"]:
        for k in ("category", "tesla", "auraview", "korea_specific", "endpoint"):
            assert k in row, f"row missing {k}"
    assert "metric_summary" in body
    assert body["metric_summary"]["trained_auc"] > 0.9


def test_fusion_sources_freshness_metadata():
    # 한 번 호출해서 freshness 강제 갱신
    client.get("/fusion/intersection/10")
    r = client.get("/fusion/sources")
    assert r.status_code == 200
    body = r.json()
    for s in body["sources"]:
        # 호출 후 mode/age_s 가 반영되거나 (signal/vds/incidents/taas/its 5개 중 일부)
        # dsz 는 별도라 None 일 수 있음
        if s["id"] in {"signal", "vds", "incidents", "taas", "its"}:
            assert s.get("mode") in {"live", "stub", "error"}, f"{s['id']} no mode"


def test_summary_includes_impact():
    r = client.get("/summary.json")
    assert r.status_code == 200
    body = r.json()
    assert "impact" in body
    assert "headline" in body["impact"]
    assert "scenarios" in body["impact"]
    assert len(body["impact"]["scenarios"]) == 3


def test_impact_top_intersections_default():
    r = client.get("/impact/top-intersections")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 10
    assert body["total_prevented_kis_yearly"] > 0
    for i, item in enumerate(body["intersections"]):
        assert item["rank"] == i + 1
        for k in ("name", "district", "lat", "lon", "category", "annual_kis_baseline"):
            assert k in item, f"missing {k}"
        assert item["preventability"] > 0


def test_impact_top_intersections_lead_param_changes_prevention():
    r1 = client.get("/impact/top-intersections", params={"lead": 1.0}).json()
    r2 = client.get("/impact/top-intersections", params={"lead": 3.5}).json()
    assert r2["total_prevented_kis_yearly"] > r1["total_prevented_kis_yearly"]


def test_impact_top_intersections_national_scope():
    r = client.get("/impact/top-intersections", params={"scope": "national", "top_n": 22})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "national"
    assert body["count"] == 22  # 서울 12 + 5대 광역 10
    cities = {item["city"] for item in body["intersections"]}
    assert "서울" in cities
    assert {"부산", "대구", "인천", "대전", "광주"} & cities


def test_impact_top_intersections_seoul_default():
    r = client.get("/impact/top-intersections")
    body = r.json()
    assert body["scope"] == "seoul"
    for item in body["intersections"]:
        assert item.get("city") == "서울"
