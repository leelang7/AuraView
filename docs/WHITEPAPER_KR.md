# AuraView — K-Perception Platform 기술백서

> **2026년 국토교통 데이터활용 경진대회 제출용**
> 주제: 비가시 교통정보 축적·고도화 기반 지능형 안전 주행 지원 시스템
> 대상 부문: 제품·서비스 개발 (시제품) · 아이디어 부문 겸용 가능

---

## 0. 제출 URL

- 🌐 **대시보드:** https://auraview.allthatai.kr/ui
- 📱 **Fleet Mobile PWA:** https://auraview.allthatai.kr/pwa/
- 📖 **Swagger API:** https://auraview.allthatai.kr/docs
- 🔧 **Source:** https://github.com/leelang7/AuraView (branch: `feat/k-perception`)

## 1. 요약 (Executive Summary)

테슬라의 FSD가 "카메라만으로 세상을 3D로 이해"했다면, AuraView는 **"블랙박스만으로 한국 도심의 사각지대까지 이해"** 한다.

기존 ADAS가 '보이는 것'을 2D 박스로 분류하는 데 그친다면, AuraView는 **가려진 공간**을 3D 확률 점유 필드로 복원하고, **가려진 보행자·이륜차의 의도**를 시계열 예측하며, **향후 5초 이내 충돌 위험**을 end-to-end로 출력한다.

모든 추론은 **한국 공공 인프라 데이터 6종(신호 · VDS · 돌발 · TAAS · ITS · 안심구역 결합분석)** 과 융합되어 운영된다.

---

## 2. 시장·사회적 문제

| 문제 | 규모 | 기존 접근 한계 |
|---|---|---|
| 신호 가림으로 인한 교차로 사고 | 연간 교차로 사고 약 5만 건, 전체의 ~45% | 차선 이탈 경고 · 전방 추돌 경고만 탑재 |
| 배달·라스트마일 이륜 사고 | 전체 교통사고 사망자의 ~12%가 이륜 | 일반 ADAS가 이륜을 우선 대상으로 안 함 |
| 고령 보행자 횡단 사망 | 보행자 사망자의 60%+가 65세 이상 | 보행자 검출 후에만 반응 (선행 예측 없음) |
| 사각지대 사고 | 대형차 뒤 보행자 사고 다수 | 가려진 영역을 '모름'으로 처리 |

AuraView는 위 네 가지를 **"보이지 않는 공간의 확률 모델링"** 이라는 하나의 축으로 동시에 해결한다.

---

## 3. 기술 스택 ─ Tesla AI Day 오마주

### 3.1 Occupancy Network (점유 격자)
- **입력:** 단일 카메라 프레임
- **출력:** 40m × 40m × 0.5m BEV grid 위 점유 확률 [0,1]
- **핵심 차별화:** 검출된 객체 주변뿐 아니라 **"대형차 뒤쪽 영역"** 을 별도 unknown-cloud로 추가해 "보이지 않지만 있을 수 있음"을 명시적으로 확률화한다.
- 구현: `backend/app/services/occupancy.py`

### 3.2 HydraNet 멀티태스크 백본
- 단일 YOLOv8/RT-DETR 백본 → N개 head
  - vehicle · VRU · signal · lane · sign · speed
- 추론 비용 고정, 정보량 6~8배
- 구현: `backend/app/services/hydranet.py`
- 학습: `notebooks/train_hydranet.ipynb` (AIHub · Cityscapes · Roboflow K-LISA 혼합)

### 3.3 End-to-End Risk Transformer
- 입력: hydranet features + occupancy flat + 신호·VDS·TAAS·GPS·duration
- 출력: P(collision) · P(near-miss) · feature attention
- 학습 라벨: 사후 급감속(|a|≥0.4g)·에어백 전개·TAAS 사고 발생
- 초기 구현은 linear-logistic 경량판(해석성 확보) → 학습 완료 후 Transformer 교체
- 구현: `backend/app/services/risk_transformer.py`

### 3.4 Intent Prediction (가려진 agent)
- MotionLM-lite 경량 시계열 예측
- 보행자 횡단 확률 · 이륜 접근 확률 · time horizon 3s
- 구현: `backend/app/services/intent.py`

