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
        # v4 2026-05-16: 12 → 15종 확장
        {"id": "air_quality",  "name": "환경부 미세먼지 (PM10/PM2.5)", "origin": "apis.data.go.kr/B552584", "gain": "시정·카메라오염 +0.06", "added": "v4-2026.05.16"},
        {"id": "school_route", "name": "어린이 통학로 GIS",            "origin": "도로교통공단 통학로",     "gain": "통학시간 boost +0.18",  "added": "v4-2026.05.16"},
        {"id": "ev_charger",   "name": "EV 충전소 위치/사용률",        "origin": "apis.data.go.kr/B552584 (Ev)", "gain": "EV 정차 패턴 이상탐지", "added": "v4-2026.05.16"},
        # v5 2026-05-18: 15 → 17종 확장
        {"id": "road_surface",       "name": "도로 노면 상태 (RWIS)",         "origin": "data.ex.co.kr/openapi/rwisapi",          "gain": "노면 위험 (frost +0.35)",         "added": "v5-2026.05.18"},
        {"id": "vehicle_inspection", "name": "KOTSA 자동차검사통계",          "origin": "apis.data.go.kr/B552014/InspectionStats", "gain": "구별 부적합률 → 잠재 위험", "added": "v5-2026.05.18"},
        # v6 2026-05-18: 17 → 19종 확장
        {"id": "dtg",                "name": "KOTSA DTG 디지털운행기록",        "origin": "apis.data.go.kr/B552014/DtgStats",       "gain": "사업용 차량 위험운전 +0.10",   "added": "v6-2026.05.18"},
        {"id": "nfa_dispatch",       "name": "소방청 119 교통사고 출동",        "origin": "apis.data.go.kr/1661000/TfcAcdntDsptch", "gain": "사고 심각도 + 골든타임 라우팅", "added": "v6-2026.05.18"},
        # v7 2026-05-19: 19 → 21종 확장
        {"id": "road_age",           "name": "행정안전부 도로 노후도",           "origin": "apis.data.go.kr/1741000/RoadAgeStats",   "gain": "노후포장+포트홀 인프라 위험 +0.10", "added": "v7-2026.05.19"},
        {"id": "av_hub",             "name": "KOTSA 자율주행 데이터허브 (V2X)",  "origin": "apis.data.go.kr/B552014/AvHub",          "gain": "V2X RSU + HD map → 위험 감산", "added": "v7-2026.05.19"},
        # v8 2026-05-21: 21 → 22종 확장
        {"id": "police_cam",         "name": "경찰청 교통단속 CCTV 위치",         "origin": "apis.data.go.kr/1320000/CityTrafficCctv","gain": "단속 밀집 = 사고다발 prior +0.04", "added": "v8-2026.05.21"},
        # v9 2026-05-21: 22 → 23종 확장
        {"id": "crosswalk",          "name": "국토부 횡단보도 GIS",                "origin": "api.vworld.kr (lt_l_crwlk)",             "gain": "보행자 prior +0.05 / 50m 접근 ×1.10",       "added": "v9-2026.05.21"},
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
        "schema_version": "fusion.v9-23src-2026.05.21",
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
