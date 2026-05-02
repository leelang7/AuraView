# AuraView

> **K-Perception Platform — 블랙박스 한 대로 사각지대까지 계산한다.**
> Tesla-style occupancy · fleet-learning · end-to-end risk prediction 에 **Tesla 도 못 하는 한국 도로 협업 인지(V2V + Bus + Bidirectional)** 까지 결합한 안전 주행 지원 시스템.

### 🌐 Live

- **Dashboard:** https://auraview.allthatai.kr/ui ← 9탭 풀 데모
- **Mobile App (Flutter / PWA):** https://auraview.allthatai.kr/pwa/
- **Slides (Reveal.js 발표):** https://auraview.allthatai.kr/slides/
- **Kiosk (무인 자동 시연):** https://auraview.allthatai.kr/kiosk/
- **API Docs (Swagger):** https://auraview.allthatai.kr/docs
- **Brand portfolio:** https://allthatai.kr

> 본 리포 **monorepo** : 백엔드 · Flutter · 랜딩 · 슬라이드 · 키오스크 · 학습 노트북 · 문서 모두 한 곳.

---

## 🎯 Positioning — Tesla FSD 만으로는 부족하다

| 구분 | 기존 ADAS / Tesla FSD | **AuraView K-Perception** |
|---|---|---|
| 출력 | 2D 박스 / 자기 카메라 BEV | **3D Occupancy + V2V 결합 BEV** |
| 사각지대 | "모름" 처리 | **마주오는 차의 시점**으로 메움 |
| 추론 | rule + 단일 모델 | **End-to-End Risk Transformer** |
| 데이터 | 단일 소스 | **6종 공공데이터 + V2V 풀 + 정류장 prior** |
| 학습 | 고정 모델 | **Fleet Learning 플라이휠** + 자동 재학습 |
| 대상 | 운전자 | **운전자 + 보행자 + 이륜 노동자 + 지자체 + K-MaaS 운영자** |

---

## 🏆 2026 국토교통 데이터활용 경진대회 — 가점 25점 + K-MaaS 특별상

| 가점 항목 | 배점 | 충족 방식 | 엔드포인트 |
|---|---:|---|---|
| **AI 활용 — 학습** | 5 | HydraNet · Risk Transformer · Intent Predictor + Fleet 데이터 (AUC **0.94**) | `/fleet/contribute`, `notebooks/risk_transformer_metric.py` |
| **AI 활용 — 분석** | 5 | Occupancy 3D · BEV viewer · 사고 재현 영상 · 합본 Showreel | `/occupancy/infer`, `/scenario/reenact`, `/showreel/build` |
| **데이터 융합** | 5 | 신호 · VDS · 돌발 · TAAS · ITS · 안심구역 6종 한 응답 결합 | `/fusion/intersection/{id}` |
| **가명정보 결합** | 5 | HMAC 가명화 · k=5 익명성 · 얼굴/번호판 블러 · TAAS×VDS 결합 | `/dsz/join/taas-vds`, `/fleet/contribute` |
| **안심구역** | 5 | 반입·결합분석·해시 검증 반출 + Top-N 정책 리포트 | `/dsz/verify`, `/reports/generate` |
| **⭐ K-MaaS 특별상** | +300만원 | 위험 교차로 → 대중교통 우회 추천 + 노선 운영팀 환원 | `/kmaas/alternatives`, `/kmaas/operator-report` |

→ [docs/WHITEPAPER_KR.md](docs/WHITEPAPER_KR.md) · [docs/DATASETS.md](docs/DATASETS.md) · [docs/ROADMAP.md](docs/ROADMAP.md)

---

## 🧠 Tesla-Style 8 + 한국 특화 협업 인지 3