### 3.5 Fleet Learning (Shadow Mode)
- 엣지 단말이 **model confidence entropy ≥ 0.6** 인 하드샘플만 자동 업로드
- 얼굴 · 번호판 블러 후 저장 (OpenCV Haar → 추후 YOLOv8-LPD)
- 주 1회 자동 재학습 → OTA 배포
- 구현: `backend/app/routers/fleet.py`, `services/pii.py`

### 3.6 BEV 3D 대시보드 (FSD UI 오마주)
- Leaflet 2D heatmap + **Three.js 3D voxel** 토글
- `grid_flat` 응답을 받아 점유 확률을 voxel 높이·색으로 렌더
- 자동 궤도 카메라, ego car 인디케이터
- 구현: `backend/app/main.py` TAB ② (`setOccMode('3d')`)

### 3.6b 모바일 Fleet PWA (엣지 단말)
- `/pwa` 경로에서 설치 가능 (대시보드 TAB ④에 QR 노출)
- 카메라 → 4초 주기 프레임 캡처 → 간이 엔트로피 추정 → 임계 이상만 업로드
- 서비스 워커로 오프라인 캐시, 설치형 앱처럼 동작
- 위치·디바이스ID는 **가명화·반올림** 후 서버 전송
- 구현: `frontend_pwa/` + `routers/fleet.py`

### 3.6c Accident Reenactment Studio
- 블랙박스 영상 → 프레임마다 HydraNet · Occupancy · Risk 추론 → HUD 오버레이 mp4 출력
- 합성 시나리오 3종 (`crosswalk_truck`, `motorcycle_blindspot`, `signal_occluded`) 으로 **영상 없이도** 데모 가능
- `lead_time_s` 자동 계산 → "AuraView였다면 N초 먼저 경고" 카피 자동 생성
- 구현: `services/scenario.py` + `routers/scenario.py` + TAB ⑥

### 3.7 C-ITS / V2X 연동 (한국 특화 킬러카드)
- 한국도로공사 C-ITS 인프라 메시지(SPaT/MAP)와 AuraView 비전 추론을 교차 검증
- 비전이 "신호 불확실"이라고 판정해도 인프라 메시지가 "stop" 이면 STOP 채택
- 구현: 어댑터 `services/public_api.py` — 향후 DATEX-II wrapper 추가

---

## 4. 가점 25점 매트릭스

| 항목 | 배점 | AuraView 증빙 | 엔드포인트 / 파일 |
|---|---:|---|---|
| AI 활용 · 학습 | 5 | HydraNet · Risk Transformer · Intent Predictor 학습 파이프라인 | `notebooks/`, `services/risk_transformer.py` |
| AI 활용 · 분석 | 5 | Occupancy BEV 추정 · 위험 확률 추론 · attention 해석 | `POST /occupancy/infer`, 대시보드 TAB② |
| 데이터 융합 | 5 | 신호 · VDS · 돌발 · TAAS · ITS · DSZ 6종 어댑터 통합 | `GET /fusion/intersection/{id}` |
| 가명정보 결합 | 5 | HMAC 가명화 · k-익명성 · 얼굴·번호판 블러 · TAAS×VDS 결합 | `services/pii.py`, `POST /dsz/join/taas-vds` |
| 안심구역 | 5 | `dsz.ex.co.kr` 반입 → 결합분석 → 해시 검증 반출 기록 | `services/dsz_adapter.py`, `POST /dsz/verify` |

**합계 25점** — 가점 상한선 정조준.

---

## 5. 시스템 아키텍처

```
┌────────────────────── Edge ─────────────────────┐
│ 블랙박스 / 모바일 / HUD                            │
│   └─ HydraNet (멀티태스크)                         │
│         └─ Occupancy BEV (40×40m × 0.5m)         │
│               └─ Intent Predictor (MotionLM-lite) │
│                     └─ E2E Risk Transformer       │
│                           └─ HUD / 음성 / 진동     │
└────────────────────────┬────────────────────────┘
                          │  hard-sample (PII 마스킹)
                          ▼
┌────────────────────── Cloud ────────────────────┐
│ FastAPI + SQLite(→ PostgreSQL) + Ultralytics    │
│   ├─ /fusion  (6종 공공 API 어댑터)                │
│   ├─ /occupancy  (서버 추론 / 시연)                │
│   ├─ /fleet  (하드샘플 기여 & 통계)                 │
│   ├─ /dsz  (안심구역 반입/검증/결합)                │
│   └─ Dojo-lite: GitHub Actions + DVC            │
│        → 주간 재학습 → 회귀 시나리오 통과 → OTA 배포  │
└─────────────────────────────────────────────────┘
```

