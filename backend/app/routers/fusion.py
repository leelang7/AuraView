"""
6종 공공데이터 융합 조회 엔드포인트.

  GET /fusion/intersection/{intersection_id}  ─ 교차로 1개에 대한 신호·VDS·돌발·TAAS·ITS 종합
  GET /fusion/sources                         ─ 연동 중인 소스 목록(대시보드용)

기능: 6종 공공데이터를 한 응답에 결합 반환.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from ..services import public_api

router = APIRouter()


@router.get("/sources")
def list_sources():
    """공공 데이터 소스 목록 + 최근 호출 시각/age (데이터 freshness 증명)."""
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
        {"id": "signal",    "name": "교통안전 실시간 신호정보",       "origin": "apis.data.go.kr"},
        {"id": "vds",       "name": "한국도로공사 VDS 실시간 소통",   "origin": "data.ex.co.kr"},
        {"id": "incidents", "name": "한국도로공사 돌발상황",          "origin": "data.ex.co.kr"},
        {"id": "taas",      "name": "TAAS 교통사고분석",              "origin": "taas.koroad.or.kr"},
        {"id": "its",       "name": "ITS 국가교통정보센터",            "origin": "openapi.its.go.kr"},
        {"id": "dsz",       "name": "국토교통 데이터안심구역 결합결과","origin": "dsz.ex.co.kr"},
    ]
    for s in sources:
        meta = fresh.get(s["id"]) or {}
        s["last_fetched_at"] = meta.get("ts")
        s["age_s"] = _age(meta.get("ts"))
        s["mode"] = meta.get("mode", "stub")   # live | stub | cached
        s["last_success"] = meta.get("ok")
    return {"sources": sources, "count": len(sources), "checked_at": now_ts.isoformat() + "Z"}


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