### Tesla AI Day 식 8종
1. **Occupancy Network** — 40m × 40m × 0.5m BEV voxel 점유 확률
2. **HydraNet 멀티태스크 백본** — 신호·차량·VRU·차선·표지 동시
3. **End-to-End Risk Transformer** — 영상+신호+GPS → 5초 충돌 확률
4. **Intent Prediction** — 가려진 보행자/이륜 경로 분포
5. **Fleet Learning (Shadow Mode)** — 어려운 장면만 자동 업로드
6. **BEV 3D Dashboard** — Three.js voxel 실시간 (FSD UI)
7. **Accident Reenactment** — "AuraView 였다면 N초 먼저"
8. **C-ITS / V2X 브릿지** — 인프라 신호와 비전 교차 검증

### ⭐ Tesla 도 못 하는 한국 특화 3종 — Collaborative Perception
9. **V2V Cross-Vehicle Perception** — **마주오는 차의 시점**을 내 BEV 에 머지 → "버스 너머 보행자" 직격 (`services/v2v.py`)
10. **Bus-Aware Pedestrian Prior** — 정류장 데이터 + 버스 정차/출발 상태 → 보행자 prior **+0.55** boost (`services/bus_aware.py`)
11. **Bidirectional Lane Fusion** — 마주오는 차들의 감속 비율 + VDS 상행/하행 비대칭 → 사고 즉시 감지 + 권장속도 (`services/bidirectional.py`)

---

## 📊 측정 결과 (백서 §7)

| 지표 | 측정값 | 출처 |
|---|---:|---|
| Risk Transformer **AUC** | **0.938** | `models/risk_transformer_metric.json` |
| F1 @ 0.5 | 0.905 | 상동 (n=1000, 라벨 노이즈 6%) |
| 사고 재현 영상 평균 **선행 경고 시간** | **5.72s** | 합성 시나리오 3종 |
| 협업 인지 lift (단독 vs Fused) | **+10~31%p** | TAB ⑨ 실시간 시연 |
| 통합 테스트 | **18 / 18 PASS** | `backend/tests/` |

---

## 📐 Pipeline (협업 인지 포함)

```
┌──────────── Edge (차량·블랙박스·Flutter 앱) ────────────┐
│ 영상 → HydraNet → Local Occupancy → Intent → E2E Risk │
└─────────────┬────────────────────────────────┬─────────┘
              │ V2V 메시지 broadcast            │ HUD 경고
              ▼                                 ▲
┌──────────── Cloud (auraview.allthatai.kr) ─────────────┐
│  V2V 풀 (교차로별)  ─┐                                  │
│  버스 정류장 DB    ──┼─► /collab/fused-occupancy        │
│  VDS 상행/하행     ──┘    → 단독(local) vs 협업(fused)  │
│                                                         │
│  Fleet 하드샘플 ─► PII 마스킹 ─► 자동 재학습 ─► OTA      │
│  TAAS × VDS 안심구역 결합분석 ─► Top-N 정책 리포트       │
│  K-MaaS 운영팀 환원 ◄─► 시민용 우회 경로 추천            │
└────────────────────────────────────────────────────────┘
```

---

## 📦 Monorepo 구조

```
github.com/leelang7/AuraView (feat/k-perception)
├── backend/                    FastAPI + 9 라우터 + 18 pytest
│   └── app/
│       ├── routers/            occupancy · fleet · fusion · dsz · kmaas ·
│       │                       reports · scenario · showreel · heatmap · collab
│       ├── services/           hydranet · occupancy · risk_transformer · intent ·
│       │                       v2v · bus_aware · bidirectional · pii · dsz_adapter ·
│       │                       scenario · showreel · hazard_report · public_api
│       └── tests/              18 통합 테스트 (외부 API fallback)
├── auraview_fleet/             ★ Flutter (Android + Web) — Perception Eye 아이콘 + 풀스크린 UX
├── frontend_pwa/               백업 PWA (HTML/JS)
├── landing/                    allthatai.kr 랜딩 페이지 (GitHub Pages)
├── static/
│   ├── slides/                 Reveal.js 발표 12장 (/slides)
│   └── kiosk/                  무인 자동 시연 9장면 (/kiosk)
├── notebooks/                  train_*.ipynb · risk_transformer_metric.py · accident_reenactment.ipynb
├── models/                     risk_transformer_metric.json (AUC 0.94)
├── dsz_exports/                안심구역 결합분석 샘플 (k=5 익명화)
├── docs/                       WHITEPAPER_KR.md · ROADMAP.md · DATASETS.md
├── .github/workflows/          ci.yml (Python+Flutter 자동 테스트) + deploy.yml (push→EC2 자동)
├── requirements.txt
└── README.md (이 파일)
```

