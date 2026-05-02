"""
K-MaaS 연계 엔드포인트.

  GET /kmaas/alternatives?origin_lat=..&origin_lon=..&dest_lat=..&dest_lon=..&risk=..
      위험 교차로 우회 대중교통 대안 3종 추천

  GET /kmaas/operator-report
      상습 위험 교차로 → K-MaaS 노선 운영팀용 요약 (top hazards 자동 집계)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..routers.events import map_data as _map_data_route  # reuse aggregation
from ..services import kmaas

router = APIRouter()


@router.get("/alternatives")
def alternatives(
    origin_lat: float = Query(...),
    origin_lon: float = Query(...),
    dest_lat: float = Query(...),
    dest_lon: float = Query(...),
    risk: float = Query(0.0, description="현재 교차로 위험 점수 (0~15+ 권고)"),
):
    alts = kmaas.fetch_alternatives(origin_lat, origin_lon, dest_lat, dest_lon, risk_score=risk)
    return {
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "destination": {"lat": dest_lat, "lon": dest_lon},
        "risk_score": risk,
        "alternatives": [a.to_dict() for a in alts],
        "headline": (
            f"⚠️ 전방 위험도 {risk:.1f} — K-MaaS 대중교통 대안을 우선 추천합니다."
            if risk >= 6 else "현 경로 안전 — 참고용 대안 제시"
        ),
    }


@router.get("/operator-report")
def operator_report(db: Session = Depends(get_db)):
    """현재 누적된 위험 교차로 데이터를 K-MaaS 운영팀용으로 요약."""
    aggregated = _map_data_route(db=db)  # list[dict]
    summary = kmaas.aggregate_for_transit_planner(aggregated)
    summary["intersections_analyzed"] = len(aggregated)
    return summary
