# AuraView

> **K-Perception Platform — 블랙박스 한 대로 사각지대까지 계산한다.**
> Tesla-style occupancy · fleet-learning · end-to-end risk prediction을 한국 도심 교차로에 이식한 안전 주행 지원 시스템.

비가시 신호·점유 공간·가려진 보행자 의도까지 **확률 필드로 추정**해 즉시 HUD에 경고합니다.
영상만 있으면 신호 · 차량 · 보행자 · 점유 공간 · 충돌 위험을 **단일 백본에서 동시 예측**합니다.

---

## 🎯 Positioning

| 구분 | 기존 블랙박스·ADAS | **AuraView K-Perception** |
|---|---|---|
| 출력 | 2D 박스 | **3D Occupancy 확률 필드** |
| 추론 | 객체 단위 rule | **End-to-End Risk Transformer** |
| 데이터 | 단일 API | **6종 공공데이터 융합** (신호·VDS·돌발·TAAS·ITS·안심구역) |
| 학습 | 고정 모델 | **Fleet Learning 플라이휠** (하드샘플 자동 수집) |
| 대상 | 운전자 | **운전자 + 고령·장애 보행자 + 이륜 배달 노동자** |

---

## 🏆 2026 국토교통 데이터활용 경진대회 — 가점 25점 정조준

| 가점 항목 | 배점 | AuraView의 충족 방식 |
|---|---:|---|
| **AI활용 — 학습** | 5 | HydraNet 멀티태스크 / E2E Risk Transformer / Intent Predictor 직접 학습 |
| **AI활용 — 분석** | 5 | Occupancy Network 추론 + BEV 3D 위험 분석 대시보드 |
| **데이터융합** | 5 | 신호 + VDS + 돌발 + TAAS + ITS + 지오코딩의 교차 융합 |
| **가명정보결합** | 5 | 사고이력(TAAS) × 교통량(VDS)을 가명처리 후 교차로 단위 결합 |
| **안심구역** | 5 | 국토교통 데이터안심구역(`dsz.ex.co.kr`) 반입 → 결과물 반출 파이프라인 |

→ [docs/WHITEPAPER_KR.md](docs/WHITEPAPER_KR.md) · [docs/DATASETS.md](docs/DATASETS.md) · [docs/ROADMAP.md](docs/ROADMAP.md)

---

## 🧠 Tesla-Style 기술 스택

1. **Occupancy Network** — 교차로 전방 공간을 3D voxel로 확률 점유 추정 → "앞 트럭 뒤에 무엇이 있을 확률"
2. **HydraNet 멀티태스크 백본** — 단일 백본에서 신호·차량·보행자·차선·속도·표지 동시 추론
3. **End-to-End Risk Transformer** — 영상 + 신호 API + GPS + 궤적을 한 모델에서 향후 5초 위험 확률 출력
4. **Intent Prediction** — 가려진 보행자·이륜차의 경로 분포를 MotionLM-lite로 예측
5. **Fleet Learning (Shadow Mode)** — 엣지 단말(PWA)이 "어려운 장면"만 자동 업로드 → 플라이휠 재학습
6. **BEV 3D Dashboard** — Three.js로 점유 격자를 voxel로 실시간 시각화 (FSD UI 오마주, 2D/3D 토글)
7. **Accident Reenactment** — 블랙박스 영상 혹은 합성 시나리오로 **"AuraView였다면 N초 먼저 경고"** 영상 자동 생성
8. **C-ITS / V2X 브릿지** — 인프라 신호와 비전 결과의 신뢰도 교차 검증 (한국도로공사 접점)

---

## 📐 Pipeline

```
┌──────────── Edge (차량·블랙박스) ────────────┐   ┌────────── Cloud ──────────┐
│                                              │   │                           │
│  영상 ─► HydraNet ─► Occupancy ─┐            │   │  Fleet 하드샘플 수집       │
│                                 ├─► E2E Risk │   │  → 가명처리 → 재학습        │
│  Intent Predictor ──────────────┘            │──►│  → OTA 배포                │
│                                              │   │                           │
│  ◄──── HUD 경고 + BEV 오버레이 ────           │   │  안심구역 내 결합분석       │
│                                              │   │  (TAAS × VDS)             │
└──────────────────────────────────────────────┘   └───────────────────────────┘
```

---

## 📦 Project Structure

