"""
9종 공공데이터 융합 조회 엔드포인트.

  GET /fusion/intersection/{intersection_id}  ─ 교차로 1개에 대한 9종(신호·VDS·돌발·TAAS·ITS·DSZ·기상·응급실·따릉이) 종합
  GET /fusion/sources                         ─ 연동 중인 소스 목록(대시보드용)
  GET /fusion/weather                         ─ 기상청 동네예보 + 도로 위험 가중치
  GET /fusion/medical                         ─ 응급실 실시간 가용병상 + 사고 심각도 보정
  GET /fusion/bike                            ─ 공공자전거 실시간 거치 + 자전거도로 prior

기능: 9종 공공데이터를 한 응답에 결합 반환. (2026-05-15 6→9종 확장)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from ..services import public_api

router = APIRouter()


@router.get("/sources")
def list_sources():
    """공공 데이터 소스 목록 + 최근 호출 시각/age (데이터 freshness 증명). 2026-05-15 9종 확장."""
    from datetime import datetime
    fresh = public_api.get_freshness() if hasattr(public_api, "get_freshness") else {}
    now_ts = datetime.utcnow()

    def _age(iso: str) -> Optional[float]:
        if not iso:
            return None
        try:
            t = datetime.fromisoformat(iso.replace("Z", ""))
            return round((now_ts - t).total_seconds(), 1)
        except Exception:
            return None

    sources = [
        {"id": "signal",    "name": "교통안전 실시간 신호정보",       "origin": "apis.data.go.kr",    "gain": "교차로 신호 위상", "added": "v1"},
        {"id": "vds",       "name": "한국도로공사 VDS 실시간 소통",   "origin": "data.ex.co.kr",      "gain": "속도·교통량·점유율", "added": "v1"},
        {"id": "incidents", "name": "한국도로공사 돌발상황",          "origin": "data.ex.co.kr",      "gain": "사고·낙하물·공사", "added": "v1"},
        {"id": "taas",      "name": "TAAS 교통사고분석",              "origin": "taas.koroad.or.kr",  "gain": "과거 사고이력 prior", "added": "v1"},
        {"id": "its",       "name": "ITS 국가교통정보센터",            "origin": "openapi.its.go.kr",  "gain": "표준링크 속도·소요", "added": "v1"},
        {"id": "dsz",       "name": "국토교통 데이터안심구역 결합결과","origin": "dsz.ex.co.kr",       "gain": "TAAS×VDS k-익명 결합", "added": "v1"},
        {"id": "weather",   "name": "기상청 동네예보 (KMA)",          "origin": "apis.data.go.kr/1360000", "gain": "강수·시정·노면위험", "added": "v2-2026.05.15"},
        {"id": "medical",   "name": "E-Gen 응급실 실시간 가용병상",   "origin": "apis.data.go.kr/B552657", "gain": "사고 심각도 보정·환자이송", "added": "v2-2026.05.15"},
        {"id": "bike",      "name": "서울시 공공자전거 따릉이 실시간","origin": "openapi.seoul.go.kr", "gain": "자전거도로 prior +0.22", "added": "v2-2026.05.15"},
        # v3 2026-05-16: 9 → 12종 확장
        {"id": "school_zone",        "name": "어린이보호구역 GIS",           "origin": "api.vworld.kr (lt_c_spzzone)", "gain": "스쿨존 위험 ×1.5 (등하교)", "added": "v3-2026.05.16"},
        {"id": "black_ice",          "name": "도로결빙 위험구간 (KMA 파생)", "origin": "T1H+PTY+RN1 결합",              "gain": "블랙아이스 +0.32", "added": "v3-2026.05.16"},
        {"id": "pedestrian_hotspot", "name": "보행자 사고다발지역",          "origin": "taas.koroad.or.kr (ped)",       "gain": "보행자 prior +0.30", "added": "v3-2026.05.16"},
    ]
    for s in sources:
        meta = fresh.get(s["id"]) or {}
        s["last_fetched_at"] = meta.get("ts")
        s["age_s"] = _age(meta.get("ts"))
        s["mode"] = meta.get("mode", "stub")   # live | stub | cached
        s["last_success"] = meta.get("ok")
    return {
        "sources": sources,
        "count": len(sources),
        "schema_version": "fusion.v3-12src-2026.05.16",
        "checked_at": now_ts.isoformat() + "Z",
    }


@router.get("/weather")
def fusion_weather(nx: int = Query(60, description="기상청 격자 X (서울=60)"),
                   ny: int = Query(127, description="기상청 격자 Y (서울=127)")):
    """기상청 동네예보 + 도로 위험 가중치 (강수·시정·노면)."""
    return public_api.fetch_weather(nx=nx, ny=ny)


@router.get("/medical")
def fusion_medical(lat: float = Query(37.5665), lon: float = Query(126.9780),
                   radius_km: float = Query(5.0, ge=0.5, le=30.0)):
    """반경 N km 응급실 실시간 가용병상 + 사고 심각도 보정 계수 (NEDIS)."""
    return public_api.fetch_emergency_capacity(lat=lat, lon=lon, radius_km=radius_km)


@router.get("/bike")
def fusion_bike(num_of_rows: int = Query(50, ge=1, le=1000)):
    """서울시 공공자전거 따릉이 실시간 거치 → 자전거도로 시나리오 prior."""
    return public_api.fetch_bike_stations(num_of_rows=num_of_rows)


# v3 2026-05-16: 신규 3 엔드포인트
@router.get("/school-zone")
def fusion_school_zone(lat: float = Query(37.5081), lon: float = Query(127.0440),
                        radius_m: float = Query(500.0, ge=50.0, le=5000.0)):
    """어린이보호구역 GIS — 반경 N m 폴리곤 + 등하교 시간대 위험 multiplier."""
    return public_api.fetch_school_zone(lat=lat, lon=lon, radius_m=radius_m)


@router.get("/black-ice")
def fusion_black_ice(lat: float = Query(37.5665), lon: float = Query(126.9780)):
    """도로결빙 위험 — KMA T1H/PTY/RN1 결합으로 자동 추론."""
    return public_api.fetch_black_ice_risk(lat=lat, lon=lon)


@router.get("/pedestrian-hotspots")
def fusion_pedestrian_hotspots(lat: float = Query(37.5665), lon: float = Query(126.9780),
                                radius_m: float = Query(500.0, ge=50.0, le=5000.0)):
    """반경 N m 보행자 사고다발지역 (TAAS 보행자 특화)."""
    return public_api.fetch_pedestrian_hotspots(lat=lat, lon=lon, radius_m=radius_m)


@router.get("/intersection/{intersection_id}")
def fusion_intersection(
    intersection_id: str,
    link_id: Optional[str] = Query(None),
    bbox_min_lat: Optional[float] = Query(None),
    bbox_max_lat: Optional[float] = Query(None),
    bbox_min_lon: Optional[float] = Query(None),
    bbox_max_lon: Optional[float] = Query(None),
):
    bbox = None
    if None not in (bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon):
        bbox = {
            "minLat": bbox_min_lat, "maxLat": bbox_max_lat,
            "minLon": bbox_min_lon, "maxLon": bbox_max_lon,
        }
    fusion = public_api.fetch_fusion(intersection_id, link_id=link_id, bbox=bbox)
    return fusion.to_dict()