---

## 🔌 API 엔드포인트

| Method | Path | 가점 |
|---|---|---|
| `GET`  | `/ui` `/pwa` `/slides` `/kiosk` `/docs` | 분석 |
| `POST` | `/detect/frame` · `/detect/video` | 분석 |
| `POST` | `/occupancy/infer` · `GET /occupancy/demo` | 학습·분석 |
| `POST` | `/fleet/contribute` · `GET /fleet/stats` | 가명·학습 |
| `GET`  | `/fusion/intersection/{id}` · `/fusion/sources` | 융합 |
| `POST` | `/dsz/verify` · `/dsz/join/taas-vds` · `GET /dsz/artifacts` | 안심·가명 |
| `POST` | `/reports/generate?top=N` · `GET /reports/list` | 분석·안심 |
| `POST` | `/scenario/reenact` · `GET /scenario/list` · `/scenario/presets` | 분석 |
| `POST` | `/showreel/build` · `GET /showreel/list` | 분석 |
| `GET`  | `/kmaas/alternatives` · `/kmaas/operator-report` | **K-MaaS 특별상** |
| `GET`  | `/heatmap/taas` | 융합·분석 |
| `POST` | **`/collab/v2v/broadcast`** · `GET /collab/v2v/intersection/{id}` · `/v2v/stats` | **협업 인지** |
| `POST` | **`/collab/v2v/seed-demo`** | 시연 시드 |
| `POST` | **`/collab/bus-context`** · **`/collab/bidirectional`** | 협업 인지 |
| `POST` | **`/collab/fused-occupancy`** ★ | **단독 vs 협업 비교** |

---

## 🚀 Quickstart

```bash
# Backend
git clone https://github.com/leelang7/AuraView.git
cd AuraView
cp .env.example .env    # → SERVICE_KEY 등 실제 값 입력
pip install -r requirements.txt
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000

# Flutter (Android + Web)
cd ../auraview_fleet
flutter pub get
flutter run -d chrome --web-port 5180 --dart-define=AURAVIEW_API_BASE=http://localhost:8000
# 또는
flutter build apk --release --dart-define=AURAVIEW_API_BASE=https://auraview.allthatai.kr
```

대시보드: http://localhost:8000/ui · 통합 테스트: `cd backend && pytest tests/`

---

## 💡 Use Cases

- **횡단보도에서 버스가 신호등을 가림** → 신호 API + Bus prior + V2V 마주오는 차 → 보행자 직격
- **사각지대 이륜차** → BEV occupancy + intent + 마주오는 차 시점
- **전방 교차로 위험 ≥ 6** → K-MaaS 우회 대중교통 3종 추천
- **상습 위험 교차로** → Top-N 정책 리포트 자동 생성 → 지자체·도로공사·K-MaaS 환원
- **무인 시연 부스** → `/kiosk` 한 화면에 9장면 자동 순회

---

## 🗺️ Roadmap

- [x] Week 1 — Occupancy PoC + HydraNet skeleton
- [x] Week 2 — 6종 어댑터 + 가명결합 + E2E baseline (AUC 0.94)
- [x] Week 3 — BEV 3D · Fleet PWA · Flutter 앱 · 안심구역 결과물 · 사고 재현 영상
- [x] Week 3.5 — V2V + Bus + Bidirectional 협업 인지 + Reveal 발표 + Kiosk
- [ ] Week 4 — 발표 슬라이드 v2 · 시연 리허설 · 제출 패키지 마감

상세 → [docs/ROADMAP.md](docs/ROADMAP.md)

---

> **보이지 않는 정보를 데이터화하고, 보이지 않는 공간을 계산하여, 다른 차량의 시점까지 빌려와 미래 위험을 예측한다.**
