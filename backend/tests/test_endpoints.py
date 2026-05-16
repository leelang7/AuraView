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


def test_fusion_sources_lists_nine():
    """2026-05-15: 6종 → 9종 확장 (KMA 기상·NEDIS 응급실·따릉이 추가)."""
    r = client.get("/fusion/sources")
    assert r.status_code == 200
    body = r.json()
    assert body.get("count") == 9
    ids = {s["id"] for s in body["sources"]}
    assert {"signal", "vds", "incidents", "taas", "its", "dsz",
            "weather", "medical", "bike"} <= ids
    assert body.get("schema_version", "").startswith("fusion.v2-9src")


def test_fusion_intersection_returns_six_keys():
    r = client.get("/fusion/intersection/1007")
    assert r.status_code == 200
    body = r.json()
    sources = body.get("sources", {})
    for key in ["signal", "vds", "incidents", "accidents_history", "its_link"]:
        assert key in sources, f"missing fusion source: {key}"


def test_fusion_intersection_returns_nine_sources_v2():
    """2026-05-15 v2: 9종 (기상·응급실·자전거 추가) + fusion_summary.sources_fused == 9."""
    r = client.get("/fusion/intersection/1007")
    assert r.status_code == 200
    body = r.json()
    sources = body.get("sources", {})
    for key in ["signal", "vds", "incidents", "accidents_history", "its_link",
                "dsz_analysis", "weather", "medical", "bike"]:
        assert key in sources, f"missing fusion source: {key}"
    summary = body.get("fusion_summary", {})
    assert summary.get("sources_fused") == 9
    assert summary.get("schema_version", "").startswith("fusion.v2-9src")
    # 9종 융합으로 추가된 신호 필드들
    for k in ["weather_raining", "wet_road_risk_boost", "nearest_ER_load",
              "severity_multiplier", "bike_lane_risk_boost"]:
        assert k in summary, f"missing fusion_summary field: {k}"


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