---

## 6. 데이터 파이프라인

### 6.1 6종 공공데이터

| # | 출처 | 내용 | 사용 위치 |
|---|---|---|---|
| 1 | 교통안전공단 실시간 신호 (`apis.data.go.kr/B551982/rti`) | 신호 상태·잔여시간 | HUD 복원 · Risk feature |
| 2 | 한국도로공사 VDS (`data.ex.co.kr`) | 속도·교통량·점유율 | Risk feature · 가명결합 |
| 3 | 한국도로공사 돌발상황 | 사고·낙하물·통제 | Risk · 지도 경고 |
| 4 | TAAS 사고이력 | 사고 위치·유형·피해자 | Intent prior · 가명결합 |
| 5 | ITS 국가교통정보센터 | 링크 단위 속도·소요시간 | BEV 정규화 |
| 6 | 국토교통 데이터안심구역 | 반입·결합·반출 요약결과 | 리포트·지자체 제안 |

### 6.2 가명결합 프로세스

1. 원천 데이터는 안심구역 내부로만 반입.
2. 결합키는 준식별자(시군구코드 × 일자·시간 bucket × 링크ID)만 사용.
3. k-익명성 `k=5` 미만 그룹 제거 (`services/pii.py`).
4. 반출은 **집계·분포 통계**만 허용, SHA-256 해시로 변조 여부 검증 (`services/dsz_adapter.py`).

---

## 7. 성능 · 평가 지표 (계획)

| 지표 | 목표 | 측정 방법 |
|---|---|---|
| 신호 가림 감지 F1 | ≥ 0.88 | 자체 라벨링 500장 + AIHub |
| BEV 점유 IoU (BEV, 3m bin) | ≥ 0.60 | nuScenes-lite subset |
| 위험 경고 선행 시간 | ≥ 2.5s | TAAS 사고 영상 재현 |
| 경고 False Positive / 1h 주행 | ≤ 3건 | 서울 시내 시범 주행 |
| 엣지 추론 지연 | ≤ 120ms (GPU) / 300ms (CPU) | yolov8n + occupancy |

---

## 8. 사회적 가치

- **고령 보행자:** Intent Predictor가 횡단 확률을 2초 전 알려 신호 연장 권고를 운영센터에 자동 송신 (opt-in).
- **이륜 배달 노동자:** 사각지대 접근 확률을 운전자에게 표시 → 이륜 사고율 30% 감소 목표.
- **지자체 데이터 행정:** 안심구역 결합분석 결과(Top-20 위험 교차로)를 월간 리포트로 제공.
- **오픈소스:** 핵심 모듈은 MIT로 공개, 모델 가중치는 비상업 연구 라이선스.

---

## 9. 비즈니스 확장

1. **B2C:** 모바일 앱 / HUD 액세서리 (Shadow mode 자동 기여)
2. **B2B:** 물류·택배 이륜 관제, 지자체 위험구간 리포트 SaaS
3. **B2G:** 한국도로공사 C-ITS · 신호운영센터와의 공동 실증

---

## 10. 제출 체크리스트

- [x] 기술백서 (본 문서)
- [x] 가점 25점 매트릭스
- [x] 6종 공공데이터 어댑터
- [x] Occupancy · HydraNet · Risk · Intent 서비스 코드
- [x] 가명결합 · 안심구역 반입/검증
- [x] Fleet Learning contribute 엔드포인트
- [ ] 학습 노트북 실행 결과 (1주 내)
- [ ] 사고 재현 데모 영상 2분 (3주 내)
- [ ] 발표 슬라이드 (4주 내)

---

## 11. 참고

- Tesla AI Day 2022 — Occupancy Networks · HydraNet · End-to-End
- Waymo MotionLM (2023) · WayFormer (2022)
- nuScenes / KITTI BEV 평가 방식
- AIHub "도로장애물·돌발상황" 데이터셋
- 국가교통 데이터 오픈마켓 (`bigdata-transportation.kr`)
- 국토교통 데이터안심구역 (`dsz.ex.co.kr`)
