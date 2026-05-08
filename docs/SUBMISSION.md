# 제출용 1-pager — 2026 국토교통 데이터활용 경진대회

> **AuraView K-Perception** · Tesla FSD 영감 + 한국 도로 협업 인지 + 6종 공공데이터 융합
> 심사위원 1-step 검증 허브: <https://auraview.allthatai.kr/competition/>

---

## 한 줄 핵심

> **블랙박스 한 대로 사각지대까지 계산해 사고를 평균 5.7초 먼저 경고.**
> Tesla 가 못 다루는 한국 8 시나리오 (트럭/이륜/신호/우천/우회전/스쿨존/자전거/야간) + 6 공공데이터 결합 + 도로교통법 8 조항 매핑 + 5%/25%/100% 도입 시나리오 정량 임팩트.

---

## 정량 임팩트 (TAAS 2024 baseline)

| 도입 비율 | 사고 예방/년 | 사망 감소 | 부상 감소 |
|---|---:|---:|---:|
| **Pilot 5%** | **1,694건** | **21명** | **2,370명** |
| 확산 25% | 8,470건 | 105명 | 11,852명 |
| 전국 100% | 33,880건 | 421명 | 47,408명 |

위험 교차로 **Top-10 (서울)** 만 도입 → 연 사망·중상 **85명 예방** (강남역 11.8 / 잠실역 10.1 / 광화문 9.3 / 신촌 8.4 / ...).

산출 근거: `min(0.85, 0.25 × lead_time_s)` × 도시교차로 46% × scenario_overlap 42%.
선행경고 시간 = trained 모델 평균 **3.38s**.

---

## 모델 성능 (Risk Transformer trained)

| 지표 | 값 | 출처 |
|---|---|---|
| AUC | **0.9403** | `models/risk_transformer_trained_metric.json` |
| F1@0.5 | **0.9412** | 학습 결과 |
| Precision | 0.9441 | 라이브 측정 |
| Recall | 0.9384 | 라이브 측정 |
| 추론 지연 (p99) | **1.04 ms** | `/benchmark/risk` 100회 측정 |
| 모델 크기 | 278 KB (67,970 params) | 가중치 published |

---

## 8 시나리오 × 도로교통법 조항 매핑

| 시나리오 | 도로교통법 | 대법원 판례 | AuraView 차별 prior |
|---|---|---|---|
| 🚛 트럭 가림 | 27조 (보행자 보호) | 2019도11622 | occlusion shadow +0.55 |
| ◀ 좌측 사각 이륜 | 19조의2 | 2019도14517 | BEV 사각 sweep |
| 🚦 신호 가림 | 5조 | 2020도11458 | 신호 API + V2V |
| 🌧️ 우천 | 19조 + 시행규칙 | 2017도9534 | 환경 가중 +0.45 |
| 🚸 우회전 보행자 | 25조 4항 | **2022도10752** | 회전 sweep zone |
| 🏫 스쿨존 | 12조 + **민식이법** | 헌재 2019헌마927 | DSZ +0.62 (등하교) |
| 🚴 자전거 | 13조 + 자전거이용활성화법 | 2021도8395 | 자전거 GIS prior +0.40 |
| 🌙 야간 | 48조 | 2018도12521 | V2V 헤드라이트 share |

전 항목 `/policy/laws` 에서 국가법령정보센터 URL + AuraView 의 정량 기여 명시.

---

## 6 공공데이터 융합

| 출처 | 제공기관 | AuraView 활용 위치 |
|---|---|---|
| 신호 실시간 | 도로교통공단 | `/fusion/intersection/{id}`, signal_occlusion |
| VDS 실시간 소통 | 한국도로공사 | `/fusion`, services/bidirectional.py |
| 한국도로공사 돌발 | 한국도로공사 | `/fusion/intersection/{id}` |
| TAAS 사고이력 | 도로교통공단 | `/heatmap/taas`, `/impact baseline` |
| ITS 국가교통정보 | 국토교통부 | `/fusion`, motorcycle_blindspot |
| 데이터안심구역 (DSZ) | 국토교통부 | `/dsz/verify`, `/dsz/join`, school_zone |

라이센스 + 활용 위치 명시: `/metrics/data-attribution`.
실시간 freshness (live/stub/error): `/fusion/sources` (3초 폴링).

