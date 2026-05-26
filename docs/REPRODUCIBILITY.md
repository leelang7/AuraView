# Reproducibility — 개발자·연구자 검증 가이드

> AuraView K-Perception 의 모든 헤드라인 숫자 (모델 성능, 임팩트, 공공데이터, 테스트) 를 **외부에서 1-step 으로 재검증** 하기 위한 가이드.
> 모든 명령은 Live (`https://auraview.allthatai.kr`) 또는 Local (`docker compose up`) 양쪽 모두에서 동일하게 작동.

---

## 1. 단일 명령 — 4축 KPI 한 응답

```bash
# 라이브
curl https://auraview.allthatai.kr/metrics/competition

# 로컬
docker compose up -d && curl http://localhost:8000/metrics/competition
```

응답에 포함:
- `model_performance.auc` = **0.9403** (Risk Transformer trained, `models/risk_transformer_trained_metric.json`)
- `model_performance.f1` = **0.9412**
- `model_performance.p99_inference_ms` = **1.04** (CPU 단일 코어, 100회 측정)
- `impact_estimate.headline_pilot_5pct.prevented_deaths_yr` = **21**
- `impact_estimate.headline_pilot_5pct.prevented_incidents_yr` = **1,694**
- `public_data_fusion.sources_total` = **25** (국내공공 23 + 보조 2) · `sources_live` / `sources_stub` / `sources_error` 카운트
- `verification.tests` = **119 passed**

> D-3 자가 진단 한 줄: `curl https://auraview.allthatai.kr/impact/submission-ready` → `ready=true, passed=9/9` 확인 (v12.144+).

---

## 2. 5개 평가 항목 자체 채점

```bash
curl https://auraview.allthatai.kr/metrics/scoreboard
```

JSON 구조: `criteria[].{criterion, score_self, evidence, endpoints[]}`

| Criterion | Score | Evidence Endpoint |
|---|---:|---|
| 공공데이터 활용 | 95 | `/fusion/sources`, `/fusion/intersection/{id}` |
| 정량적 효과 | 92 | `/impact`, `/impact/scenarios`, `/impact/top-intersections` |
| 기술 차별화 | 90 | `/occupancy/scenario`, `/collab/v2v/*`, `/risk/predict` |
| 재현성·검증 | 88 | `/healthz/details`, `/metrics/competition` |
| 한국 특화 | 93 | `/occupancy/demo?scenario=right_turn_pedestrian` (또는 school_zone) |

---

## 3. A4 1-pager PDF 자동 다운로드

```bash
# 5% pilot 시나리오
curl -O https://auraview.allthatai.kr/impact/policy-pdf

# 25% 확산 시나리오
curl -O "https://auraview.allthatai.kr/impact/policy-pdf?coverage=0.25"
```

산출물: ~88KB A4 PDF 파일. KPI 카드 4종 + 5행 시나리오표 + 25종 공공데이터 상태 + 기술 차별화 4섹션.
3-page 기획서 PDF 자동 생성 (v12.140 가로 막대 차트 포함): `curl -O https://auraview.allthatai.kr/impact/proposal-pdf` — 호출 시점 git_sha 반영.

---

## 4. 8 시나리오 voxel 데이터 검증

```bash
for s in truck_occlusion motorcycle_blindspot signal_occlusion rainy_intersection \
         right_turn_pedestrian school_zone bicycle_lane night_pedestrian; do
  echo "─── $s ─────"
  curl -s "https://auraview.allthatai.kr/occupancy/demo?scenario=$s" | python -c "
import json, sys
d = json.load(sys.stdin)
g = d.get('class_grid_flat', [])
print(f'  scenario_id: {d.get(\"scenario_id\")}')
print(f'  hotspots: {len(d.get(\"hotspots\",[]))}')
print(f'  classes: {sorted(set(g))}')
"
done
```

각 시나리오 응답에 `scenario_id`, `class_grid_flat` (40×40 voxel = 1,600 셀), `hotspots[]`, `risk_summary`, `available_scenarios` 포함.

