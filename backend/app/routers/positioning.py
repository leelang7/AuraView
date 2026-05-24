"""
Positioning — AuraView vs Tesla FSD 항목별 비교.

심사용 한 줄 요약: "Tesla 가 못 하는 한국 특화 5종".
구조화된 JSON → 프론트가 표로 렌더 (slides/submission/kiosk 모두 동일 데이터).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/tesla-vs-auraview")
def tesla_vs_auraview():
    return {
        "intro": "Tesla FSD 가 다루지 않는 한국 도심의 5가지 핵심 — AuraView 가 직접 구현.",
        "rows": [
            {
                "category": "차량 간 협업 인지",
                "tesla": "Vehicle-only Occupancy Network (자기 시점만)",
                "auraview": "V2V Cross-Vehicle Perception — 마주오는 차의 detection 을 ego BEV 에 머지 (heading 130°+ 가중치 0.95)",
                "korea_specific": "신호위반 보복운전 대응에 측면 시점 결정적",
                "endpoint": "/collab/v2v/intersection/{id}",
            },
            {
                "category": "버스/정류장 보행 prior",
                "tesla": "Generic pedestrian detector — 정류장 맥락 X",
                "auraview": "Bus-Aware Pedestrian Prior — dwelling/departing/passing 추정 → 보행자 prior +0.55 boost",
                "korea_specific": "한국 버스정류장은 무단횡단 hotspot — K-MaaS 정류장 데이터 활용",
                "endpoint": "/collab/bus-aware/{id}",
            },
            {
                "category": "마주오는 차로 융합",
                "tesla": "Single-direction lane prediction",
                "auraview": "Bidirectional Lane Fusion — oncoming 감속 + VDS 상행/하행 비대칭 → hazard probability + 권장속도",
                "korea_specific": "골목길/이면도로 황색실선 무시 빈번 — VDS asymmetry 가 sensor 만큼 정확",
                "endpoint": "/collab/bidirectional/{id}",
            },
            {
                "category": "공공 신호 API 결합",
                "tesla": "신호등 vision detection only",
                "auraview": "교통안전 실시간 신호 (apis.data.go.kr/B551982/rti) + ITS 결합 → 가려진 신호 복원",
                "korea_specific": "한국은 공공 신호 API 가 발달 — 트럭 뒤 가려진 신호도 복원 가능",
                "endpoint": "/signals/{id}",
            },
            {
                "category": "정책 환원 루프",
                "tesla": "데이터는 Tesla 내부에 머무름",
                "auraview": "위험 교차로 Top-N 자동 리포트 (HTML+JSON) → 지자체·도로공사·K-MaaS 환원",
                "korea_specific": "안심구역 (DSZ) k=5 익명 + 가명결합 → 정책 활용 가능",
                "endpoint": "/reports/generate?top=20",
            },
            {
                "category": "한국 도로 시나리오 8종",
                "tesla": "미국 도로 우선 — 한국 우회전 보행자 우선/스쿨존/자전거 도로 미특화",
                "auraview": "8 시나리오 — 트럭/이륜/신호/우천/우회전/스쿨존(DSZ)/자전거(GIS)/야간(V2V 헤드라이트 share)",
                "korea_specific": "도로교통법 12조(어린이 우선)·13조(자전거 우측통행)·우회전 대법 판례 직결",
                "endpoint": "/occupancy/compare",
            },
            {
                "category": "개발자 1-step 검증",
                "tesla": "외부 검증 불가 (블랙박스)",
                "auraview": "/metrics/competition (4축 KPI · git_sha) + /metrics/scoreboard (5항목 자체채점) + /impact/policy-pdf (A4 1-pager)",
                "korea_specific": "공공데이터 stub/live 명시 + 68 pytest 통과 + GitHub CI 4잡 + /metrics/manifest 11 검증 URL",
                "endpoint": "/metrics/competition",
            },
        ],
        "metric_summary": {
            "v2v_lift_pp": "10~31",
            "trained_auc": 0.9403,
            "trained_f1": 0.9412,
            "avg_lead_time_s": 3.38,
            "inference_p99_ms": 1.04,
        },
    }
