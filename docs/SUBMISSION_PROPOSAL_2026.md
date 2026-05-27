# AuraView K-Perception · 2026 제출 기획서 (초안)

> **마감**: 2026-05-29 (D-2) · **출품자**: ThinkU Team / leelang7
> **라이브 시스템**: <https://auraview.allthatai.kr>
> **저장소**: <https://github.com/leelang7/AuraView> (MIT)
> **자가 진단 (단일 URL)**: <https://auraview.allthatai.kr/impact/submission-ready> → `ready=true, passed=9/9`

---

## 0. 한 줄 요약

> **블랙박스 한 대로 사각지대까지 계산해 사고를 평균 3.38초 먼저 경고하는 한국 도로 안전 AI.**
> Tesla FSD 의 Occupancy + Fleet Learning 에 **한국 도로 협업 인지 (V2V + Bus-Aware + Bidirectional)** 와 **25종 공공데이터 실시간 융합** (`fusion.v11-2026.05.25-25src`) 을 결합.

---

## 1. 문제 정의

한국 도로의 사망/중상 사고는 **TAAS 2024 기준 연 사망 2,581명 / 부상 290,400명**.
일반 ADAS 의 한계:

- 카메라 시점 한 곳만 봄 → 트럭/버스에 가려진 신호등·보행자 못 봄 (occlusion)
- 사전 경고 lead time 0.5~1초 (회피 가능률 25% 이하)
- 한국 특수 환경 (스쿨존·민식이법, 우회전 보행, 마주오는 차로, 119 골든타임) 미반영
- 공공데이터 (TAAS 사고이력·VDS·KMA·DSZ) 와 실시간 융합 부재

---

## 2. 솔루션 개요

### 2.1 핵심 아이디어

**Tesla FSD 영감** 의 occupancy/fleet learning 위에 **한국이 가진 공공 인프라 데이터 25종** 을 실시간 융합하여, 단일 차량의 시야 한계를 사회 전체 시야로 확장.

```
[블랙박스 카메라 1대]
        │
        ▼
[Risk Transformer · AUC 0.9403] ←─── [25종 공공데이터 실시간 융합]
        │                                  ├─ 국내공공 23종 (정부/공공기관 공식 API)
        ▼                                  │   신호·VDS·돌발·TAAS·ITS·DSZ·KMA·
[위치/속도 게이트 검증]                       │   119·DTG·KOTSA·환경부·경찰청·국토부
        │                                  └─ 보조 2종 (글로벌 오픈)
        ▼                                      USGS 지진 · OSM 철도건널목
[3.38s 선행 경고 + V2V broadcast]
        │
        ▼
[정책 환원: 위험 교차로 Top-N 리포트 + DSZ 안심구역 결합]
```

### 2.2 한국 차별점 5종 (Tesla 가 다루지 못함)

| 카테고리 | Tesla | AuraView |
|---|---|---|
| 차량 간 협업 인지 | 자기 차 시점만 | **V2V Cross-Vehicle** (heading 130°+ 가중 0.95) |
| 정류장 prior | generic 보행자 | **Bus-Aware** (dwelling/passing → +0.55 boost) |
| 마주오는 차로 | 단방향 | **Bidirectional Lane** + VDS 비대칭 분석 |
| 공공 신호 결합 | vision only | **신호 API + ITS** 직접 호출 결합 |
| 정책 환원 | Tesla 내부 데이터 | **위험 Top-N 자동 리포트 + DSZ 결합** |

---

## 3. 정량 임팩트 (TAAS 2024 baseline · lead=3.38s)

| 도입 비율 | 사고 예방/년 | 사망 감소 | 부상 감소 |
|---|---:|---:|---:|
| **Pilot 5%** | **1,694건** | **21명** | **2,370명** |
| 확산 25% | 8,470건 | 105명 | 11,852명 |
| 전국 100% | 33,880건 | 421명 | 47,408명 |

**산출 공식**: `prev_events = TAAS_annual × urban_intersection_ratio (46%) × scenario_overlap (42%) × min(0.85, 0.25 × lead_time_s) × coverage`
**라이브 검증**: <https://auraview.allthatai.kr/impact?lead=3.38&coverage=0.05>

**위험 교차로 Top-10 (서울)** 만 도입 → 연 사망·중상 **85명 예방**
강남역 11.8 / 잠실역 10.1 / 광화문 9.3 / 신촌 8.4 / ...
<https://auraview.allthatai.kr/impact/top-intersections>

---

## 4. 평가 항목별 25점 매핑

