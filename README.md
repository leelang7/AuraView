# AuraView

> 비가시 교통정보 축적·고도화 기반 지능형 안전 주행 지원 시스템

보이지 않는 신호와 공간을 계산해 미래 위험을 예측하는 모바일 웹 서비스입니다.  
앞차나 대형차에 가려진 신호 상황을 YOLOv8 기반으로 감지하고, 공공 신호 API와 결합해 즉시 HUD 경고를 제공합니다.

---

## Demo

**Dashboard** → `http://13.48.70.193:8000/ui`

---

## Pipeline

```
영상 입력
  → YOLOv8 시야 차단 인식
  → 비가시 영역 추정
  → 공공 신호 API 연동
  → 위험 스코어링
  → HUD 경고 출력
  → 이벤트 DB 축적
```

---

## Key Features

- **시야 차단 인식** — YOLOv8-nano 기반 차량/신호 객체 탐지
- **신호 정보 복원** — 교통안전 공공데이터 API 연동 (교차로별 잔여시간, 신호 상태)
- **위험 스코어링** — 지속시간 · 장애물 유형 · 누적 이벤트 기반 실시간 점수 산출
- **이벤트 지도화** — Leaflet 기반 실시간 위험 분포 지도 및 TOP 5 랭킹
- **이미지 / 영상 분석** — 단일 프레임 오버레이 및 영상 구간별 위험 프레임 추출
- **HUD 알림** — 텍스트 기반 경고 안내 (신호 가림 감지 / 확인 가능)

---

## Tech Stack

| Layer | Stack |
|---|---|
| Backend | FastAPI · Uvicorn · SQLAlchemy · SQLite |
| Vision | YOLOv8-nano (Ultralytics) |
| Validation | Pydantic |
| Frontend | Vanilla JS · Leaflet.js (embedded HTML) |
| External API | 교통안전 실시간 신호등 정보 API (`apis.data.go.kr`) |
| Infra | AWS EC2 · nohup |

---

## Project Structure

```
AuraView/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI 앱 + 대시보드 UI
│       ├── config.py            # 환경 변수
│       ├── database.py          # SQLite 세션
│       ├── models.py            # ORM 모델
│       ├── schemas.py           # Pydantic 스키마
│       ├── routers/
│       │   ├── detect.py        # 이미지/영상 분석
│       │   ├── events.py        # 이벤트 CRUD + 지도 데이터
│       │   ├── risk.py          # 위험 스코어 집계
│       │   ├── signals.py       # 신호 정보 프록시
│       │   └── intersections.py # 교차로 동기화
│       └── services/
│           ├── detector.py      # YOLOv8 래퍼
│           ├── public_api.py    # 공공 API 호출
│           ├── matching.py      # 지오로케이션 매칭
│           └── scoring.py       # 위험 점수 계산
├── requirements.txt
└── README.md
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/ui` | 대시보드 |
| `POST` | `/detect/frame` | 이미지 위험 분석 |
| `POST` | `/detect/video` | 영상 위험 분석 |
| `GET` | `/events/` | 이벤트 목록 |
| `GET` | `/events/map-data` | 지도용 집계 데이터 |
| `GET` | `/risk/` | 교차로별 위험 랭킹 |
| `GET` | `/signals/{id}` | 교차로 신호 정보 |
| `GET` | `/intersections/` | 교차로 목록 |
| `POST` | `/intersections/sync` | 공공 API 동기화 |

---

## Quickstart

```bash
# 의존성 설치
pip install fastapi uvicorn sqlalchemy pydantic requests python-dotenv ultralytics

# 서버 실행 (개발)
cd AuraView/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 백그라운드 실행 (운영)
cd AuraView/backend
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &

# 서버 종료
pkill -f "uvicorn app.main:app"

# 로그 확인
tail -f AuraView/backend/uvicorn.log
```

### 환경 변수 (.env)

```
SERVICE_KEY=<공공데이터포털 API 인증키>
```

---

## Use Cases

**신호 가림 상황**  
전방 대형차로 신호가 보이지 않을 때 → `신호 가림 감지 / 잔여 12초`

**보행자 출현 예측**  
횡단보도·골목 위험 구간 접근 시 → `보행자 출현 가능`

**사각지대 차량 접근**  
측면/후방 비가시 구역 → `충돌 위험`

---

## Roadmap

- [ ] Transformer 기반 시계열 위험 예측 모델
- [ ] 프론트엔드 분리 (React / Vue)
- [ ] PostgreSQL 전환
- [ ] API 인증 (JWT)
- [ ] 업로드 파일 자동 정리

---

> **보이지 않는 정보를 데이터화하고, 보이지 않는 공간을 계산하여 미래 위험을 예측한다**