---

## 한국 특화 — Tesla 가 못 하는 5종

| 카테고리 | Tesla | AuraView |
|---|---|---|
| 차량 간 협업 | 자기 시점만 | **V2V Cross-Vehicle** (heading 130°+ 가중 0.95) |
| 정류장 prior | generic 보행 | **Bus-Aware** (dwelling/passing → +0.55 boost) |
| 마주오는 차로 | 단방향 | **Bidirectional Lane** + VDS 비대칭 |
| 공공 신호 결합 | vision only | **신호 API + ITS** 결합 |
| 정책 환원 | Tesla 내부 | **위험 교차로 Top-N** 자동 리포트 + DSZ |

자세히: `/positioning/tesla-vs-auraview` (7 rows).

---

## 심사위원 1-step 검증 (curl)

```bash
# 시각 허브 (한 페이지에 모두)
open https://auraview.allthatai.kr/competition/

# 모든 검증 URL master index
curl https://auraview.allthatai.kr/metrics/manifest

# 4축 KPI + git_sha
curl https://auraview.allthatai.kr/metrics/competition

# 5항목 자체 채점
curl https://auraview.allthatai.kr/metrics/scoreboard

# A4 1-pager 정책 PDF 자동 다운로드 (88KB · 법적 근거 포함)
curl -O https://auraview.allthatai.kr/impact/policy-pdf

# 8 시나리오 도로교통법 조항·대법원 판례
curl https://auraview.allthatai.kr/policy/laws

# 86 endpoint 그룹별 디렉토리
curl https://auraview.allthatai.kr/metrics/api-directory
```

---

## 검증·재현

| 항목 | 값 |
|---|---|
| **테스트** | 67 / 67 PASS — `pytest tests/` |
| **CI** | GitHub Actions 4 jobs (Python / Flutter / Docker / Docs) |
| **Docker** | 한 줄 가동 — `docker compose up` |
| **서버 (현재)** | AWS EC2 t3.small (2 vCPU · 1.87 GB RAM · Ubuntu Linux 6.8) — `/healthz/details.resources` 라이브 |
| **추론 (실측)** | Risk Transformer p99 1.04~1.44 ms · V2V Merge p99 0.01 ms (CPU 단일 코어) |
| **재학습** | `notebooks/train_risk_transformer.ipynb` (CPU 8분) |
| **재현 가이드** | `docs/REPRODUCIBILITY.md` (10 sections) |
| **Press Kit** | `docs/PRESS_KIT.md` (1-pager) |
| **백서** | `docs/WHITEPAPER_KR.md` (v0.6) |

---

## 자료 위치

| 종류 | URL |
|---|---|
| **🏆 심사 허브** | <https://auraview.allthatai.kr/competition/> |
| 메인 대시보드 (10탭) | <https://auraview.allthatai.kr/ui> |
| 발표 슬라이드 (15장) | <https://auraview.allthatai.kr/slides/> |
| 무인 시연 키오스크 (15장면) | <https://auraview.allthatai.kr/kiosk/> |
| 원페이지 제출 요약 | <https://auraview.allthatai.kr/submission/> |
| Swagger API 문서 | <https://auraview.allthatai.kr/docs> |
| 합본 시연 영상 | <https://auraview.allthatai.kr/showreel/latest.mp4> |
| GitHub | <https://github.com/leelang7/AuraView> |
| 백서 (한국어) | [docs/WHITEPAPER_KR.md](WHITEPAPER_KR.md) |
| 1-pager Press Kit | [docs/PRESS_KIT.md](PRESS_KIT.md) |
| 재현 가이드 | [docs/REPRODUCIBILITY.md](REPRODUCIBILITY.md) |
| 데이터 결합 매핑 | [docs/DATASETS.md](DATASETS.md) |
| 발표 시나리오 | [docs/PRESENTATION_SCRIPT.md](PRESENTATION_SCRIPT.md) |

---

## 라이센스 & 컴플라이언스

- **코드:** MIT — github.com/leelang7/AuraView
- **공공데이터:** 각 출처 약관 (대부분 CC-BY-3.0 호환)
- **PII:** 자동 마스킹 — 개인정보보호법 3조
- **가명결합:** k=5 익명 — 개인정보보호법 28조의2
- **DSZ 안심구역:** 국토부 훈령 1456호