---

## 5. 모델 성능 — 직접 재학습 (선택)

```bash
git clone https://github.com/leelang7/AuraView
cd AuraView
pip install -r requirements.txt

# 합성 데이터셋 + Transformer 학습 (CPU 약 8분, GPU 1분)
jupyter nbconvert --to notebook --execute notebooks/train_risk_transformer.ipynb \
  --output train_risk_transformer_executed.ipynb

# 결과는 models/risk_transformer_trained_metric.json 에 저장됨
cat models/risk_transformer_trained_metric.json
```

기대값:
```json
{
  "auc": 0.9403,
  "f1@0.5": 0.9412,
  "precision@0.5": 0.9441,
  "recall@0.5": 0.9384,
  "params": 67970,
  "samples": {"train": 8000, "val": 2000}
}
```

(노이즈 라벨 6% · 시드 고정으로 재현 가능. 합성 데이터셋이라 train/val 분리 + label noise 로 over-fit 방어.)

---

## 6. 추론 지연 — 직접 측정

```bash
# /risk/predict 100회 호출 → 백분위
curl https://auraview.allthatai.kr/benchmark/all
```

응답에 `risk.{p50, p99, p99_9}_ms` 등.

---

## 7. 통합 테스트 53종

```bash
git clone https://github.com/leelang7/AuraView
cd AuraView/backend
pip install -r ../requirements.txt pytest httpx
ALLOW_FALLBACK=1 SERVICE_KEY=test-stub pytest tests/ -v
```

기대 결과: `119 passed` (90 초기 + 28 fusion/fleet/v12.83 location/v12.87 speed-gate + 1 v12.150 /impact/submission-ready 회귀 보호).

---

## 8. CI / GitHub Actions

GitHub Actions 가 매 push 마다 4잡 실행:
- **Python · syntax + import smoke** — 68 pytest
- **Flutter · analyze** — Dart linter (warnings non-fatal for prototype)
- **Docs · presence check** — README, WHITEPAPER, ROADMAP, DATASETS, architecture.svg
- **Docker · build + smoke** — Dockerfile 빌드 + healthz + 8 시나리오 응답 검증

배지: ![CI](https://github.com/leelang7/AuraView/actions/workflows/ci.yml/badge.svg)

---

## 9. 데이터 출처 (모든 가정 추적 가능)

| 출처 | URL | AuraView 이용 위치 |
|---|---|---|
| TAAS 2024 통계 | https://taas.koroad.or.kr | `/impact` baseline (사고 207,535 / 사망 2,581 / 부상 290,400) |
| 도시 교차로 비중 46% | TAAS 도로종류별 분석 | `/impact` `URBAN_INTERSECTION_RATIO` |
| KOTI ITS 효과 분석 | https://koti.re.kr | 회피율 함수 `min(0.85, 0.25 × lead_time_s)` |
| 신호 API | apis.data.go.kr/B551982/rti | `/fusion/intersection/{id}` |
| VDS 실시간 소통 | data.ex.co.kr/openapi | `/fusion/intersection/{id}` |
| 한국도로공사 돌발 | data.ex.co.kr | `/fusion/intersection/{id}` |
| ITS 국가교통정보센터 | openapi.its.go.kr:9443 | `/fusion/intersection/{id}` |
| 데이터안심구역 | dta.molit.go.kr | `/dsz/verify`, school_zone 시나리오 prior |

`/fusion/sources` 응답으로 어떤 게 라이브, 어떤 게 stub fallback 인지 즉시 확인 가능.

---

## 10. 라이센스 · 데이터 사용

- 코드: MIT (https://github.com/leelang7/AuraView/blob/main/LICENSE)
- 공공데이터: 각 출처의 공공데이터 활용 약관 (대부분 CC-BY-3.0 호환)
- 학습 합성 데이터: 자체 생성 (개인정보 X, 가명결합 k=5 익명)
