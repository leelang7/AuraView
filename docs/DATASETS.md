# Datasets · 가명결합 · 안심구역 가이드

> 6종 공공데이터 융합 + 가명결합 + 국토교통 데이터안심구역 절차를 통합한 AuraView 데이터 플로우 문서.

---

## A. 실시간 공공 API (6종)

| # | 소스 | Base URL | 어댑터 함수 |
|---|---|---|---|
| 1 | 교통안전 실시간 신호 | `apis.data.go.kr/B551982/rti` | `public_api.fetch_signal_info()` |
| 2 | 한국도로공사 VDS | `data.ex.co.kr/openapi` | `public_api.fetch_vds_traffic()` |
| 3 | 한국도로공사 돌발상황 | `data.ex.co.kr/openapi` | `public_api.fetch_incidents()` |
| 4 | TAAS 사고이력 | `taas.koroad.or.kr/openapi` | `public_api.fetch_taas_accidents()` |
| 5 | ITS 국가교통정보 | `openapi.its.go.kr:9443` | `public_api.fetch_its_link()` |
| 6 | 안심구역 결합결과 | `dsz.ex.co.kr` (수동 반출) | `dsz_adapter.verify_artifact()` |

키 발급: 각 포털에서 개별 발급 후 `.env` 의 `EX_OPEN_KEY`, `TAAS_KEY`, `ITS_KEY` 등에 등록.

---

## B. 학습용 정적 데이터셋

| 이름 | 용도 | 비고 |
|---|---|---|
| AIHub "도로장애물·돌발상황" | 멀티태스크 검출 학습 | 한국어 라벨 |
| AIHub "이륜·보행자 위험상황" | VRU·intent 학습 | 사회적 가치 |
| Roboflow K-LISA traffic-light | 신호등 분류 | 공개 |
| nuScenes BEV subset | occupancy 벤치마크 | 평가용 |
| TAAS 과거 사고 CSV | 위치 prior | 연간 |

학습 데이터는 `datasets/` 하위에 보관 (gitignore).

---

## B-2. 시연 시나리오 8종 — 데이터 결합 매핑

각 시나리오가 어떤 공공데이터 + 학습 데이터 + 자체 prior 를 결합하는지 추적표.

| # | 시나리오 | 핵심 결합 데이터 | 차별 prior |
|---|---|---|---|
| 1 | `truck_occlusion` | AIHub 도로장애물 + 신호 API | occlusion shadow +0.55 |
| 2 | `motorcycle_blindspot` | AIHub 이륜 + ITS 차로별 속도 | BEV 사각 sweep |
| 3 | `signal_occlusion` | Roboflow 신호등 + ITS + V2V 풀 | 신호 API 결합 |
| 4 | `rainy_intersection` | 기상청 RDR + AIHub 우천 | rainy/night 가중치 +0.45 |
| 5 | `right_turn_pedestrian` | 도로교통공단 우회전 사고 + V2V | 회전 sweep zone |
| 6 | `school_zone` | **DSZ (국토부 데이터안심구역)** + 학교 위치 GIS | 등하교 시간대 +0.62 |
| 7 | `bicycle_lane` | 도로 GIS 자전거 레이어 + V2V 후방 | 자전거 도로 prior +0.40 |
| 8 | `night_pedestrian` | TAAS 야간 사고 + V2V 마주오는 차 | 헤드라이트 share + 환경 +0.45 |

응답: `GET /occupancy/demo?scenario={name}` → `class_grid_flat` (40×40), `hotspots[]`, `risk_summary`, `available_scenarios`.

---

## C. 가명정보 결합 (TAAS × VDS 예시)

### 결합 대상
- TAAS 2024년 교차로 사고 레코드
- 한국도로공사 VDS 2024년 해당 교차로 인근 시간대 소통 데이터

### 결합키 (준식별자)
```
district_code   # 시군구 코드
date_hour       # YYYY-MM-DD-HH 단위 bucket
link_id         # ITS 표준 링크
```

### 원천 PII 처리
- 사건 ID, 차량번호, 운전자 ID → **결합 전에 HMAC-SHA256 가명화**
- 결합 후 원천 식별자는 반출물에 포함 금지

### k-익명성
- `k = 5` 미만 그룹은 반출 레코드에서 제거
- 구현: `services/pii.k_anonymize()`

### 검증
```python
from app.services import pii
joined = pii.join_taas_vds(taas_records, vds_records)
# 자동으로 k=5 필터링됨
```

---

## D. 국토교통 데이터안심구역 프로세스

**URL:** https://dsz.ex.co.kr

### 1) 신청
- 이용 목적서, 분석 계획서 제출
- 국토부·한국도로공사 승인 (평균 2~4주)

### 2) 반입
- 안심구역 내 전용 분석 환경(VDI)에 원천 데이터 반입
- 인터넷·외부 매체 차단
- 반입 데이터: TAAS 원천, VDS 원천, 지번·좌표 상세

### 3) 분석
- 안심구역 VDI에서 AuraView 결합 스크립트 실행
- 결과물은 **집계·분포·추세**만

### 4) 반출
- 결과물에 SHA-256 해시 부착
- 승인 후 외부 반출
- AuraView 에서는 `POST /dsz/verify` 로 해시 검증 + 메타 기록

### 5) 감사 로그
- `dsz_exports/manifest.jsonl` 에 모든 반입 결과물 이력 기록
- 제출 시 이 파일을 증빙으로 첨부 가능

---

## E. 제출 시 데이터 관련 체크리스트

- [ ] 6종 API 키 발급 증빙 스크린샷
- [ ] 안심구역 이용 승인서 스크린샷
- [ ] 가명결합 스크립트 + k-익명성 테스트 결과
- [ ] 반출 결과물 SHA-256 해시 목록
- [ ] 학습 데이터 출처·라이선스 명세