| 평가 항목 | 점수 | 핵심 증빙 | 라이브 URL |
|---|:---:|---|---|
| **AI 학습** | 5점 | PyTorch Transformer 실 학습 · AUC 0.9403 · F1 0.9412 · 10,000 train · 15 epoch | [`/ai/model-card`](https://auraview.allthatai.kr/ai/model-card) |
| **AI 분석** | 5점 | 4 시나리오 분류 · Attention 피처 중요도 · ROC 50pt · 혼동행렬 · p99 1.04ms | [`/ai/scenario-analysis`](https://auraview.allthatai.kr/ai/scenario-analysis) |
| **데이터 융합** | 5점 | **25종** (국내공공 23 + 보조 2) 실시간 융합 · 12종 no-key 라이브 | [`/fusion/sources`](https://auraview.allthatai.kr/fusion/sources) |
| **가명정보 결합** | 5점 | HMAC-SHA256 가명화 + k≥5 익명 + TAAS×VDS 결합 전 과정 | [`/privacy/pipeline-spec`](https://auraview.allthatai.kr/privacy/pipeline-spec) |
| **안심구역 (DSZ)** | 5점 | dsz.ex.co.kr 반입→결합→반출 + SHA-256 해시 검증 + 감사 로그 | [`/dsz/pipeline-report`](https://auraview.allthatai.kr/dsz/pipeline-report) |
| **합계** | **25점** | | |

---

## 5. 25종 공공데이터 융합 (v11)

### 국내공공 23종 (정부/공공기관 공식 API)

신호 (도로교통공단) · VDS / 돌발 / 노면 RWIS (한국도로공사) · TAAS 사고이력 / 보행자다발 (도로교통공단) · ITS (국토부) · DSZ 안심구역 (국토부) · KMA 동네예보 / 결빙 (기상청) · E-Gen 응급실 / 119 출동 (보건복지부·소방청) · 따릉이 (서울시) · 스쿨존 / 횡단보도 (vworld 국토부) · 통학로 (도로교통공단) · PM10·PM2.5 / EV 충전소 (환경부·환경공단) · KOTSA 검사·DTG·V2X 허브 · 행안부 도로 노후도 · 경찰청 단속 CCTV

### 보조 2종 (글로벌 오픈, no-key)

USGS 실시간 지진 (M2.0+) · OSM 철도 건널목 (`railway=level_crossing`)

**라이브 freshness 검증**: <https://auraview.allthatai.kr/fusion/sources> (`mode`: live/stub, `age_s` 노출)

---

## 6. 8 시나리오 × 도로교통법 매핑

| 시나리오 | 도로교통법 | 대법원 판례 | AuraView prior |
|---|---|---|---|
| 트럭 가림 | 27조 (보행자 보호) | 2019도11622 | occlusion shadow +0.55 |
| 좌측 사각 이륜 | 19조의2 | 2019도14517 | BEV 사각 sweep |
| 신호 가림 | 5조 | 2020도11458 | 신호 API + V2V |
| 우천 교차로 | 19조 + 시행규칙 | 2017도9534 | 환경 가중 +0.45 |
| 우회전 보행자 | 25조 4항 | **2022도10752** | 회전 sweep zone |
| 스쿨존 | 12조 + **민식이법** | 헌재 2019헌마927 | DSZ +0.62 (등하교) |
| 자전거 | 13조 + 자전거이용활성화법 | 2021도8395 | 자전거 GIS prior +0.40 |
| 야간 | 48조 | 2018도12521 | V2V 헤드라이트 share |

전 항목 `/policy/laws` 에서 국가법령정보센터 URL + 정량 기여 명시.

---

## 7. 검증 · 재현 (1-step)

### 7.1 단일 URL 자가 진단 (D-2 신규)

```bash
curl https://auraview.allthatai.kr/impact/submission-ready
```

응답: `{ ready: true, passed: 9/9, blockers: [], deadline: "2026-05-29" }`
9 게이트: `sources_25` · `schema_v11` · `proposal_pdf_ok` · `manifest_ok` · `model_weights` · `git_sha` · `license_present` · `banned_words_zero` · `korean_font_hint`

### 7.2 라이브 시스템 헬스

```bash
curl https://auraview.allthatai.kr/metrics/audit
```

포함: data_sources 25 + live_ids · fleet_events verified_pct · score25_gates · tests_passing 119

### 7.3 즉석 기획서 PDF (호출 시점 git_sha 반영)

```bash
curl -O https://auraview.allthatai.kr/impact/proposal-pdf
```

A4 3-page · Page 1 가로 막대 차트 (예방 건수 시각화) · Page 2 25 sources 카테고리 + 8 시나리오 + Tesla 차별화 · Page 3 검증 URL 인덱스 + 재현 가이드 + 라이센스

### 7.4 로컬 재현

```bash
git clone https://github.com/leelang7/AuraView
cd AuraView
docker compose up -d
# 또는
python -m pytest backend/tests/  # 119 / 119 PASS
```

---

## 8. 시스템 헬스 (호출 시점)

| 항목 | 값 |
|---|---|
| 라이브 자가 진단 | `ready=true, 9/9 PASS` |
| 데이터 소스 | 25 (국내공공 23 + 보조 2) |
| Schema | `fusion.v11-2026.05.25-25src` |
| Risk Transformer | AUC 0.9403 · F1 0.9412 · p99 1.04ms |
| 테스트 | 119 / 119 PASS |
| API 엔드포인트 | 149+ |
| Native APK | v12.170 (Galaxy Z Fold 3 검증) |
| GitHub | <https://github.com/leelang7/AuraView> (MIT) |

---

## 9. 정직성 노출 (Honesty)

본 프로젝트의 한계와 제약을 외부에서 직접 검증할 수 있도록 라이브 응답에 명시:

- `fleet_events.honesty_note`: verified_pct 가 부풀려진 100% → 정직한 ~43% (v12.92 backfill)
- `fusion.v11-2026.05.25-25src` 카테고리 분리: 국내공공 23 (주력) + 보조 2 (no-key fallback)
- `korean_font_hint`: Render 배포 환경에서 Noto Sans KR 미설치 시 PDF 한글 폰트 fallback 안내
- **Native 앱 BEV 시각화 (object footprint + 실루엣)**: ML Kit base ObjectDetector 의 generic 카테고리 한계로 정확한 차량/사람 semantic 분류 불가. 따라서 v12.169 부터 거짓 분류 라벨 제거하고 ML Kit 원본 카테고리 (e.g. `Home goods 67%`) 만 노출. **정확한 객체 분류는 TFLite COCO-SSD 같은 별도 모델 임베드 (~10MB) 가 필요** — 향후 작업.

---

## 10. 라이센스 · 컴플라이언스

- **코드**: MIT — <https://github.com/leelang7/AuraView/blob/main/LICENSE>
- **공공데이터**: 각 출처 약관 준수 (대부분 CC-BY-3.0 호환) — `/metrics/data-attribution`
- **PII (얼굴/번호판)**: 자동 마스킹 → **개인정보보호법 3조**
- **가명결합 k≥5**: **개인정보보호법 28조의2** (가명정보 처리)
- **DSZ 안심구역**: **국토부 훈령 1456호** 절차 준수 (반입→결합→반출 SHA-256 검증)

---

## 11. 핵심 라이브 URL (제출 함께 제출)

| 자료 | URL |
|---|---|
| **즉석 기획서 PDF** | <https://auraview.allthatai.kr/impact/proposal-pdf> |
| **자가 진단 (9 게이트)** | <https://auraview.allthatai.kr/impact/submission-ready> |
| 라이브 시스템 헬스 | <https://auraview.allthatai.kr/metrics/audit> |
| 25 소스 카탈로그 | <https://auraview.allthatai.kr/fusion/sources> |
| 종합 스코어카드 | <https://auraview.allthatai.kr/scorecard/> |
| 위험 교차로 Top-N | <https://auraview.allthatai.kr/impact/top-intersections> |
| 30초 일반인 스토리 | <https://auraview.allthatai.kr/story/> |
| GitHub (MIT) | <https://github.com/leelang7/AuraView> |
| Native APK v12.170 | (별도 첨부: `auraview_fleet/build/app/outputs/flutter-apk/app-release.apk` 56MB) |

---

## 12. 제출 전 체크리스트

- [x] LICENSE 파일 존재 (MIT + 공공데이터 컴플라이언스 명시)
- [x] 119 / 119 pytest PASS
- [x] 라이브 시스템 `ready=true, 9/9 PASS`
- [x] 즉석 PDF 자동 생성 (호출 시점 git_sha 반영, 154KB Noto 환경 / 53KB Render)
- [x] 외부 노출 자산 '공모전/심사/가점' 등 금지 단어 0건
- [x] 25 sources `fusion.v11-2026.05.25-25src` 전 site 일관성
- [x] Native APK v12.170 빌드 (Galaxy Z Fold 3 검증)
- [ ] **제출 시스템 업로드** (PDF + GitHub URL + 라이브 URL)
- [ ] (선택) `auraview_submission_YYYYMMDD.zip` 번들 동봉 (`scripts/build_submission_bundle.py`)

---

> 본 문서는 호출 시점 라이브 상태 (`git_sha`, `tests_passing`, `data_sources.live_count`) 와 동기화됩니다.
> 평가자가 어느 시점에 검증해도 동일한 진실 (또는 정직한 honesty_note) 응답을 받도록 설계.
