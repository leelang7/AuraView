# AuraView Press Kit

> **한 줄로:** 블랙박스 한 대로 사각지대까지 계산하는 한국형 K-Perception 플랫폼.
> Tesla FSD 의 Occupancy + Fleet Learning 에 **한국 도로 협업 인지 (V2V + Bus + Bidirectional)** 와 **6종 공공데이터 결합** 을 더했다.

[![demo](https://img.shields.io/badge/demo-auraview.allthatai.kr-00e09a)](https://auraview.allthatai.kr/ui)
[![CI](https://github.com/leelang7/AuraView/actions/workflows/ci.yml/badge.svg)](https://github.com/leelang7/AuraView/actions)
[![AUC](https://img.shields.io/badge/AUC-0.9403-00c8ff)](https://auraview.allthatai.kr/summary.json)
[![Inference](https://img.shields.io/badge/p99-1.04ms-7c3aed)](https://auraview.allthatai.kr/benchmark/all)

---

## 🎯 임팩트 헤드라인

> **AuraView 가 도시 교차로의 5% 에 도입되면 — 연간 사고 1,694건 · 사망 21명 · 부상 2,370명 예방.**

| 도입 시나리오 | 사고 예방/년 | 사망 감소 | 부상 감소 |
|---|---:|---:|---:|
| Pilot 5%   | **1,694건** | **21명**  | **2,370명** |
| 확산 25%   | 8,470건     | 105명     | 11,852명 |
| 전국 100%  | 33,880건    | 421명     | 47,408명 |

**산출 근거** (라이브 검증 가능 — `/impact`):
- TAAS 2024: 사고 207,535 / 사망 2,581 / 부상 290,400
- 도시 교차로 비중 46% (TAAS 도로종류별)
- AuraView 적용 시나리오 비중 42% (보행 가림 22% + 측면 11% + 신호 9%)
- 회피율 `min(0.85, 0.25 × lead_time_s)` (KOTI ITS 효과 분석)
- 트레인드 모델 평균 lead time = **3.38s** → 회피율 **84.5%**

---

## 🎯 위험 교차로 Top-10 — 도입 우선순위 (서울)

> **이 10개 교차로만 우선 도입해도 연간 사망·중상 85명 예방** (라이브 검증 가능 · `/impact/top-intersections`)

| # | 교차로 | 구 | 유형 | 연 사망·중상 | 예방 (도입 시) |
|---|---|---|---|---:|---:|
| 1 | **강남역 사거리** | 서초구 | 보행 + 차대차 | 14 | **11.8명** |
| 2 | **잠실역 교차로** | 송파구 | 보행 가림 + 신호 | 12 | **10.1명** |
| 3 | **광화문 사거리** | 종로구 | 보행 다중차로 | 11 | **9.3명** |
| 4 | **신촌역 로터리** | 서대문구 | 버스 + 보행 폭주 | 10 | **8.4명** |
| 5 | **청량리역 사거리** | 동대문구 | 고령보행 + 우회전 | 10 | **8.4명** |
| 6 | **건대입구 사거리** | 광진구 | 이륜 + 측면 | 9 | **7.6명** |
| 7 | **사당역 사거리** | 동작구 | 혼잡 + 교차 | 9 | **7.6명** |
| 8 | **홍대입구 교차로** | 마포구 | 야간 보행 | 9 | **7.6명** |
| 9 | **신림역 교차로** | 관악구 | 이륜 + 보행 | 8 | **6.8명** |
| 10 | **서울역 광장** | 중구 | 교통 결절 | 8 | **6.8명** |

출처: TAAS 다발지역 분석 + 도로교통공단 보행자사고 통계.

---

## ⚡ 핵심 차별화 5종 (`/positioning/tesla-vs-auraview`)

| 카테고리 | Tesla 방식 | AuraView | 한국 특화 이유 |
|---|---|---|---|
| 차량 간 협업 | 자기 시점만 | **V2V Cross-Vehicle** — 마주오는 차의 detection 머지 | 신호위반 보복운전 대응 |
| 정류장 prior | 일반 보행자 검출 | **Bus-Aware** — dwelling/departing/passing | 정류장 무단횡단 hotspot |
| 마주오는 차로 | 단방향 예측 | **Bidirectional Lane Fusion** + VDS 비대칭 | 황색실선 무시 빈번 |
| 공공 신호 결합 | 비전만 | **신호 API + ITS** 결합 | 한국 신호 API 발달 |
| 정책 환원 | Tesla 내부 | **위험 교차로 Top-N 자동 리포트** + 안심구역 | 가명결합 k=5 익명 |

---

## 📊 실측 성능

| 지표 | 값 | 출처 |
|---|---|---|
| Trained Risk Transformer AUC | **0.9403** | `models/risk_transformer_trained_metric.json` |
| F1 @ 0.5 | **0.9412** | 학습 결과 |
| 평균 선행 경고 | **3.38초** | 8 시나리오 × 2,000 샘플 평가 |
| 추론 지연 (p99) | **1.04 ms** | `/benchmark/risk` 실측 100회 |
| V2V merge 지연 (p99) | **0.03 ms** | `/benchmark/v2v-merge` |
| 모델 크기 | **278 KB** (67,970 params) | 가중치 published |
| 라우트 수 | **80+** (impact + metrics + positioning) | `/healthz/details` |
| 테스트 | **68 / 68 PASS** (38 baseline + 30 경진대회 features incl. policy/manifest/api-directory/resources) | `pytest tests/` |

---

## 🌐 라이브 검증 URL

| 용도 | URL |
|---|---|
| 풀 대시보드 (9탭) | https://auraview.allthatai.kr/ui |
| 원페이지 요약 (인쇄용) | https://auraview.allthatai.kr/submission/ |
| Reveal.js 발표 슬라이드 | https://auraview.allthatai.kr/slides/ |
| 무인 자동 시연 키오스크 | https://auraview.allthatai.kr/kiosk/ |
| 합본 시연 영상 | https://auraview.allthatai.kr/showreel/latest.mp4 |
| **경진대회 통합 KPI** | https://auraview.allthatai.kr/metrics/competition |
| **5개 평가항목 자체채점** | https://auraview.allthatai.kr/metrics/scoreboard |
| **A4 1-pager 정책 PDF** | https://auraview.allthatai.kr/impact/policy-pdf |
| **도로교통법 조항 매핑** | https://auraview.allthatai.kr/policy/laws |
| **시행규칙 + 컴플라이언스** | https://auraview.allthatai.kr/policy/regulations |
| **데이터 출처 명시** | https://auraview.allthatai.kr/metrics/data-attribution |
| **8 시나리오 매트릭스** | https://auraview.allthatai.kr/occupancy/compare |
| 임팩트 (TAAS 결합) | https://auraview.allthatai.kr/impact |
| 임팩트 시나리오 | https://auraview.allthatai.kr/impact/scenarios |
| Tesla 비교 5종 | https://auraview.allthatai.kr/positioning/tesla-vs-auraview |
| 데이터 freshness | https://auraview.allthatai.kr/fusion/sources |
| 추론 벤치마크 | https://auraview.allthatai.kr/benchmark/all |
| Swagger API 문서 | https://auraview.allthatai.kr/docs |

---

## 🚀 30초 데모 시나리오

1. **5초**: https://auraview.allthatai.kr/ → 자동 /ui 이동
2. **8초**: TAB ① 시나리오 8종 picker → 트럭/이륜/우회전/스쿨존/자전거/야간 클릭만으로 전환
3. **7초**: TAB ⑤ Capability Matrix → 임팩트 카드 + 인터랙티브 시뮬레이터
4. **5초**: TAB ⑨ V2V → 단독 vs 협업 인지 비교
5. **5초**: TAB ⑩ 공공데이터 라이브 → 6종 freshness 실시간 모니터

키오스크 모드 (10장면 자동 순환): https://auraview.allthatai.kr/kiosk/

## 🔍 심사위원 1-step 검증

```bash
curl https://auraview.allthatai.kr/metrics/competition  # 4축 KPI 한 응답
curl https://auraview.allthatai.kr/metrics/scoreboard   # 5항목 자체 채점
curl -O https://auraview.allthatai.kr/impact/policy-pdf # A4 PDF 자동 다운로드
```

---

## 🏗️ 시스템 아키텍처

```
                    ┌─────────────────────────────┐
                    │      6종 공공 데이터        │
                    │  신호 · VDS · 돌발 · TAAS  │
                    │       ITS · 안심구역        │
                    └──────────────┬──────────────┘
                                   │ fusion
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
   ┌──────────────────┐                    ┌─────────────────────┐
   │  Vision Pipeline │                    │   Korean K-Perception│
   │  YOLOv8 + HydraNet│                    │   - V2V Cross-Vehicle│
   │  Occupancy BEV    │                    │   - Bus-Aware Prior  │
   └────────┬──────────┘                    │   - Bidirectional    │
            │                               └──────────┬──────────┘
            └──────────┐                ┌───────────────┘
                       ▼                ▼
              ┌─────────────────────────────┐
              │   Risk Transformer (E2E)    │
              │   2L · d=64 · 67,970 params │
              │   AUC 0.94 · p99 = 1.04 ms  │
              └──────────────┬──────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌──────────────┐
      │  운전자 경고 │ │  K-MaaS  │ │ 정책 리포트  │
      │  HUD 오버레이 │ │ 우회 추천 │ │ Top-N 자동  │
      └──────────────┘ └──────────┘ └──────────────┘
```

---

## 📦 재현 (Reproducibility)

```bash
git clone https://github.com/leelang7/AuraView.git
cd AuraView
docker compose up -d
# → http://localhost:8000/ → /ui
```

또는 Native:
```bash
pip install -r requirements.txt
cd backend && uvicorn app.main:app --port 8000
pytest tests/   # 36/36 PASS
```

---

## 📞 문의

- **Repo:** https://github.com/leelang7/AuraView
- **Live:** https://auraview.allthatai.kr
- **Brand:** https://allthatai.kr
- **License:** MIT
