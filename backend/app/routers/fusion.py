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

    # v12.135: category 필드 추가 — 출처 정직성 (국내 공공 vs 글로벌 보조)
    #   "국내공공": 한국 정부/공공기관 공식 API (주력 평가 대상)
    #   "보조인프라": 글로벌 오픈데이터 (no-key fallback 용도, 정확도 보강)
    sources = [
        {"id": "signal",    "name": "교통안전 실시간 신호정보",       "origin": "apis.data.go.kr",    "gain": "교차로 신호 위상",       "category": "국내공공", "added": "v1"},
        {"id": "vds",       "name": "한국도로공사 VDS 실시간 소통",   "origin": "data.ex.co.kr",      "gain": "속도·교통량·점유율",     "category": "국내공공", "added": "v1"},
        {"id": "incidents", "name": "한국도로공사 돌발상황",          "origin": "data.ex.co.kr",      "gain": "사고·낙하물·공사",       "category": "국내공공", "added": "v1"},
        {"id": "taas",      "name": "TAAS 교통사고분석",              "origin": "taas.koroad.or.kr",  "gain": "과거 사고이력 prior",   "category": "국내공공", "added": "v1"},
        {"id": "its",       "name": "ITS 국가교통정보센터",            "origin": "openapi.its.go.kr",  "gain": "표준링크 속도·소요",     "category": "국내공공", "added": "v1"},
        {"id": "dsz",       "name": "국토교통 데이터안심구역 결합결과","origin": "dsz.ex.co.kr",       "gain": "TAAS×VDS k-익명 결합",  "category": "국내공공", "added": "v1"},
        {"id": "weather",   "name": "기상청 동네예보 (KMA)",          "origin": "apis.data.go.kr/1360000", "gain": "강수·시정·노면위험",   "category": "국내공공", "added": "v2-2026.05.15"},
        {"id": "medical",   "name": "E-Gen 응급실 실시간 가용병상",   "origin": "apis.data.go.kr/B552657", "gain": "사고 심각도 보정·환자이송", "category": "국내공공", "added": "v2-2026.05.15"},
        {"id": "bike",      "name": "서울시 공공자전거 따릉이 실시간","origin": "openapi.seoul.go.kr", "gain": "자전거도로 prior +0.22", "category": "국내공공", "added": "v2-2026.05.15"},
        # v3 2026-05-16: 9 → 12종 확장
        {"id": "school_zone",        "name": "어린이보호구역 GIS",           "origin": "api.vworld.kr (lt_c_spzzone)", "gain": "스쿨존 위험 ×1.5 (등하교)", "category": "국내공공", "added": "v3-2026.05.16"},
        {"id": "black_ice",          "name": "도로결빙 위험구간 (KMA 파생)", "origin": "T1H+PTY+RN1 결합",              "gain": "블랙아이스 +0.32",        "category": "국내공공", "added": "v3-2026.05.16"},
        {"id": "pedestrian_hotspot", "name": "보행자 사고다발지역",          "origin": "taas.koroad.or.kr (ped)",       "gain": "보행자 prior +0.30",      "category": "국내공공", "added": "v3-2026.05.16"},
        # v4 2026-05-16: 12 → 15종 확장
        {"id": "air_quality",  "name": "환경부 미세먼지 (PM10/PM2.5)", "origin": "apis.data.go.kr/B552584", "gain": "시정·카메라오염 +0.06",   "category": "국내공공", "added": "v4-2026.05.16"},
        {"id": "school_route", "name": "어린이 통학로 GIS",            "origin": "도로교통공단 통학로",     "gain": "통학시간 boost +0.18",   "category": "국내공공", "added": "v4-2026.05.16"},
        {"id": "ev_charger",   "name": "EV 충전소 위치/사용률",        "origin": "apis.data.go.kr/B552584 (Ev)", "gain": "EV 정차 패턴 이상탐지", "category": "국내공공", "added": "v4-2026.05.16"},
        # v5 2026-05-18: 15 → 17종 확장
        {"id": "road_surface",       "name": "도로 노면 상태 (RWIS)",         "origin": "data.ex.co.kr/openapi/rwisapi",          "gain": "노면 위험 (frost +0.35)",         "category": "국내공공", "added": "v5-2026.05.18"},
        {"id": "vehicle_inspection", "name": "KOTSA 자동차검사통계",          "origin": "apis.data.go.kr/B552014/InspectionStats", "gain": "구별 부적합률 → 잠재 위험", "category": "국내공공", "added": "v5-2026.05.18"},
        # v6 2026-05-18: 17 → 19종 확장
        {"id": "dtg",                "name": "KOTSA DTG 디지털운행기록",        "origin": "apis.data.go.kr/B552014/DtgStats",       "gain": "사업용 차량 위험운전 +0.10",   "category": "국내공공", "added": "v6-2026.05.18"},
        {"id": "nfa_dispatch",       "name": "소방청 119 교통사고 출동",        "origin": "apis.data.go.kr/1661000/TfcAcdntDsptch", "gain": "사고 심각도 + 골든타임 라우팅", "category": "국내공공", "added": "v6-2026.05.18"},
        # v7 2026-05-19: 19 → 21종 확장
        {"id": "road_age",           "name": "행정안전부 도로 노후도",           "origin": "apis.data.go.kr/1741000/RoadAgeStats",   "gain": "노후포장+포트홀 인프라 위험 +0.10", "category": "국내공공", "added": "v7-2026.05.19"},
        {"id": "av_hub",             "name": "KOTSA 자율주행 데이터허브 (V2X)",  "origin": "apis.data.go.kr/B552014/AvHub",          "gain": "V2X RSU + HD map → 위험 감산",   "category": "국내공공", "added": "v7-2026.05.19"},
        # v8 2026-05-21: 21 → 22종 확장
        {"id": "police_cam",         "name": "경찰청 교통단속 CCTV 위치",         "origin": "apis.data.go.kr/1320000/CityTrafficCctv","gain": "단속 밀집 = 사고다발 prior +0.04", "category": "국내공공", "added": "v8-2026.05.21"},
        # v9 2026-05-21: 22 → 23종 확장
        {"id": "crosswalk",          "name": "국토부 횡단보도 GIS",                "origin": "api.vworld.kr (lt_l_crwlk)",             "gain": "보행자 prior +0.05 / 50m 접근 ×1.10",       "category": "국내공공", "added": "v9-2026.05.21"},
        # v10 2026-05-25: 23 → 24종 확장 (USGS 지진 — 글로벌 보조 인프라)
        {"id": "earthquake",         "name": "USGS 실시간 지진 (M2.0+)",            "origin": "earthquake.usgs.gov/fdsnws (no-key)",   "gain": "터널/교량 인프라 위험 prior +0.02 / 진앙 50km 내 알림", "category": "보조인프라", "added": "v10-2026.05.25"},
        # v11 2026-05-25: 24 → 25종 확장 (OSM 철도 건널목 — 글로벌 보조 인프라)
        {"id": "railway_crossing",   "name": "OSM 철도 건널목 (level_crossing)",     "origin": "OSM Overpass railway=level_crossing (no-key)", "gain": "건널목 1개당 +0.03 (차단기 없으면 +0.05) / 100m 접근 알림", "category": "보조인프라", "added": "v11-2026.05.25"},
    ]
    for s in sources:
        meta = fresh.get(s["id"]) or {}
        s["last_fetched_at"] = meta.get("ts")
        s["age_s"] = _age(meta.get("ts"))
        s["mode"] = meta.get("mode", "stub")   # live | stub | cached
        s["last_success"] = meta.get("ok")
    # v12.135: 카테고리별 카운트 (출처 정직성 — 국내공공 vs 보조인프라 분리)
    domestic = [s for s in sources if s.get("category") == "국내공공"]
    aux = [s for s in sources if s.get("category") == "보조인프라"]
    return {
        "sources": sources,
        "count": len(sources),
        "categories": {
            "국내공공": {
                "count": len(domestic),
                "ids": [s["id"] for s in domestic],
                "note": "한국 정부/공공기관 공식 API (주력 평가 대상 데이터)",
            },
            "보조인프라": {
                "count": len(aux),
                "ids": [s["id"] for s in aux],
                "note": "글로벌 오픈데이터 (no-key fallback, 정확도 보강 용도)",
            },
        },
        "schema_version": "fusion.v11-2026.05.25-25src",
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


# v4 2026-05-16: 12 → 15종 확장
@router.get("/air-quality")
def fusion_air_quality(sido: str = Query("서울")):
    """시도별 실시간 미세먼지 (PM10/PM2.5)."""
    return public_api.fetch_air_quality(sido=sido)


@router.get("/school-route")
def fusion_school_route(lat: float = Query(37.5081), lon: float = Query(127.0440),
                        radius_m: float = Query(800.0, ge=50.0, le=5000.0)):
    """반경 N m 내 어린이 통학로 + 등하교 시간대 boost."""
    return public_api.fetch_school_routes(lat=lat, lon=lon, radius_m=radius_m)


@router.get("/ev-charger")
def fusion_ev_charger(lat: float = Query(37.5665), lon: float = Query(126.9780),
                       radius_m: float = Query(500.0, ge=50.0, le=5000.0)):
    """반경 N m 내 EV 충전소 + 사용률 → 정차 패턴 이상탐지."""
    return public_api.fetch_ev_chargers(lat=lat, lon=lon, radius_m=radius_m)


@router.get("/crosswalk")
def fusion_crosswalk(lat: float = Query(37.5665), lon: float = Query(126.9780),
                      radius_m: float = Query(300.0, ge=50.0, le=2000.0)):
    """v12.88: 반경 N m 내 횡단보도 + 신호등 유무 + 스쿨존.
    Flutter 앱이 위치 게이팅(_isNearTrafficSignal)용으로 호출 → OSM Overpass live."""
    return public_api.fetch_crosswalk_gis(lat=lat, lon=lon, radius_m=radius_m)


@router.get("/earthquake")
def fusion_earthquake(lat: float = Query(37.5665), lon: float = Query(126.9780),
                       radius_km: float = Query(500.0, ge=10.0, le=2000.0),
                       days_back: int = Query(30, ge=1, le=180),
                       min_magnitude: float = Query(2.0, ge=0.0, le=8.0)):
    """v10 2026-05-25: USGS FDSN 실시간 지진 (no-key) — 터널/교량 인프라 안전 prior.
    반경 N km, 최근 N일, M? 이상. 응답: events[] + derived (max_mag, 24h count, risk_boost)."""
    return public_api.fetch_usgs_earthquakes(lat=lat, lon=lon,
        radius_km=radius_km, days_back=days_back, min_magnitude=min_magnitude)


@router.get("/railway-crossing")
def fusion_railway_crossing(lat: float = Query(37.5665), lon: float = Query(126.9780),
                              radius_m: float = Query(2000.0, ge=100.0, le=10000.0)):
    """v11 2026-05-25: OSM 철도 건널목 (no-key) — 한국 KORAIL 사고다발 지점.
    반경 N m, 차단기/경고등 유무 표시. 응답: crossings[] + derived (nearest_m, unbarriered count)."""
    return public_api.fetch_railway_level_crossings(lat=lat, lon=lon, radius_m=radius_m)


# v5 2026-05-18: 15 → 17종 확장
@router.get("/road-surface")
def fusion_road_surface(lat: float = Query(37.5665), lon: float = Query(126.9780),
                        radius_m: float = Query(2000.0, ge=100.0, le=20000.0)):
    """반경 N m RWIS 도로 노면 상태 (건조/습윤/적설/결빙) + 위험 가중치."""
    return public_api.fetch_road_surface(lat=lat, lon=lon, radius_m=radius_m)


@router.get("/vehicle-inspection")
def fusion_vehicle_inspection(district: str = Query("강남구")):
    """KOTSA 시군구별 자동차검사 부적합률 → 잠재 사고 위험 지표."""
    return public_api.fetch_vehicle_inspection(district=district)


# v6 2026-05-18: 17 → 19종 확장
@router.get("/dtg")
def fusion_dtg(vehicle_type: str = Query("법인택시")):
    """KOTSA DTG 디지털운행기록 — 사업용 차량 위험운전 지표 (택시·버스·화물)."""
    return public_api.fetch_dtg_stats(vehicle_type=vehicle_type)


@router.get("/nfa-dispatch")
def fusion_nfa_dispatch(sido: str = Query("서울특별시")):
    """소방청 119 교통사고 출동 통계 — 사고 심각도 prior + 골든타임 라우팅."""
    return public_api.fetch_nfa_dispatch(sido=sido)


# v7 2026-05-19: 19 → 21종 확장
@router.get("/road-age")
def fusion_road_age(sido: str = Query("서울특별시")):
    """행정안전부 도로 노후도 — 노후 포장 비율 + 포트홀 밀도."""
    return public_api.fetch_road_age(sido=sido)


@router.get("/av-hub")
def fusion_av_hub(region: str = Query("판교")):
    """KOTSA 자율주행 데이터허브 — V2X RSU + HD map + AV 시범운행 통계."""
    return public_api.fetch_av_hub(region=region)


# v12.16: 어디서든 GPS 좌표 기반 동적 fusion — intersection_id 없어도 OK
@router.get("/here")
def fusion_here(
    lat: float = Query(..., description="현재 위도"),
    lon: float = Query(..., description="현재 경도"),
    radius_m: float = Query(550.0, description="bbox 반경 m"),
):
    """GPS 좌표로 직접 fusion 호출 — intersection_id 자동 생성 (gps-grid-셀).

    네이티브앱이 어디서 사용되든 (8 known intersection 밖이라도) 작동.
    """
    # 100m grid cell ID
    iid = f"gps-{int(lat * 1000)}-{int(lon * 1000)}"
    d = radius_m / 111000.0   # deg lat 1°≈111km
    bbox = {
        "minLat": lat - d, "maxLat": lat + d,
        "minLon": lon - d, "maxLon": lon + d,
    }
    fusion = public_api.fetch_fusion(iid, bbox=bbox)
    return fusion.to_dict()


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


# v12.52: risk-breakdown 60s 캐시 (라이브 응답시간 30s+ → <1s)
_RISK_BREAKDOWN_CACHE: dict = {}  # iid → {at, payload}
_RISK_BREAKDOWN_TTL = 60  # seconds


@router.get("/risk-breakdown/{intersection_id}")
def fusion_risk_breakdown(intersection_id: str):
    """v12.49: 각 23 소스가 fusion_risk_score 에 얼마나 기여했는지 분해.

    가중치 모델 (services/public_api.py to_dict 와 동일):
      speed(0.13) + 돌발(0.08) + TAAS(0.08) + 우천(0.07) + ER(0.04) + 자전거(0.04)
      + 결빙(0.06) + 보행다발(0.05) + 스쿨존(0.08) + 통학로(0.05) + PM10(0.03)
      + EV(0.02) + 노면(0.06) + 검사(0.04) + DTG(0.06) + 119(0.05) + 노후(0.06)
      + 단속(0.04) + 횡단(0.05) − V2X 감산

    v12.52: 60s 인메모리 캐시 (iid 별 키).
    """
    import time
    now = time.time()
    cached = _RISK_BREAKDOWN_CACHE.get(intersection_id)
    if cached and (now - cached["at"]) < _RISK_BREAKDOWN_TTL:
        out = dict(cached["payload"])
        out["cache_age_s"] = round(now - cached["at"], 1)
        return out

    fusion = public_api.fetch_fusion(intersection_id).to_dict()
    s = fusion.get("fusion_summary", {})

    avg_speed = s.get("avg_vds_speed_kmh", 60) or 60
    items = [
        {"id": "vds",                "label": "VDS 평균속도",       "raw": f"{avg_speed}km/h",                "value": round((1 - min(avg_speed, 80)/80), 3),       "weight": 0.13},
        {"id": "incidents",          "label": "돌발 N건",            "raw": f"{s.get('active_incidents', 0)}건", "value": round(min(s.get("active_incidents", 0), 3)/3, 3), "weight": 0.08},
        {"id": "taas",               "label": "TAAS 사고이력",      "raw": f"{s.get('taas_accidents_nearby', 0)}건", "value": round(min(s.get("taas_accidents_nearby", 0), 7)/7, 3), "weight": 0.08},
        {"id": "weather",            "label": "기상 (우천)",         "raw": "비" if s.get("weather_raining") else "맑음", "value": s.get("wet_road_risk_boost", 0), "weight": 0.07},
        {"id": "medical",            "label": "ER 포화도",           "raw": f"{round((s.get('nearest_ER_load', 0) or 0)*100)}%", "value": s.get("nearest_ER_load", 0) or 0, "weight": 0.04},
        {"id": "bike",               "label": "자전거 prior",        "raw": f"+{round((s.get('bike_lane_risk_boost', 0) or 0)*100)}%", "value": s.get("bike_lane_risk_boost", 0) or 0, "weight": 0.04},
        {"id": "black_ice",          "label": "결빙",                "raw": "위험" if s.get("black_ice_risk") else "안전", "value": s.get("freeze_risk_boost", 0) or 0, "weight": 0.06},
        {"id": "pedestrian_hotspot", "label": "보행 다발",            "raw": "진입" if s.get("in_pedestrian_hotspot") else "—", "value": s.get("ped_hotspot_boost", 0) or 0, "weight": 0.05},
        {"id": "school_zone",        "label": "스쿨존 (-1)",         "raw": f"×{s.get('school_zone_multiplier', 1.0)}",   "value": max(0, (s.get("school_zone_multiplier", 1.0) or 1) - 1.0), "weight": 0.08},
        {"id": "school_route",       "label": "통학로",              "raw": "활성" if s.get("on_school_route") else "—", "value": s.get("walk_route_boost", 0) or 0, "weight": 0.05},
        {"id": "air_quality",        "label": "미세먼지",            "raw": f"PM10 {round(s.get('pm10_avg', 0) or 0)}", "value": s.get("air_quality_risk_boost", 0) or 0, "weight": 0.03},
        {"id": "ev_charger",         "label": "EV 정차 확률",        "raw": f"{round((s.get('ev_dwelling_likelihood', 0) or 0)*100)}%", "value": s.get("ev_dwelling_likelihood", 0) or 0, "weight": 0.02},
        {"id": "road_surface",       "label": "노면 상태",           "raw": str(s.get("road_surface", "dry")), "value": s.get("surface_risk_boost", 0) or 0, "weight": 0.06},
        {"id": "vehicle_inspection", "label": "검사 부적합률",       "raw": f"{round((s.get('inspection_fail_rate_district', 0) or 0)*100)}%", "value": s.get("inspection_risk_boost", 0) or 0, "weight": 0.04},
        {"id": "dtg",                "label": "DTG 위험점수",        "raw": f"{s.get('dtg_danger_score', 0)}", "value": s.get("dtg_risk_boost", 0) or 0, "weight": 0.06},
        {"id": "nfa_dispatch",       "label": "119 골든타임",        "raw": f"×{s.get('nfa_severity_multiplier', 1.0)}", "value": s.get("nfa_severity_risk_boost", 0) or 0, "weight": 0.05},
        {"id": "road_age",           "label": "도로 노후",           "raw": f"{round((s.get('road_aged_15y_plus_pct', 0) or 0)*100)}%", "value": s.get("road_age_risk_boost", 0) or 0, "weight": 0.06},
        {"id": "police_cam",         "label": "단속 CCTV",          "raw": f"{s.get('enforcement_cam_count', 0)}대", "value": s.get("enforcement_risk_boost", 0) or 0, "weight": 0.04},
        {"id": "crosswalk",          "label": "횡단보도",            "raw": "50m 접근" if s.get("approaching_crosswalk") else f"{s.get('crosswalk_count_within_radius', 0)}개소", "value": s.get("crosswalk_pedestrian_boost", 0) or 0, "weight": 0.05},
        # v12.133: 24-25 source 추가 (USGS 지진 + OSM 철도건널목)
        {"id": "earthquake",         "label": "지진 인프라",         "raw": f"M{s.get('earthquake_max_mag', 0.0):.1f} (24h: {s.get('earthquake_recent_24h', 0)}건)" if s.get("earthquake_max_mag") else "—", "value": s.get("earthquake_risk_boost", 0) or 0, "weight": 0.03},
        {"id": "railway_crossing",   "label": "철도 건널목",         "raw": f"{s.get('railway_crossing_count', 0)}개 (가까운 {s.get('nearest_railway_m', '—')}m)" if s.get("railway_crossing_count") else "—", "value": s.get("railway_risk_boost", 0) or 0, "weight": 0.04},
    ]
    for it in items:
        it["contribution"] = round(it["value"] * it["weight"], 4)

    items_sorted = sorted(items, key=lambda x: -x["contribution"])
    raw_sum = sum(it["contribution"] for it in items_sorted)
    av_reduce = s.get("av_risk_reduce", 0) or 0
    final = s.get("fusion_risk_score", 0) or 0

    payload = {
        "intersection_id": intersection_id,
        "schema_version": s.get("schema_version"),
        "final_risk_score": final,
        "risk_level": s.get("risk_level"),
        "av_risk_reduce": av_reduce,
        "approaching_crosswalk_boost_x1_10": s.get("approaching_crosswalk", False),
        "school_zone_multiplier_applied": s.get("school_zone_multiplier", 1.0) if s.get("in_school_zone") else 1.0,
        "raw_weighted_sum": round(raw_sum, 4),
        "components_sorted_by_contribution": items_sorted,
        "cache_ttl_s": _RISK_BREAKDOWN_TTL,
        "note": "value × weight = contribution. final_risk_score 는 스쿨존 배수·횡단접근 ×1.10·V2X 감산 후 [0, 1] clamp.",
    }
    _RISK_BREAKDOWN_CACHE[intersection_id] = {"at": now, "payload": payload}
    return payload
