"""
Impact Calculator — 정량적 사고 예방 효과 (수상용 헤드라인 숫자).

  GET  /impact                          기본 가정 (lead_time=3.38s, coverage=10%)
  GET  /impact?lead=2.5&coverage=0.05   파라미터 조정
  GET  /impact/scenarios                Pilot 5% / 확산 25% / 전국 100% 표
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..services import impact as impact_service

router = APIRouter()


@router.get("")
@router.get("/")
def impact(
    lead: float = Query(3.38, description="평균 선행경고 시간 (초)"),
    coverage: float = Query(0.10, ge=0.0, le=1.0, description="도시 교차로 도입 비율"),
    scenario_overlap: float = Query(impact_service.SCENARIO_OVERLAP, ge=0.0, le=1.0),
):
    inp = impact_service.ImpactInputs(
        avg_lead_time_s=lead,
        coverage_urban_intersections=coverage,
        scenario_overlap=scenario_overlap,
    )
    return impact_service.estimate(inp).to_dict()


@router.get("/scenarios")
def scenarios(lead: float = Query(3.38)):
    return {
        "lead_time_s": lead,
        "scenarios": impact_service.scenarios(lead_time_s=lead),
    }


@router.get("/top-intersections")
def top_intersections(
    lead: float = Query(3.38, description="평균 선행경고 시간 (초)"),
    top_n: int = Query(10, ge=1, le=22, description="반환할 Top-N 교차로 수"),
    scope: str = Query("seoul", regex="^(seoul|national)$", description="seoul (12) | national (22, 5대 광역)"),
):
    """위험 교차로 Top-N 랭킹 + 교차로별 예방 효과 (사망·중상 기준)."""
    return impact_service.top_intersections(lead_time_s=lead, top_n=top_n, scope=scope)