```
AuraView/
├── backend/app/
│   ├── main.py              # FastAPI + 6탭 대시보드 + Three.js BEV 3D
│   ├── config.py · database.py · models.py · schemas.py
│   ├── routers/
│   │   ├── detect.py · events.py · risk.py · signals.py · intersections.py
│   │   ├── occupancy.py     # ★ Occupancy 추론
│   │   ├── fleet.py         # ★ Fleet Learning /contribute
│   │   ├── fusion.py        # ★ 6종 공공데이터 융합
│   │   ├── dsz.py           # ★ 안심구역 반입·검증
│   │   └── scenario.py      # ★ 사고 재현 영상 생성
│   └── services/
│       ├── detector.py · matching.py · scoring.py · public_api.py
│       ├── hydranet.py       # ★ 멀티태스크 백본
│       ├── occupancy.py      # ★ 3D Occupancy 추정
│       ├── risk_transformer.py # ★ E2E 위험 예측
│       ├── intent.py         # ★ Occluded agent intent
│       ├── pii.py            # ★ 가명처리·k-익명성
│       ├── dsz_adapter.py    # ★ 안심구역 반입 감사로그
│       └── scenario.py       # ★ 사고 재현 · 합성 시나리오 3종
├── frontend_pwa/            # ★ 모바일 Fleet PWA
│   ├── index.html · app.js · service-worker.js
│   ├── manifest.webmanifest · icon.svg
├── notebooks/
│   ├── train_hydranet.ipynb
│   ├── train_risk_transformer.ipynb
│   └── accident_reenactment.ipynb  # ★ 재현 영상 노트북
├── docs/
│   ├── WHITEPAPER_KR.md · ROADMAP.md · DATASETS.md
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🔌 API Endpoints

| Method | Path | Description | 가점 기여 |
|---|---|---|---|
| `GET`  | `/ui` | 대시보드 (탭 6개) | 분석 |
| `GET`  | `/pwa` | ★ **모바일 Fleet PWA** (카메라·QR 설치) | 학습 |
| `POST` | `/detect/frame` | 이미지 위험 분석 | 분석 |
| `POST` | `/detect/video` | 영상 위험 분석 | 분석 |
| `POST` | `/occupancy/infer` | ★ Occupancy 3D 추정 (grid_flat 포함) | 학습·분석 |
| `GET`  | `/occupancy/demo` | ★ 데모 격자 (2D/3D 뷰어용) | 분석 |
| `POST` | `/fleet/contribute` | ★ 하드샘플 업로드 (PII 자동 마스킹) | 가명·학습 |
| `GET`  | `/fleet/stats` | Fleet 기여 통계 | — |
| `GET`  | `/fusion/intersection/{id}` | ★ 6종 데이터 융합 조회 | 융합 |
| `POST` | `/dsz/verify` · `/dsz/join/taas-vds` | ★ 안심구역 결합/검증 | 안심·가명 |
| `POST` | `/scenario/reenact` | ★ **사고 재현 2분 영상 생성** | 분석 |
| `GET`  | `/scenario/list` · `/scenario/presets` | 재현 영상 관리 | — |
| `GET`  | `/events/` · `/risk/` · `/signals/{id}` · `/intersections/` | 기본 CRUD | — |

---

## 🚀 Quickstart

```bash
# 1) 의존성
pip install -r requirements.txt

# 2) 환경변수
cp .env.example .env
# → .env 파일에 SERVICE_KEY 등 실제 값 입력

# 3) 실행
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

대시보드: `http://localhost:8000/ui`

---

## 💡 Use Cases

- **신호 가림** — 대형차 뒤 신호 상태를 Occupancy + 신호 API로 복원 → HUD에 표시
- **가려진 보행자** — Intent Predictor가 횡단 확률 2초 전 예측 → 감속 경고
- **사각지대 이륜차** — 배달 오토바이 접근 확률을 BEV occupancy로 표시
- **지자체 리포트** — 안심구역 결합분석으로 "사고 ↔ 교통량 ↔ 신호" 상관관계 기반 개선 제안

---

## 🗺️ Roadmap (2026-04 ~ 2026-05)

- [ ] Week 1 — Occupancy PoC + HydraNet skeleton
- [ ] Week 2 — 6종 데이터 어댑터 + 가명결합 + E2E Risk Transformer 학습
- [ ] Week 3 — BEV 3D viewer + Fleet contribute + 안심구역 반출 리포트
- [ ] Week 4 — 사고 재현 데모 영상 2분 + 발표자료 + 기술백서

상세 → [docs/ROADMAP.md](docs/ROADMAP.md)

---

> **보이지 않는 정보를 데이터화하고, 보이지 않는 공간을 계산하여, 미래 위험을 예측한다.**
