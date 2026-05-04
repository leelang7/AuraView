"""
AuraView Impact Calculator — 정량적 사고 예방 효과 추정.

심사 임팩트 메시지: "AuraView 가 연간 N 건 사고 / M 명 사상자 예방"
모든 수치는 출처 + 가정을 투명하게 노출 (judging 시 검증 가능).

Sources (2024 기준 공개 통계):
  - 도로교통공단 TAAS: 2024 교통사고 207,535 건 · 사망 2,581 명 · 부상 290,400 명
    https://taas.koroad.or.kr/sta/acs/exs/typical.do?menuId=WEB_KMP_OVT_UAS_PDS
  - 경찰청 보행사고 통계: 보행자 사망 약 800 명 · 도시부 비중 70%
  - 교통연구원 ITS 효과 분석:
    1초 선행 경고 → 충돌 회피율 약 25%
    3초 선행 경고 → 약 75% (운전자 반응시간 1.0~1.5s + 제동거리)

Model:
  preventability(lead_time_s) = min(0.85, 0.25 * lead_time_s)
    · 1초 → 25%, 2초 → 50%, 3초 → 75%, 3.4초+ → 85% (cap)

  prevented_accidents(coverage, lead_time) =
      annual_total × coverage × preventability(lead_time) × scenario_overlap
    · scenario_overlap: AuraView 가 다루는 사고 유형 비율 (가림/사각/신호) ≈ 0.42
      (TAAS 사고 유형 분포: 차대보행 22% · 차대차 측면 11% · 신호위반 9% 등)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


# ── 공개 통계 (2024 기준, 출처 명시 필수) ──────────────────────────────
ANNUAL_ACCIDENTS_TOTAL = 207_535       # TAAS 2024
ANNUAL_DEATHS = 2_581
ANNUAL_INJURED = 290_400
ANNUAL_PEDESTRIAN_DEATHS = 800
URBAN_INTERSECTION_RATIO = 0.46        # 전체 사고 중 도시부 교차로 비중 (TAAS)
SCENARIO_OVERLAP = 0.42                # AuraView 가 직접 도움이 되는 유형 비율
                                        # (보행 가림 22% + 측면 11% + 신호 9% ≈ 42%)


@dataclass
class ImpactInputs:
    avg_lead_time_s: float = 3.38       # /summary.json 의 trained 모델 평균
    coverage_urban_intersections: float = 0.10  # 0~1 — 도시 교차로 중 도입 비율
    scenario_overlap: float = SCENARIO_OVERLAP


@dataclass
class ImpactResult:
    inputs: dict
    preventability: float                # 0~0.85 — 본 lead time 의 회피율
    annual_baseline: dict                # 한국 통계 baseline
    projected_prevented: dict            # 연간 예방 추정
    methodology: dict                    # 계산식·가정·출처

    def to_dict(self) -> dict:
        return {
            "inputs": self.inputs,
            "preventability": round(self.preventability, 4),
            "annual_baseline": self.annual_baseline,
            "projected_prevented": self.projected_prevented,
            "methodology": self.methodology,
        }


def _preventability(lead_time_s: float) -> float:
    """선행경고 시간 → 충돌 회피 가능 비율. cap 85%."""
    return min(0.85, max(0.0, 0.25 * float(lead_time_s)))


def estimate(inp: Optional[ImpactInputs] = None) -> ImpactResult:
    inp = inp or ImpactInputs()
    p = _preventability(inp.avg_lead_time_s)

    # 도시 교차로 사고 = 전체 × 도시비중
    urban_accidents = ANNUAL_ACCIDENTS_TOTAL * URBAN_INTERSECTION_RATIO
    urban_deaths = ANNUAL_DEATHS * URBAN_INTERSECTION_RATIO
    urban_injured = ANNUAL_INJURED * URBAN_INTERSECTION_RATIO

    # AuraView 적용 가능 사고 = 도시 × 시나리오 적용율 × 도입 커버리지
    addressable = urban_accidents * inp.scenario_overlap * inp.coverage_urban_intersections
    addressable_deaths = urban_deaths * inp.scenario_overlap * inp.coverage_urban_intersections
    addressable_injured = urban_injured * inp.scenario_overlap * inp.coverage_urban_intersections

    prevented = addressable * p
    prevented_deaths = addressable_deaths * p
    prevented_injured = addressable_injured * p

    return ImpactResult(
        inputs=asdict(inp),
        preventability=p,
        annual_baseline={
            "accidents_total": ANNUAL_ACCIDENTS_TOTAL,
            "deaths_total": ANNUAL_DEATHS,
            "injured_total": ANNUAL_INJURED,
            "urban_share": URBAN_INTERSECTION_RATIO,
            "urban_accidents": int(urban_accidents),
            "urban_deaths": int(urban_deaths),
            "urban_injured": int(urban_injured),
        },
        projected_prevented={
            "addressable_accidents": int(addressable),
            "prevented_accidents": int(prevented),
            "prevented_deaths": int(prevented_deaths),
            "prevented_injured": int(prevented_injured),
            "headline": f"연간 사고 {int(prevented):,}건 · 사망 {int(prevented_deaths):,}명 · 부상 {int(prevented_injured):,}명 예방",
        },
        methodology={
            "preventability_formula": "min(0.85, 0.25 * lead_time_s)",
            "coverage_definition": "도시부 교차로 중 AuraView 도입 비율 (0~1)",
            "scenario_overlap_definition": "AuraView 가 직접 도움이 되는 사고 유형 비율 (가림·사각지대·신호 = 42%)",
            "sources": [
                {
                    "name": "도로교통공단 TAAS 2024 통계",
                    "url": "https://taas.koroad.or.kr/sta/acs/exs/typical.do",
                    "values_used": {
                        "annual_accidents": ANNUAL_ACCIDENTS_TOTAL,
                        "annual_deaths": ANNUAL_DEATHS,
                        "annual_injured": ANNUAL_INJURED,
                    },
                },
                {
                    "name": "교통연구원 (KOTI) ITS 효과 분석",
                    "summary": "1초 선행경고 ≈ 25% 회피, 3초 ≈ 75%",
                },
            ],
            "assumptions": [
                "도시 교차로 사고 비중 46% (TAAS 도로종류별 사고 분류)",
                "AuraView 다루는 시나리오 적용율 42% (보행/측면/신호 합산)",
                "선행경고 → 회피율 변환은 운전자 반응시간 1.0~1.5s 가정 선형 모델",
            ],
        },
    )


def scenarios(lead_time_s: float = 3.38) -> List[Dict[str, object]]:
    """커버리지 시나리오별 예방 추정 (5%, 25%, 100%) — 슬라이드용 표."""
    out = []
    for cov, label in [(0.05, "Pilot · 5%"), (0.25, "확산 · 25%"), (1.00, "전국 · 100%")]:
        r = estimate(ImpactInputs(avg_lead_time_s=lead_time_s, coverage_urban_intersections=cov))
        out.append({
            "label": label,
            "coverage": cov,
            "prevented_accidents": r.projected_prevented["prevented_accidents"],
            "prevented_deaths": r.projected_prevented["prevented_deaths"],
            "prevented_injured": r.projected_prevented["prevented_injured"],
        })
    return out
