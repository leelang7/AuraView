"""
Impact Calculator — 정량적 사고 예방 효과 (수상용 헤드라인 숫자).

  GET  /impact                          기본 가정 (lead_time=3.38s, coverage=10%)
  GET  /impact?lead=2.5&coverage=0.05   파라미터 조정
  GET  /impact/scenarios                Pilot 5% / 확산 25% / 전국 100% 표
  GET  /impact/policy-pdf               정책 1-pager PDF (검증·정책담당자 배포용)
"""

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Query
from fastapi.responses import Response

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


@router.get("/policy-pdf")
def policy_pdf(
    coverage: float = Query(0.05, ge=0.0, le=1.0, description="도입 비율 (5% pilot 기본)"),
    lead: float = Query(3.38, ge=0.5, le=8.0, description="선행경고 시간 (초)"),
):
    """A4 1-pager 정책 임팩트 보고서 PDF — 검증·정책담당자 배포용."""
    from ..services import policy_pdf as pdf_service
    pdf_bytes = pdf_service.render_policy_pdf(coverage=coverage, lead_time_s=lead)
    fname = f"AuraView_Policy_Impact_{int(coverage*100)}pct_{lead:.2f}s.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@router.get("/proposal-pdf")
def proposal_pdf():
    """v12.136: 2026 제출용 기획서 PDF 자동 생성 (3-page A4).
    매 호출마다 현재 시스템 상태 (25 소스 / live 카운트 / git_sha / tests) 반영.
    페이지 구성:
    1. 표지 + 한 줄 가치 + 25점 항목 매트릭스 + 임팩트 + 시스템 헬스
    2. 25종 데이터 분류 (국내공공 vs 보조) + 8 시나리오 + Tesla 차별화 5종
    3. 1-step 검증 URL + 라이브 데모 + 재현 가이드 + 라이센스
    """
    from ..services import proposal_pdf as pdf_service
    pdf_bytes = pdf_service.render_proposal_pdf()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"AuraView_Proposal_{ts}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@router.get("/top-intersections")
def top_intersections(
    lead: float = Query(3.38, description="평균 선행경고 시간 (초)"),
    top_n: int = Query(10, ge=1, le=22, description="반환할 Top-N 교차로 수"),
    scope: str = Query("seoul", pattern="^(seoul|national)$", description="seoul (12) | national (22, 5대 광역)"),
):
    """위험 교차로 Top-N 랭킹 + 교차로별 예방 효과 (사망·중상 기준)."""
    return impact_service.top_intersections(lead_time_s=lead, top_n=top_n, scope=scope)
