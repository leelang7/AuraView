# Changelog

All notable changes to **AuraView K-Perception** are tracked here.
Format: keep a [keep-a-changelog](https://keepachangelog.com/en/1.1.0/) style + commit SHA.

---

## v0.22 — 대시보드 ↔ 23종 데이터 시각화 일관성 + 위험점수 분해 (2026-05-22~23)

### Fixed — UX 일관성 (사용자 피드백 "공공데이터 보여주는게 없음")
- `/fleet/` 대시보드 메인 컨텐츠를 **23종 공공데이터 라이브 grid** 로 교체 (v12.44)
  - 각 카드: live/stub 도트 + age + 이름 + origin + 기여도
  - 헤더: `N/23 · live X · stub Y` 카운터 (5s 폴링)
- 23 grid 카드별 **실 derived 값** 표시 — 한양대 1007 기준 (v12.45)
  - 신호 '정지/주의/진행', VDS '평균 38km/h', TAAS '반경 내 N건', 우천 '+18%', 단속 'N대', 횡단 '50m 접근⚠' 등
  - 카드 클릭 → `/fusion/intersection/{iid}` JSON 새 탭
- 23 grid 헤더에 **교차로 dropdown** 9 위치 (v12.46)
  - 8 known + 1 강원 임의 GPS — 토글로 위치인식 stub 즉시 비교
  - 임의 GPS 선택 시 카드 accent 색 회색조 (#7C8AA8) — 시각적 구분
- `/policy` + `/scorecard` 에 23 소스 mini strip (v12.47)
  - "지금 N/23 호출 중 · live X / stub Y · [라이브 grid →]"
- `/story` 첫 인상 페이지 23 카드에 **라이브 live/stub 도트** (v12.48)
  - 각 카드 우상단 8px 도트: live=녹색 glow, stub=황색 dim
  - 헤더 ping strip: "지금 이 순간: N/23 호출 중"

### Removed — "심사위원" 용어 일괄 제거 (v12.44)
사용자 피드백 "심사위원 그딴 용어는 빼고":
- 7 파일에서 "심사위원" → "경진대회" / "검증" 으로 정리
  - competition / gallery / kiosk / story / slides / scorecard 6 정적 페이지
  - 표 라벨 / 메뉴 라벨 / pill 텍스트 / 주석 모두

### Added — 위험점수 기여도 분해 (v12.49)
`GET /fusion/risk-breakdown/{iid}` 신규 — 23 소스 각각이 fusion_risk_score 에 얼마나 기여했나:
- `raw 값 + weight + contribution (= value × weight)` 분해
- `raw_weighted_sum` (조정 전) + `final_risk_score` (스쿨존 ×N / 횡단 ×1.10 / V2X 감산 적용 후) 모두 노출
- contribution 내림차순 정렬
- fleet 대시보드 신규 차트: 라벨 / 가로 막대 (raw 표시) / contribution + weight, 큰 기여 황색
- 한양대 1007 top 5: VDS(0.050) / ER(0.022) / 스쿨존(0.016) / 우천(0.013) / DTG(0.003)

### Performance — 라이브 응답시간 대폭 단축 (v12.43+v12.52+v12.53)
**v12.43** /fleet/demo-tour: 30s+ → ~15s (cold) / ~1s (cache hit)
- `_DEMO_TOUR_CACHE` 60s TTL
- `ThreadPoolExecutor(max_workers=10)` 외부 fetch_fusion 10건 병렬

**v12.52** /fusion/risk-breakdown: 30s+ → ~3s (cold) / <300ms (cache hit)
- `_RISK_BREAKDOWN_CACHE` 60s TTL per intersection
- 라이브 검증: cold 28s → cache hit 299ms

**v12.53** fetch_fusion 근본 병렬화 (가장 임팩트 큼):
- 22 sub-fetch sequential → `ThreadPoolExecutor(max_workers=12)` 동시 실행
- weather 만 black_ice 의존 → 두 단계 분리
- 라이브 검증: /fusion/intersection cold ~28s → **6.5s** (4배 단축)
- pytest 풀 스위트 **55s → 30s** (-45%)
- 모든 fusion 호출 (demo-tour / risk-breakdown / intersection) 동시 혜택

### Added — HUD mockup SVG (v12.41) + /gallery 등록 (v12.42)
실 디바이스 캡쳐 대체용 마케팅 자료:
- `static/visuals/hud_mockup.svg` — Tesla 스타일 23-chip HUD (720×1440 Galaxy Z Fold 비율)
  - 상단 카메라: 트럭 검출 박스 + 보행자 블라인드스팟 + ML Kit FPS counter
  - 23 chip row 3줄
  - BEV: 40×40 voxel + ego/truck/V2V + 횡단보도 + 위험 히트맵
  - 하단 HUD: Tesla식 큰 속도 + FUSION RISK 게이지 + schema v9-23src + AURA ENGAGED pill
- `/gallery/?f=app` 에 등록 (19 → 20 SVG)

### Updated — 회귀 잠금 + 문서 일관성
- pytest 117/117 PASSED — risk-breakdown 2건 추가 (v12.50)
- /story OG/Twitter meta 12종 → 23종 (소셜 공유 카드 통일) (v12.31)
- kiosk 4개 scene + competition + summary 9-23종 (v12.31)
- gallery / reel / slides 15/21 → 23 일괄 정렬 (v12.32)
- ROADMAP / REPRODUCIBILITY / DATASETS (전체 23행 어댑터 매핑) (v12.29)
- PRESS_KIT / SUBMISSION / PRESENTATION_SCRIPT / WHITEPAPER 6종 → 23종 (v12.28)
- visuals SVG 3개 (fusion_diagram / before_after / og_card) + native app 마케팅 텍스트 23종 (v12.33)
- README v9 업데이트 블럭 + 데이터융합 row + tests 배지 117/117 (v12.36+)

---

## v0.21 — 23종 확장 (국토부 횡단보도 GIS) + 50m 접근 알림 (2026-05-21)

### Added — 23번째 데이터 소스 (v12.23)
- **`#23 국토부 횡단보도 GIS`** (`api.vworld.kr/req/wfs lt_l_crwlk`) — 횡단보도 polyline + 신호등 유무
  - 12개 fixture (8개 known 교차로 + 3개 스쿨존 횡단보도 + 강남대로)
  - derived: crosswalk_count_within_radius (300m), nearest_crosswalk_m, approaching_crosswalk (50m 내), school_zone_crosswalk_count, crosswalk_pedestrian_boost (최대 +0.08)
- 위험 가중치 v9: cw_boost × 0.05 추가, approaching True 시 base × 1.10
- `schema_version`: `fusion.v8-22src` → `fusion.v9-23src-2026.05.21`
- 신규 엔드포인트 카탈로그: `/fusion/sources` 에 23번째 entry

### Updated — 네이티브 HUD
- 횡단보도 chip: 50m 접근 시 적색 '횡단보도 50m', 스쿨존 횡단보도 '스쿨횡단 N', 일반 '횡단 N'
- expectedSchemaPrefix: `fusion.v9-23src`
- sourcesFused 배지: 23src v9 추가

### Static pages
- /story/ /scorecard/ 22종 → 23종 + 횡단보도 GIS 카드 추가 + 가중치 v9 표시

---

## v0.20 — 22종 확장 (경찰청 단속CCTV) + 위치인식 stub 정확성 (2026-05-21)

### Fixed — 임의 GPS 위치에서 거짓 알람 차단 (v12.20)
사용자 보고: "집에서 테스트하는데 이 위치에 적색/정지 신호 hud이게 왜나오냐?"
- **`fetch_taas_accidents(bbox)`**: bbox 안의 사고만 반환 — 임의 위치에서 7건 거짓 알람 차단
- **`fetch_emergency_capacity(lat,lon)`**: 반경 5km 내 병원만으로 nearest_ER 재계산
- **`fetch_incidents(bbox)`**: bbox 내 돌발만 필터
- **`fetch_bike_stations(lat,lon)`**: 반경 1.5km 내 따릉이 정거장만으로 derived 재계산
- **`fetch_fusion`**: `gps-{lat*1000}-{lon*1000}` iid 에서 실제 GPS 파싱 + bbox 자동 생성
- **`_signal_stub_cycle`**: `gps-*` 임의 위치 → unknown 신호 (red/stop 가짜 알람 제거)

### Added — 22번째 데이터 소스 (v12.21)
- **`#22 경찰청 교통단속 CCTV`** (`apis.data.go.kr/1320000/CityTrafficCctv`) — 단속 카메라 위치 + 단속실적
  - 단속 밀집 = 사고다발 정책 prior (5년 단속실적 기반)
  - 9개 fixture: 강남대로/테헤란로/광화문/잠실대교/왕십리/사당역/신촌/한양대역/건대입구
  - derived: cam_count_within_radius, enforcement_risk_boost (최대 +0.10), is_enforcement_hotzone
- 융합 가중치: enforcement_risk_boost × 0.04 추가
- `schema_version`: `fusion.v7-21src-2026.05.19` → `fusion.v8-22src-2026.05.21`

### Added — 자가 검증 (location_accuracy)
- `GET /fleet/verify` 신규 컴포넌트: 강원 임의 GPS (38.2, 128.5) 에서 unknown/0/0/LOW 반환 검증
- 대시보드 PIPELINE CHECK 스트립에 `LOC ACC` 배지 추가

### Updated — 네이티브 HUD (v12.20-v12.21)
- TAAS chip: `summary.taas_accidents_nearby` 0 이면 미표시 (집/임의 위치 거짓 알람 차단)
- GPS 모드 배지: `gps-*` iid 시 'GPS' 작은 배지 표시 — 데이터 출처 투명성
- 단속카메라 chip: 단속 1대 이상이면 videocam 아이콘 + N대 + boost%; 단속존(≥3대) 적색 danger 톤
- sourcesFused 배지: 22src v8 → 21src v7 → ... 호환 유지
- expectedSchemaPrefix: `fusion.v8-22src`

### Static pages
- /story/ /scorecard/ 21종 → 22종 + 경찰청 단속 CCTV 카드 추가

---

## v0.18 — 21종 확장 (도로노후+V2X) + Tesla UI/UX 전면 개편 + /policy 라이브 API (2026-05-19)

### Added — 19 → 21종 데이터 융합 확장 (v7)
- **`#20 행정안전부 도로 노후도`** (`apis.data.go.kr/1741000/RoadAgeStats`) — 노후 포장 비율 + 포트홀 밀도
  - 시도별 aged_15y_plus_pct + pothole_per_km + crack_index
  - 노후도 0.30 초과 시 +0.06, 포트홀 평균 초과 시 +0.04 → max +0.10 road_age_risk_boost
- **`#21 KOTSA 자율주행 데이터허브 (V2X)`** (`apis.data.go.kr/B552014/AvHub`) — HD map + V2X RSU + AV 시범운행
  - 판교/세종/상암 등 자율주행 시범지구 데이터
  - av_confidence = HD map 0.7 + V2X RSU 0.3 가중평균
  - **음의 prior**: V2X 인프라 충분한 구역은 위험 감산 (`av_risk_reduce`)
- 융합 가중치 v7 재조정: speed 0.13 + 돌발 0.08 + TAAS 0.08 + 기상 0.07 + 노면 0.06 + DTG 0.06 + 도로노후 0.06 + 119 0.05 + 스쿨존 0.08 + 보행 0.05 + 통학로 0.05 + 검사 0.04 + ER 0.04 + 자전거 0.04 + 미세먼지 0.03 + EV 0.02 − av_risk_reduce
- `schema_version`: `fusion.v7-21src-2026.05.19`
- 신규 엔드포인트: `GET /fusion/road-age` + `GET /fusion/av-hub`

### Added — Backend /policy/stats endpoint
- `GET /policy/stats` — 정책의사결정 대시보드용 집계 KPI
  - kpi (fleet/events/hot_grids/recommendations/CI 95%)
  - top_hotspots 10개 (rank + name + risk + ci + factors)
  - recommendations 4종 (schoolzone_new / signal_tuning / enforcement / infra)
  - time_pattern_2d_24x7 (168 cells = 7days × 24h)

### Updated — /policy/ 전 페이지 라이브 API 기반 (v10.3)
- 이전: KPI 5개만 페치, hotspots/recs/heatmap 은 하드코딩 HTML
- 이번: 모든 데이터를 `/policy/stats` API 에서 동적 렌더
  - `renderHotspots()` / `renderRecs()` / `renderHeatmap()` 함수화
  - 패널 헤더에 `GET /policy/stats` endpoint URL 노출 (judges 검증용)
  - escapeHtml() XSS 가드
- KPI count-up 애니메이션 (easeOut 1.1~1.3s)

### Updated — Flutter 네이티브앱 Tesla 시각언어 전면 적용 (v11.2)
사용자 지적 "디자인 UI/UX 간지나게 세련되게 테슬라 스타일로":
- **_UnifiedStatusBar**: BackdropFilter blur 16 + glassmorphism + Tesla 시그니처 큰 숫자 28pt + uppercase tracking
- **_TeslaChip**: 26px 작은 pill (REC / 업로드 / ONLINE 상태)
- **_TeslaLabel**: 카메라/BEV 카드 corner badge (글로우 dot + uppercase 9.5pt tracking 1.0)
- **_RecPill**: Tesla "Engage AP" 풍 (42px, "TAP TO ENGAGE" / "AURA · ENGAGED", 빨강 글로우 spread)
- BEV 카드 borderRadius 14 → 20, white 8% border, drop shadow (떠있는 느낌)
- _IdleStatusCard 폐기 → 화면 95% 가 카메라+BEV split
- 중복 ⚙ 설정 버튼 제거
- IPM affine 워프 폐기 (사용자: "걍 아핀변환해서 보여주는거 아니냐") → 순수 합성 3D BEV
- 검출 파이프라인 가시 디버그 pill 추가 (raw=N kept=M / "ML Kit 초기화 실패" 등)
- ML Kit area filter 완화 (1.2% → 0.4%)

### Static pages
- /story/ /scorecard/ /privacy/ /policy/ /reel/ /kiosk/ /gallery/ /visuals/fusion_diagram.svg → 19 → 21 일괄 갱신

---

## v0.17 — Tesla 식 정책 대시보드 + /bev3d 실 카메라 구동 (객체 모양 보존) (2026-05-18)

### Added — /policy/ 정책의사결정 대시보드 (Tesla fleet → 통계 → 정책)
**핵심 컨셉 재정렬**: 이 프로젝트의 본질은 실시간 경고가 아니라
[수집 (fleet) → 가명·집계 → 통계분석 → 정책의사결정] 데이터 가치사슬.
- 상단 4단계 pipeline (수집/가명집계/통계분석/정책결정)
- 5 KPI 카드: fleet 1,247대 · 위험이벤트 38,914 · 고위험 그리드 218 · 정책제안 17 · CI 95%
- 좌측 공간 위험 히트맵 (Seoul · 100m 그리드 · k≥5 익명 결합 후)
  - 빨강/주황/녹색 클러스터 + 스쿨존 폴리곤 (학동초/청운초) + 도로망
- 시간대×요일 heatmap (24h × 7days) — 평일 등교/퇴근, 금요일 야간 고위험 자동 패턴
- 위험 상위 10개 교차로 (신뢰구간 95%) — 강남대로/청운초/양재대로 등 + CI half-width
- 데이터 기반 정책 제안 4종 (기대 사고감소 시뮬레이션):
  - 스쿨존 신설: -32% / 연 4건
  - 신호 조정: -21% / 연 3건
  - 단속 강화: -18% / 연 2건
  - 인프라 개선: -14% / 연 2건
- 가명·집계 처리 노티스 + /privacy/ 직링크

### Updated — /bev3d 실 카메라 구동 점유 BEV (v8: 객체 모양 보존, 사용자 요청)
이전 정적 시뮬 + PiP 데코를 진짜 카메라 입력 기반으로 교체:
- TensorFlow.js + COCO-SSD lite_mobilenet_v2 on-device (~5fps)
- 6 클래스: person/bicycle/motorcycle/car/bus/truck
- pixelToBev() 호모그래피: bottom_y 비선형 깊이 (1.5~35m) + 가로 lateral
- **객체 모양 살리기**: BoxGeometry 폐기 → SpriteMaterial + CanvasTexture
  - updateOccCrop(): video.drawImage(ROI) 로 실 객체 픽셀을 매 프레임 캔버스 텍스처에 복사
  - bbox 비율(AR)로 빌보드 width/height 동적 (왜곡 방지 fit + 색 외곽선)
- Tesla 비주얼 톤: ego emissive 0.45 + 외곽 글로우 링 + 전방 예측 경로 8 segment fade
- 트래커 + 평활화 (1.5s decay + texture/material dispose)
- 위험 빌보드 위치 = 최근접 점유물 위, 색/액션 동적 (즉시 정지/감속/안전)

### Updated — v8.2 /bev3d/ 견고화 (사용자 "실시간 라이브? 사람 모양?")
- TF.js backend 명시 분리: webgl 우선 → cpu 폴백 (Android WebView 호환성)
- 별도 모듈 로드: tfjs-core + tfjs-converter + tfjs-backend-webgl + tfjs-backend-cpu
- AI 상태 배지 (#ai-status): 우상단 펄스 LED + 라벨
  - 단계별 표시: TF backend 초기화 → 모델 다운로드 → AI ready · webgl/cpu · 검출 N개
  - 실패 시 빨강 LED + 사유 메시지

### Updated — Flutter v7.5 ★ 모드 5탭 확장
- _JudgeModeScreen: 4탭 → 5탭
  - ★ 가산점 · ⚖ 정책 · 🔒 PII · 🛡 안전구역 · 📖 스토리
- /policy/ 새 페이지를 ★ 두번째 탭으로 우선 배치

### Static pages
- /story/ nav: ⚖ 정책 대시보드 핀 추가
- /scorecard/ 엔드포인트 목록에 /policy/ 추가
- backend/app/main.py: /policy 마운트

---

## v0.16 — 가산점 25점 적격 증거 페이지 + 19종 융합 + 자체 3D BEV (2026-05-18)

### Added — judge-facing 페이지 4종 신규
- **`/scorecard/`** — 가산점 25점 적격 증거표 1-page (AI 10 + 데이터융합 5 + 가명정보 5 + 안전구역 5)
  - 카테고리별 색상 카드 (cyan / purple / orange / green)
  - 각 카드: 평가기준 → 구현 5개 증거 → 라이브 링크 버튼
  - 하단: 심사위원 즉시 검증 라이브 엔드포인트 8개 카탈로그
- **`/bev3d/`** — AuraView 자체 Three.js 3D BEV (MetroEyes URL 폐기)
  - importmap three@0.170.0 + OrbitControls (zoom 12-80)
  - 한국 우측통행 도로 + 황색 점선 + 가로 횡단보도 + ego/NPC/보행자 펄스
  - getUserMedia 후면 카메라 PiP 좌상단 140×100
  - `/fusion/intersection/1007` 8초 폴링 → 하단 메트릭 (vehicles/peds/risk/lead)
- **`/privacy/`** — 가명정보 처리 라이브 데모 (5pt 실증)
  - 5단계 PII 파이프라인 시각화 + Before/After SVG (번호판/얼굴 블러)
  - SHA-256 라이브 해시 (Web Crypto API · 브라우저 내)
  - 100m GPS 양자화 + k-익명 결합 테이블 (k≥5 / k<5 SUPPRESS)
  - 개인정보 영향평가 7대 항목 체크리스트
- **`/safezone/`** — 안전구역 라이브 대시보드 (5pt 실증)
  - SVG 인터랙티브 맵: 스쿨존 폴리곤 ×1.5 / 통학로 / 보행자 hotspot / E-Gen
  - 위험순위 상위 6개소 카드 + 융합 가중표

### Added — 17 → 19종 데이터 융합 확장 (v6)
- **`#18 KOTSA DTG`** (`apis.data.go.kr/B552014/DtgStats`) — 사업용 차량 디지털운행기록
  - 택시·시내버스·전세버스·화물차 4종, 급가속/급감속/과속 per 100km
  - `danger_score` 0.48~0.71 → `dtg_risk_boost` 최대 +0.10
- **`#19 소방청 119 출동`** (`apis.data.go.kr/1661000/TfcAcdntDsptchInfo`) — 교통사고 출동 통계
  - 시도별 평균 도착시간 / severe/fatal share
  - 평균 도착 > 7분 시 자동 `severity_multiplier` 상향 (골든타임 라우팅)
- 융합 가중치 v6 재조정: speed 0.14 + DTG 0.07 + 스쿨존 0.09 + 119 심각도 0.05 + 노면 0.06 + 보행자 0.05 ···
- 신규 필드 5개: `dtg_danger_score`, `dtg_risk_boost`, `nfa_severity_multiplier`, `nfa_severity_risk_boost`, `golden_time_at_risk`
- `schema_version`: `fusion.v6-19src-2026.05.18`
- 신규 엔드포인트: `GET /fusion/dtg` + `GET /fusion/nfa-dispatch`

### Updated — Flutter 네이티브앱 v7
- `MetroEyesBevScreen` → `AuraView3DBevScreen` 전면 교체
- URL: `https://auraview.allthatai.kr/bev3d/` (자체 호스팅)
- `AndroidWebViewController.setOnPlatformPermissionRequest((r) => r.grant())` — WebView getUserMedia 자동 허용
- `setMediaPlaybackRequiresUserGesture(false)` — 자동 카메라 시작
- `webview_flutter_android ^4.0.0` 명시적 의존성 추가
- 상단 nav 핀 추가 (`/story/`, `/gallery/`): `⭐ 가산점 25점` / `🎮 3D BEV` / `🔒 PII 데모` / `🛡️ 안전구역`

### Fixed
- MetroEyes 전체 운영자 페이지(지하철/버스 대시보드) 통째로 임베드한 실수 → 3D 시각화만 적용한 자체 페이지로 교체
- 폰 후면 카메라가 WebView 안에서 동작하지 않던 문제 → `setOnPlatformPermissionRequest((r) => r.grant())` 처리

---

## v0.15 — MetroEyes 3D BEV WebView 통합 + Flutter UI 디테일 개선 (2026-05-18)

### Added — MetroEyes 3D BEV 통합 (사용자 다른 GitHub 프로젝트 결합)
- `webview_flutter ^4.10.0` 신규 의존성
- **`MetroEyesBevScreen`** StatefulWidget — `https://leelang7.github.io/MetroEyes/frontend/operator_web/realbev.html` 풀스크린 임베드
  - NavigationDelegate LinearProgressIndicator (로딩 진행률)
  - 로딩 중 spinner + "MetroEyes 실시간 3D BEV 로딩…" 안내
  - AppBar 새로고침 버튼
  - 다크 배경 통일
- **헤더 우측 신규 "3D" 보라 그라디언트 버튼** (`_IdleStatusCard` 설정 버튼 옆)
  - Navigator push → MetroEyesBevScreen
  - 글로우 효과 (#A095FF accent2)

### Updated — Flutter UI 디테일 (사용자 "조잡하다" 피드백)
- **`_CityInfoLine` 칩** 폰트 10→12pt, 아이콘 11→13, spacing 8→10, runSpacing 4→6, weight w700 추가
- **`_SignalHud` 카드** 신호 아이콘 38→48px, 교차로명 13.5→16pt(w900), 상태 10.5→12pt(w800), 안내 박스 폰트 12.5→14pt(w700), 좌측 보더 3→4px, 권고 라인 ↗ 아이콘 + 12.5pt(w800)
- **`_DriveButton` 알약** 260px 폭, 녹색 그라디언트 (모니터링 중), 펄스 dot, 흰 글로우 보더, 이중 그림자

### Why
- MetroEyes 결합 = 운전자 폰에서 차량 BEV (AuraView) + 대중교통 BEV (MetroEyes) 동시 접근 → "한국 도로 전체 통합 인지" 차별점
- 사용자 직접 폰 사용 시 폰트 가독성 + 시각적 무게감 부족 해소

### 빌드/설치
- app-release.apk 86.4MB · adb install -r Success (Galaxy Z Fold 3, Android 15)

---

## v0.14 — 외부 데이터 17종 확장 + Flutter HUD + 시뮬레이터 v5 동기화 (2026-05-18)

### Added — 외부 데이터 15 → 17종 확장
- **도로 노면 상태 (RWIS)** — `data.ex.co.kr/openapi/rwisapi` · EX_OPEN_KEY 재사용 (신규 키 불필요)
  - 4 station fixture (강남대로/성수대교/광화문/잠실대교)
  - `surface_risk_boost` : dry=0 / wet=0.10 / snow=0.22 / frost·ice=0.35
  - `low_visibility_flag` (시정 < 2000m)
- **KOTSA 자동차검사통계** — `apis.data.go.kr/B552014/InspectionStats`
  - 시군구별 부적합률 (강남/송파/중구/성동 fixture)
  - `inspection_risk_boost` : 부적합률 1%p 초과 시 +0.04
  - 잠재 사고 위험 지표 (제동·배기·타이어 등)
- 신규 엔드포인트: `GET /fusion/road-surface`, `/fusion/vehicle-inspection`
- `IntersectionFusion` 17 sources + fusion_summary 신규 5필드
- 위험점수 재가중 (속도0.16 + 돌발0.10 + ... + 노면0.07 + 검사0.05)
- `schema_version: fusion.v5-17src-2026.05.18`

### Updated — Flutter `_CityInfoLine` v5
- 🛣️ 도로 노면 신호 (RWIS) — frost/ice → 결빙, snow → 적설, wet → 습윤
- 🔧 자동차검사 부적합 신호 (KOTSA) — 시군구 부적합률 표시
- 배지 v5 추가 (sourcesFused ≥17)

### Updated — /story 인터랙티브 시뮬레이터 v5
- 슬라이더 8 → 10 (surface 0-35%, inspection 0-8%)
- 프리셋 5종 모두 v5 키 추가 (ice_bicycle: surface=35%, rush_er: insp=4%)
- 가중치 식 17-source 동기화 (backend 정합)

### Updated — 사용자 노출 카피 일괄 갱신
- 7 파일 일괄 갱신 (story/reel/competition/kiosk/slides/landing/README)
- "15종 공공데이터" → "17종 공공데이터"
- "15-Source Fusion" → "17-Source Fusion"
- "15 입력" / "15-source HUD" → 17

### Added — backend 신규 엔드포인트
- `GET /metrics/visuals` — 19 SVG 자동 인덱스 (카테고리/크기/URL)

### Tests (101 → 103 passed)
- `test_fusion_sources_lists_seventeen` (전 _fifteen 교체)
- `test_fusion_intersection_returns_seventeen_sources_v5` (전 _v4 교체)
- `test_fusion_road_surface_endpoint` (신규)
- `test_fusion_vehicle_inspection_endpoint` (신규)
- `test_data_attribution_lists_17_public_sources` (전 _15_ 교체)

### Why
- 가점 데이터융합 5점 강화: 17종 = 한국 도로 인프라가 측정 중인 거의 모든 신호
- 도로 노면 = 결빙·블랙아이스 정확도 ↑ (KMA 파생 + RWIS 직접)
- 자동차검사 = 잠재 사고 위험 차량 사전 식별 (정비 부적합 차량 ↑ 사고 위험 ↑)
- 모든 추가 데이터가 API 키 1개 (SERVICE_KEY 또는 EX_OPEN_KEY) 로 작동

---

## v0.13 — 19 SVG + 8 페이지 진입점 + Flutter 앱 전면 개선 (2026-05-17~18)

### Added — 시각자료 4종 신규 (16 → 19 SVG)
- `fusion_diagram.svg` (29KB) — 좌 15 입력 → 가운데 융합 엔진 → 우 4 출력
- `kmaas_alternatives.svg` (23KB) — 위험 교차로 + 지하철·버스·따릉이 3 우회
- `tesla_vs_auraview.svg` (25KB) — Tesla FSD vs AuraView 한국 차별점 5종
- `ai_metrics.svg` (27KB) — Risk Transformer 학습 결과 한 화면 (AUC/F1/ROC/scenario/v1↔v2)
- `app_mockup.svg` (27KB) — Flutter 앱 UI 모형 (폰 프레임 + 스택 + 메트릭)
- `taas_stats.svg` (21KB) — TAAS 2024 한국 도로 사고 통계 (도넛/시도별/시간대)
- `user_journey.svg` (29KB) — 운전자·정책결정자·시민 3 페르소나 흐름

### Added — 신규 페이지 (`/gallery`)
- `static/gallery/index.html` — 19 SVG 종합 그리드 (필터 + 라이트박스 + 카테고리 배지)
- main.py `_mount_static(['static','gallery'], '/gallery')` 마운트
- /story sticky 메뉴에 🖼️ 갤러리 링크 추가

### Added — Flutter 앱 전면 개선 (13 항목)
- **첫 진입 온보딩** PageView 3장 (`_OnboardingScreen` + SharedPreferences 'onboarding_done')
- **BEV setState GPU 최적화** (RepaintBoundary + ValueListenableBuilder + 30 FPS 캡)
- **AppLifecycleState.resumed 자동 재시작** (3 타이머 leak 수정)
- **카메라 권한 거부 복구 UX** (`_CameraPlaceholder` 풀 UI + openAppSettings)
- **위험 햅틱 경보** (alt_signal 정지 신호 시 heavyImpact 3 burst)
- **Dead class 6개 제거** (-196 line, _BevPainter / _BevToggleChip / _BrandLogo / _CounterChip / _StatusOrb / _PrimaryActionPill / _OpenSheetHandle)
- **Dead 함수 2개 제거** (_toggleBev, _manualContribute)
- **Deprecated Color API 마이그레이션 15곳** (.red → (r*255).round())
- **일반인 친화 한국어 카피** (alt_signal API → 가려진 신호등도 보여줍니다)
- **인앱 'AuraView가 뭐예요?' 카드** (_DetailSheet 최상단)
- **BIS 라이브 폴링** (/collab/bus-live · 5s)
- **15-source HUD** (스쿨존·결빙·보행자다발·PM·통학로·EV)
- **_BisBusBadge** (BEV 우상단 라이브 버스 표시)
- flutter analyze: 60+ → 34 issues (-43%) · 0 error 유지
- main.dart: 4748 → 4671 line

### Added — backend 신규 엔드포인트
- `GET /metrics/visuals` — 19 SVG 자동 인덱스 (카테고리/크기/URL)

### Added — landing 페이지 3 골든 진입점 카드
- 📖 30초 이해 (FFB020→FF6B6B)
- 🎥 1분 시연 (FF4444→7c3aed)
- 🖼️ 18 SVG 갤러리 (A095FF→00C8FF)
- AuraView 카드 badges 12개 (15-Source Fusion · BIS Live · 신호 API · DSZ k-anon · KMA·NEDIS · 스쿨존 GIS 등)

### Updated — README Live 섹션
- 8 진입점 표 (story / reel / gallery / competition / ui / slides / kiosk / submission)
- 19 SVG 카테고리별 인덱스
- Native APK 설명 갱신 (온보딩 + 15-source + BIS + 햅틱)

### Why
- "수상 1위 목표" 사용자 피드백 반영
- 일반인·심사위원·정책결정자 3 청중 모두 30초 ~ 1분에 임팩트 이해
- Flutter 앱이 실제 작동하는 완성도 (온보딩 + 햅틱 + 백그라운드 복귀)
- 19 SVG 한 곳에서 검증 가능 (/gallery)

---

## v0.12 — before_after 시나리오 전환 + 시각자료 고증 정정 (2026-05-16~17)

### Changed — before_after.svg 시나리오 전환 (사용자 피드백)
- **이전**: '트럭이 횡단보도 앞 정지 + 어린이 횡단'
  → 트럭이 어차피 정지 상태이므로 내 차도 안전 정지하면 끝 → 임팩트 약함
- **새 시나리오**: '교차로 진입 중 앞 트럭이 신호등을 가림 → 내 차는 신호 상태 모름'
  → 적신호 무시 진입 위험 + AuraView 신호 API 직접 호출로 카메라 가림 무관
- 한국 표준 차량 신호등 (cantilever 매달림, 적-황-녹 가로 배열)
- 위 차로 + 우→좌 진행 + 모든 차량 화면 우측 (한국 우측통행)

### Fixed — 시각자료 고증 일괄 정정
- **횡단보도 stripe** : 차량 진행 방향과 평행 (가로로 긴 흰색 stripe, 세로 반복) — 한국 표준
- **보행자 신호등** : 사람 픽토그램 (빨강 서있는 사람 / 녹색 걷는 사람) — 차량 신호등(원형 3색)과 구분
- **차량 신호등** : cantilever 매달림 (도로 위 공중, 적-황-녹 가로 배열)
- **차량 위치** : 한국 우측통행 → 차로 안에 배치, 중앙선 가로지름 X
- **EGO → 내 차** : 모든 시나리오에서 영어 라벨을 한국어로
- **사각지대 라벨** : 좌→우 진행 차량의 사각지대는 진행방향 기준 우측 후방 (라벨 정정)
- **timeline_57s.svg** : xlink namespace 미정의 XML 에러 수정

### Fixed — 01_truck_occlusion.svg 재작성
- 한국 우측통행 (위 차로 = 내 차 + 트럭 우→좌)
- 맞은편 AuraView 차 (아래 차로 좌→우) 가 보행자 정면 시점 → V2V 전송
- 차량이 차로 안에만 (중앙선 가로지름 X)
- 보행자에 빨강 글로우 + 점선 추적 박스

### Updated — 연동 카피 정합
- `/story` 1번 섹션 헤드라인 + sub + caption
- `/reel` 장면 2 자막
- `/slides` 2번 Problem 슬라이드 헤드라인

### Added — 시나리오 SVG 차로 음영 + 진행 방향 라벨
- 양 차로 색 구분 (위 = 반대편 어두운, 아래 = 내 차 약간 밝게)
- "내 차 ⟶" / "⟵ 반대 차로" 큰 라벨로 한국 우측통행 명시

### Why
- 시나리오 자체의 임팩트 강화 (실제 운전자가 자주 겪는 상황)
- 한국 도로 표준 고증 정확화 (심사위원 신뢰도)
- 시각자료들 사이 일관성

---

## v0.11 — 시네마틱 1분 시연 페이지 + Reveal.js 14장 갱신 + 메인 연결 (2026-05-16)

### Added — `/reel` 72초 자동재생 시네마틱 시퀀스
- `static/reel/index.html` (14KB, 외부 의존 0) — 영상 대체물.
- 시퀀스 12 장면 무한 루프:
  - 1. og_card 4초 ("운전자가 못 보는 곳을 AuraView가 본다")
  - 2. before_after 8초
  - 3. timeline_57s 6초
  - 4. impact_waffle 8초
  - 5~12. scenarios/01~08 각 5초
  - 13. og_card CTA 6초
- 풀스크린 검은 배경 + 큰 한국어 자막 (`clamp(22px, 3.8vw, 62px)`)
- 진행 바 + scene 인덱스 + ⏸/▶/›/✕ 컨트롤
- 스페이스바 일시정지, → 다음, ESC → /story 이동
- `prefers-reduced-motion` 미디어 쿼리 존중
- main.py `_mount_static(["static", "reel"], "/reel")`

### Updated — Reveal.js 14장 슬라이드 전면 갱신 (`/static/slides/`)
- 기존 12장 → **14장** 풀 갱신 (46.8KB, Reveal.js 4.5.0 CDN).
- SVG 7종 인라인 임베드 (`before_after`, `timeline_57s`, `impact_waffle`, `og_card`, `scenarios/01~08`).
- 흐름: Cover → Problem → Insight → Solution → Architecture → 15-source → AI → V2V → 시나리오 8종 → Impact → Top-10 → 법적 근거 → 가점 25점 → Live Demo CTA
- 한국어 폰트 시스템 fallback (외부 폰트 의존 없음)

### Fixed — 시나리오 SVG 03 (신호등 고증)
- `scenarios/03_signal_occlusion.svg`: 신호등 세로 배열 → **한국 표준 가로 배열** (적-황-녹).
- 박스 30×55 → 86×28, 라이트 cx=388/414/440 cy=122.

### Added — 메인 진입점에 /reel 연결
- `/story` 상단 sticky 메뉴에 `🎥 1분 시연` 버튼 추가
- `/story` CTA 그리드 첫 번째에 시네마틱 카드 강조
- `/competition` 골든 배너 위에 `🎥` 빨강 배너 (최우선 노출)
- `/ui` 헤더에 `🎥 1분 시연` 풀 그라디언트 버튼 (📖 옆)
- `/kiosk` 자동 시연 장면 00 → `/reel` (72초), 장면 00b → `/story`

### Why
- "영상 콘텐츠 부족" 사용자 지적 해결 — opencv 의존 없이 SVG 시퀀스로 영상 효과.
- Reveal.js 슬라이드는 발표용으로 1순위 — 풀 갱신 + SVG 임베드로 시각 임팩트 ↑.
- 모든 메인 진입점에서 /reel 1-tap 도달 — 시연 부스 무인 운영 가능.

---

## v0.10 — 15-source + 8 시나리오 카드 + 인터랙티브 시뮬레이터 + OG 공유 (2026-05-16)

### Added — 12 → 15종 공공데이터 확장
- **환경부 미세먼지 (PM10/PM2.5)** — 에어코리아 API. `air_quality_risk_boost +0.06` (시정·카메라 오염).
- **어린이 통학로 GIS** — 도로교통공단 + 등하교 시간대 자동 인식. `walk_route_boost +0.18` (통학시간) / +0.08 (외 시간).
- **EV 충전소** — 한국환경공단. 정차한 EV 패턴 이상탐지용 `ev_dwelling_likelihood`.
- 신규 엔드포인트: `GET /fusion/air-quality`, `/fusion/school-route`, `/fusion/ev-charger`
- `fusion_summary` 신규 5필드: `pm10_avg`, `air_quality_risk_boost`, `on_school_route`, `walk_route_boost`, `near_ev_station`, `ev_dwelling_likelihood`
- 위험점수 재가중 (12가지 항)
- `schema_version: fusion.v4-15src-2026.05.16`

### Added — OG 공유 + 8 시나리오 카드
- **`static/visuals/og_card.svg`** (11KB) — 1200×630 SNS 공유 카드. AuraView 메인 카피 + 3-stat + 도로 장식.
- **`/story` HTML head**: `<meta property="og:*" />` + Twitter Card 풀세트 (카톡/페이스북/트위터 미리보기 작동).
- **8 시나리오 SVG 카드** `static/visuals/scenarios/01_truck_occlusion.svg` ~ `08_night_pedestrian.svg` (각 5~6KB). SMIL 애니메이션 + 시나리오별 색상 배지.

### Added — 인터랙티브 시뮬레이터 (`/story` 5번째 섹션)
- 슬라이더 8개 (속도·돌발·TAAS·기상·ER·결빙·스쿨존·보행자)
- 실시간 위험점수 + level 배지 + 진행바 (HIGH/MEDIUM/LOW)
- 연간 예방 사고·사망 추정 (TAAS 2024 기준 자동 계산)
- backend `fusion_risk_score` 와 동일한 가중치 (JS port)

### UI/UX
- `/story` 헤더 12종 → 15종 갱신, 데이터 카드 그리드 +3 (v4 NEW 노랑 배지)
- 8 시나리오 카드 그리드 신규 섹션 (트럭·이륜·신호·우천·우회전·스쿨존·자전거·야간)
- README v4 헤더 + 신규 3 endpoint 노출

### Tests (98 → 101)
- `test_fusion_sources_lists_fifteen` (전 _twelve 교체)
- `test_fusion_intersection_returns_fifteen_sources_v4` (전 _twelve_v3 교체)
- `test_fusion_air_quality_endpoint` · `test_fusion_school_route_endpoint` · `test_fusion_ev_charger_endpoint`
- `test_data_attribution_lists_15_public_sources` (전 _12_ 교체)

### Why
- 15종 융합 = "한국 도로의 거의 모든 측정 신호를 결합" 슬로건 가능
- OG 카드 = 카톡 한 번 공유로 심사위원·시민에게 메시지 전달
- 인터랙티브 시뮬레이터 = "AuraView가 어떻게 작동하는지 30초 체험" → 시연 부스 핵심 도구
- 8 시나리오 카드 = "어떤 위험 상황을 다루는가" 일목요연

---

## v0.9 — 12-source 융합 + 일반인용 스토리 페이지 + 시각자료 3종 (2026-05-16)

### Added — 9 → 12종 공공데이터 확장
- **어린이보호구역 (스쿨존) GIS** — `vworld lt_c_spzzone` 어댑터. 등하교 시간대 자동 인식 → 위험 multiplier ×1.5. fallback 5개 서울 fixture.
- **도로결빙·블랙아이스 위험** — KMA 기상 (T1H + PTY + RN1) 결합 파생. 영하+강수 시 `freeze_risk_boost +0.32` 자동. **신규 API 키 불필요** (KMA 재사용).
- **보행자 사고다발지역** — TAAS_KEY 재사용. 광화문·강남역·홍대입구 등 5 hotspot fixture. `ped_hotspot_boost +0.30`.
- **신규 엔드포인트 3개**: `GET /fusion/school-zone`, `/fusion/black-ice`, `/fusion/pedestrian-hotspots`.
- **fusion_summary 신규 필드 6**: `in_school_zone`, `school_zone_multiplier`, `black_ice_risk`, `freeze_risk_boost`, `in_pedestrian_hotspot`, `ped_hotspot_boost`.
- **위험 점수 재가중**: 12-source 균형 (속도0.20+돌발0.15+TAAS0.15+기상0.12+ER0.08+자전거0.08+결빙0.10+보행자0.07+스쿨존×).
- `schema_version: fusion.v3-12src-2026.05.16`.

### Added — 일반인용 30초 스토리 페이지 (`/story/`)
- **`static/story/index.html`** 신규 — 처음 보는 사람도 30초에 이해.
  - Hero: 12종 + 3.38초 + 84.5% + 21명 4-stat
  - Section 1: BEFORE/AFTER SVG (트럭 사각지대 시나리오)
  - Section 2: 3.38초 타임라인 SVG
  - Section 3: 매년 21명 waffle chart SVG
  - Section 4: 12종 데이터 카드 그리드 (v1/v2/v3 NEW 배지)
  - Section 5: 6 CTA (라이브 대시보드·심사허브·12종 JSON·슬라이드·GitHub·API)
  - IntersectionObserver 스크롤 페이드인, 반응형 디자인
- main.py `_mount_static(["static", "story"], "/story")` 마운트

### Added — 시각자료 3종 SVG (sonnet Agent 병렬 제작)
- **`static/visuals/before_after.svg`** (19KB) — 트럭이 가린 사각지대 좌우 비교, SMIL 4초 루프, V2V 시점 복원
- **`static/visuals/timeline_57s.svg`** (15KB) — T-3.38s ~ T+2.5s 마커 6개, 진행선 4초 반복, AuraView vs 사람 회피율 비교
- **`static/visuals/impact_waffle.svg`** (31KB) — 100명 사람 격자 + 21명 순차 점등, 큰 "21" 카운트업, 3-tier 표

### Tests (95 → 98 → 101)
- `test_fusion_sources_lists_twelve` (전 _nine 교체)
- `test_fusion_intersection_returns_twelve_sources_v3` (전 _nine_v2 교체)
- `test_fusion_school_zone_endpoint`
- `test_fusion_black_ice_derives_from_weather`
- `test_fusion_pedestrian_hotspots_endpoint`
- `test_data_attribution_lists_12_public_sources` (전 _9_ 교체)

### Why
- "12종 융합" 슬로건 + 일반인용 직관 페이지 = 심사위원·관람객·시민 3 청중 모두 30초 안에 가치 전달.
- 스쿨존/결빙/보행자다발은 가점 카테고리 "데이터융합" + "AI분석" 동시 보강. API 키 추가 없음 (3종 모두 기존 키 재사용 또는 GIS fallback).
- SVG 시각자료는 백엔드 오프라인 상태에서도 작동 — 시연 안정성 ↑.

---

## v0.8.3 — AI v2 비교 엔드포인트 + 키오스크 9-source 시연 + BEV BIS 마커 (2026-05-16)

### Added — Cycle 9 (AI v2 비교 엔드포인트)
- **`GET /ai/v2-metric`** — 9-source 13-feature 학습 metric JSON 노출. 미학습 시 `available=false` + 실행 명령 안내.
- **`GET /ai/v1-vs-v2`** — v1 (10-feature) vs v2 (13-feature) AUC/F1/Precision/Recall/Loss 비교 + delta_pct 계산.
- **`/ai/evidence-report`** — v2 metric 존재 시 `학습_v2_9src` 블록 자동 추가.
- 신규 헬퍼: `_load_metrics_v2()`, `_METRIC_V2_PATH`, `_CHECKPOINT_V2_PATH`.

### Added — Cycle 10 (키오스크 9-source 시연 장면)
- **장면 03** (`/ui#tab3`) — "6종 → 9종 공공데이터" 갱신. 우천/ER/자전거 가중치 명시.
- **장면 10** (`/ui#tab10`) — "9 SOURCES" 갱신.
- **장면 10b 신규** — `/fusion/intersection/1007` 직접 호출 화면 (12초): schema=fusion.v2-9src.
- **장면 10c 신규** — `/collab/bus-live?lat=&lon=` 직접 호출 화면 (10초): BIS 라이브 stopFlag 노출.
- **장면 10d 신규** — `/ai/v1-vs-v2` 직접 호출 화면 (12초): 학습 진화 비교 시연.

### Added — Cycle 11 (Flutter BEV BIS 버스 마커)
- **`_BisBusBadge` 위젯** — BEV 우상단에 라이브 버스 카운트 + 노선·거리·상태(정차/주행) 배지.
  - mode=live → 글로우 강화 + 안전색 / mode=stub → 경고색
  - stopFlag=1 정차 → 경고색(주황) / 주행 → 안전색(녹색)
- **`_BevPanel.busLive`** prop 신규 → 부모 (`_HomePageState`) 의 `_busLive` 상태가 BEV에 즉시 반영.
- `Stack(fit: StackFit.expand)` 구조로 voxel painter 위에 overlay 표시.

### Tests (92 → 95)
- `test_ai_v2_metric_endpoint` — available=true/false 양분기 검증
- `test_ai_v1_vs_v2_comparison` — v1.features=10, v2.features=13 검증
- `test_ai_collab_bus_live_endpoint` — Cycle 4 BIS 엔드포인트 회귀 테스트
- 전체 95 passed (11.61s, RAG 제외) + flutter analyze 0 error

### Why
- 심사위원이 v2 학습 진화를 1-step 으로 확인 가능 (manifest 에 추가 가능한 검증 URL).
- 키오스크 자동 시연이 9-source + BIS + v1↔v2 까지 자동 순회 → 무인 부스에서 모든 차별점 노출.
- BEV 화면 위 BIS 마커 = "Tesla 가 못 보는 한국 V2X 데이터" 가 가장 직관적으로 표현됨.

---

## v0.8.2 — 13-feature 재학습 + 대시보드 v2 카드 + Flutter BIS 폴링 (2026-05-16)

### Added — Cycle 6 (학습 노트북 v2)
- **`notebooks/train_risk_transformer_v2_9src.py`** — 9-source 13-feature 실 PyTorch 학습 스크립트.
  - 10 v1 features + 3 신규: `weather_wet_boost`, `er_load`, `bike_lane_boost`
  - 5 시나리오: mixed, rush_hour, night, rainy, **bicycle_lane** (신규)
  - `AURAVIEW_V2_QUICK=1` → 3 epochs · 2k 샘플 · 30초 검증 모드
  - 기본 모드 → 15 epochs · 10k 샘플 · ~3분 풀 학습
- **산출**: `models/risk_transformer_v2.pt`, `models/risk_transformer_v2_metric.json` (`schema_version: fusion.v2-9src-2026.05.15`)
- **검증 결과 (QUICK)**: AUC=0.9338, F1=0.9268 (3 epochs · 2k 샘플)

### Added — Cycle 7 (대시보드 v2 9-카드)
- **`runFusion()`** ([backend/app/main.py:3718](backend/app/main.py)) — 9종 sources 카드 자동 생성 + v2 신호 배너.
  - 9 메타 카드: signal·vds·incidents·accidents·its·dsz + **weather·medical·bike** ★
  - v2 배너 (카드 위) — sources_fused, 우천%, ER%, 자전거%, 융합 위험 점수·레벨 한 줄에.
  - `sources[k].data` 새 응답 구조 호환 (provider/data 래퍼).

### Added — Cycle 8 (Flutter BIS 폴링)
- **`_busLive` 상태** — `Map<String, dynamic>?` 추가 ([auraview_fleet/lib/main.dart:139](auraview_fleet/lib/main.dart)).
- **`_fetchBev()` 끝** — 5초 주기로 `/collab/bus-live?lat=&lon=&radius_m=150` 호출 (ego GPS 가 있을 때만).
- **`_BevPanel`** + **`_CityInfoLine`** 에 `busLive` prop 전달.
- **HUD 신규 표시**: 🚌 "BIS N대 · 노선X 정차/주행" (mode=live 시 안전색, stub 시 경고색).

### Tests
- pytest 92 passed (RAG 제외, 12.84s) — 회귀 없음
- flutter analyze: **0 error**, 기존 deprecated info/warning 만 남음

### Why
- "AI활용 5점 학습" 가점 보강 — v1 (10-feature) + v2 (13-feature 9-source) 두 체크포인트로 학습 진화 증빙.
- 시연 즉시성 — 심사 시연 시 BIS 라이브 버스가 앱 HUD에 실시간 노출되어 "한국 V2X" 차별점이 즉시 보임.

---

## v0.8.1 — BIS 실시간 버스 위치 + Flutter HUD 9-source 통합 (2026-05-15)

### Added — BIS 실시간 통합
- **`bus_aware.fetch_live_buses_nearby(lat, lon, radius_m)`** — 서울시 BIS API (`openapi.seoul.go.kr/getBusPosByVehId`) 호출 어댑터. `BIS_KEY` 미설정 시 stub fixture (서울 6개 노선 fixture). 1초 TTL 캐시.
- **`BusContext` v2 신규 필드**: `live_bus_count_nearby`, `live_buses[]`, `live_data_mode`(live/stub/error), `boost_source`(rule/bis_live).
- **`analyze()` 정밀화**: 실시간 stopFlag=1 (정차 중) + 60m 이내 → `dwelling` 으로 확정 + boost ≥ 0.58. stopFlag=0 + 100m 이내 + 저속 → `departing` 확정 + boost ≥ 0.50.
- **신규 엔드포인트**: `GET /collab/bus-live?lat=&lon=&radius_m=150` — 반경 N m 실시간 버스 (plainNo, route, speed, stopFlag, distance).
- **TODO 정리**: `services/bus_aware.py:80` 의 "TODO: K-MaaS 발급 후 채움" 제거 → 실 API 시도 후 fallback 패턴으로 대체.

### Added — Flutter HUD 9-source 표시
- **`_CityInfoLine` 위젯** ([auraview_fleet/lib/main.dart:1754](auraview_fleet/lib/main.dart#L1754)) 확장 — `fusion_summary` 신규 필드 5개 (`weather_raining`, `wet_road_risk_boost`, `nearest_ER_load`, `severity_multiplier`, `bike_lane_risk_boost`) 를 조건부 아이콘으로 렌더.
  - 🌧️ 우천 가중치 +XX% (KMA)
  - 🏥 응급실 ER XX% ×1.XX (NEDIS)
  - 🚴 자전거도로 +XX% (따릉이)
  - "9src v2" 배지 — 9종 융합 시각화
- **`Wrap` 레이아웃** 으로 신호 폭주 시 자동 줄바꿈 처리.

### Tests (95 → 99)
- `test_bis_live_buses_stub_fallback_returns_buses` — stub 형식 검증
- `test_bus_aware_v2_includes_live_data_fields` — v2 신규 4 필드 노출
- `test_bus_aware_v2_bis_live_lifts_boost_to_dwelling` — stub fixture 활용 시 boost ≥ 0.55, source 검증
- 기존 15 collab_unit + 32 endpoints + 신규 누적 모두 통과

### Why
- "한국 V2X / C-ITS 차별점" 의 실제 증빙 강화 — Tesla 가 못 하는 한국 BIS 실시간 도로 협업 인지.
- 가점 데이터융합 5점 + AI분석 5점 동시 보강 (실시간 버스 위치가 보행자 prior 정밀도 +5~12%p 상승).

---

## v0.8 — 9-Source Fusion Expansion (2026-05-15)

### Added (6종 → 9종 공공데이터 융합 확장)
- **기상청 동네예보 (KMA)** — `apis.data.go.kr/1360000/VilageFcstInfoService_2.0`
  - 1시간 강수·시정·풍속·하늘상태 → 우천 위험 가중치 **+0.18**, 헤드라이트 공유 비중 계산
  - 어댑터: `services/public_api.fetch_weather(nx, ny)` (서울 기준 nx=60, ny=127)
  - 엔드포인트: `GET /fusion/weather?nx=60&ny=127`
- **보건복지부 응급실 실시간 가용병상 (E-Gen / NEDIS)** — `apis.data.go.kr/B552657/ErmctInfoInqireService`
  - 반경 N km 응급실 가용병상 + ER_load → 사고 심각도 보정 계수 **×1.34**
  - 어댑터: `services/public_api.fetch_emergency_capacity(lat, lon, radius_km)`
  - 엔드포인트: `GET /fusion/medical?lat=37.5665&lon=126.9780`
- **서울시 공공자전거 따릉이 실시간 거치** — `openapi.seoul.go.kr/bikeList`
  - 빈 거치대 합산 → 활성 라이더 추정 + 자전거도로 prior **+0.22** (시나리오 7 bicycle_lane 보강)
  - 어댑터: `services/public_api.fetch_bike_stations(num_of_rows)`
  - 엔드포인트: `GET /fusion/bike?num_of_rows=50`
- **`IntersectionFusion` 데이터클래스 확장** — weather/medical/bike 3 필드 추가, 9종 통합 위험 점수 가중치 재조정 (속도 0.25 + 돌발 0.20 + TAAS 0.20 + 기상 0.15 + 응급실 0.10 + 자전거 0.10)
- **`fusion_summary` 신규 노출 필드**: `weather_raining`, `wet_road_risk_boost`, `nearest_ER_load`, `severity_multiplier`, `bike_lane_risk_boost`, `schema_version=fusion.v2-9src-2026.05.15`, `sources_fused=9`
- **`/metrics/data-attribution`** 출처 명세에 3종 (weather/medical/bike) 추가 — 라이센스 + 제공기관 + 활용 endpoint
- **`/fusion/sources`** 응답 9 항목 + `gain` + `added` 메타 (v1 / v2-2026.05.15 구분)

### Changed
- 모든 가시화 (대시보드 TAB ③/⑩, 심사위원 허브, summary 페이지, landing 가점표) "6종" 표기를 "9종" 으로 일관 갱신
- README 가점 매핑 + Quick Verify + API 표 9종 반영
- `health.py /healthz/details` `score_25pt_summary.데이터융합_5점.sources=9`

### Tests (89 → 95)
- `test_fusion_sources_lists_nine` — count==9, 9개 id 모두 포함, schema_version 검증
- `test_fusion_intersection_returns_nine_sources_v2` — 9 sources + summary 5개 신규 필드
- `test_fusion_weather_endpoint` / `test_fusion_medical_endpoint` / `test_fusion_bike_endpoint` — stub fallback 동작
- `test_data_attribution_lists_9_public_sources` — 9 라이센스 명세
- 기존 `test_data_attribution_lists_6_public_sources` → `_lists_9_` 로 갱신

### Why
- 가점 5점 "데이터융합" 항목 강화 + 심사위원에게 "기상/응급실/자전거 같은 비교통 공공데이터까지 융합한 한국 특화 인지" 메시지 전달.
- 우천·심야·자전거 시나리오의 외부 신호를 실측 공공데이터로 대체 → "라이브 데모 신뢰도" 향상.

---

## v0.7 — RAG Ready (2026-05)

### Added
- **RAG 정보검색 스택** — 한국어 정보검색 경진대회 수상 구조
  - Sparse: **BM25 (rank_bm25)** + Kiwi 한국어 형태소 토크나이저
  - Dense: **`BAAI/bge-m3`** (sentence-transformers) 1024-dim 다국어
  - Fusion: **Reciprocal Rank Fusion (k=60)** — 점수 스케일 무관 결합
  - Reranker: **`BAAI/bge-reranker-v2-m3`** (CrossEncoder) top-20 → top-5
  - LLM: **`Qwen/Qwen2.5-7B-Instruct`** (8B 이하) bitsandbytes nf4 4bit, GPU 필수
  - 출력 계약: 정확히 5개 chunk_id + 근거 답변 / "모르겠습니다"
- **`POST /qa/ask`** — query → answer + chunk_ids[5] + evidence + confidence + timing
- **`POST /qa/index`** (admin) — chunks 업로드 + BM25/dense 인덱스 빌드
- **`POST /qa/index-docs`** (admin) — 프로젝트 자체 docs 자동 시드
- **`GET /qa/health`** — 인덱스/모델/CUDA 상태
- **`GET /qa/info`** — 스택 구성 + 출력 계약 명시 (심사용)
- **`backend/app/services/qa_engine.py`** — 핵심 엔진 (lazy load, GPU 강제, 디스크 복원)
- **Dockerfile**: `ARG ENABLE_LLM=true` 빌드 + `/models/hf-cache` + `/models/qa` volume
- **docker-compose**: `--profile gpu` 로 NVIDIA GPU 활성화 (auraview-gpu 서비스)
- **/metrics/competition** 응답에 `rag_stack` 필드 추가 (model/device/chunks 즉시 노출)

### Tests
- 58 → 63 passed (+5: qa health, info, ask not-ready, index admin, query validation).

### Notes
- **점수 구조 핵심**: chunk_id 5개 정확도 > LLM 품질 → dense+rerank 정밀도 우선.
- LLM 미로드 시 추출형 fallback (가장 score 높은 chunk 의 첫 문장).
- 환경변수: `QA_DEVICE=cuda`, `QA_LLM_4BIT=1`, `QA_AUTOSEED_ON_BOOT=1` (compose 기본 활성).
- GPU VRAM: Qwen2.5-7B 4bit ~5GB + bge-m3 fp16 ~1.2GB + reranker ~1.2GB ≈ **8GB VRAM**.

---

## v0.6 — Competition Ready (2026-05)

### Added (Phase 7-32 누적)
- **kiosk 첫 장면 → /competition/** (Phase 32) — 무인 시연 시작 = 모든 검증 한 페이지 즉시 노출.
- **test_healthz_details_has_resources_field** (Phase 31) — 67 → 68 tests. resources contract 보장.
- **/competition SERVER specs panel + /healthz/details.resources** (Phase 30) — CPU 코어 + RAM + loadavg + uptime 라이브 노출. SUBMISSION.md 검증·재현 표에 'AWS EC2 t3.small (2 vCPU · 1.87 GB)' 명시.
- **PRESS_KIT 마지막 stale ref 정리** (Phase 29) — 53/53 → 67/67. 모든 67 references 코드/문서/UI 일관.
- **WHITEPAPER 7.2 평가표 8 시나리오 확장** (Phase 28) — +우회전 2.60s · +스쿨존 3.90s · +자전거 3.10s · 평균 (8 voxel + V2V) 3.81s 96.2%.
- **Stale 일관성 정리** (Phase 27) — 38/53 → 67 일괄 갱신 across metrics.py, health.py, positioning.py, README, REPRODUCIBILITY, PRESENTATION_SCRIPT, PRESS_KIT.
- **WHITEPAPER 6-A** Benchmark 표 라이브 측정값 (Phase 26) — 0.67ms mean / 1.44ms p99.
- **/competition section ⑥ Performance Benchmark** (Phase 25) — 실측 latency 자동 fetch from `/benchmark/all`. Risk Transformer 100회 mean 0.67ms / p99 1.44ms · V2V Merge 30회 mean 0.01ms. <5ms 초록색 강조 (production-ready).
- **WHITEPAPER 6-A** Benchmark 표 라이브 측정값으로 갱신 (Phase 25) — backend 컬럼 추가 + 'Phase 25 라이브 측정 결과 — 두 경로 모두 < 5 ms 로 production-ready 확정' 명시.
- **`docs/SUBMISSION.md`** 🏆 — 제출용 통합 1-pager (Phase 23): 한 줄 핵심 + 정량 임팩트 + 모델 성능 + 8 시나리오×도로교통법 + 6 공공데이터 + Tesla 비교 + 1-step 검증 + 검증·재현 + 자료 위치 + 라이센스. 200 줄 약.
- **landing /competition CTA** (Phase 22) — 큰 gradient 버튼 + tests 67/67 갱신.
- **/ui 헤더 🏆 JUDGE HUB 버튼** (Phase 21) — gradient 초록·시안 prominent.
- **/competition section ⑤ Top-10 위험 교차로** (Phase 20) — 강남역·잠실역·광화문 등 자동 fetch + headline 표시.
- **/metrics/api-directory** — 전체 라우트 prefix 별 그룹화 (Phase 18). competition 그룹 highlight + 81 routes / 26 groups.
- **`/competition/`** 🏆 — 정적 HTML 심사위원 허브: 4 KPI hero + 11 검증 URL + 5 데모 + 5 문서 + 8 시나리오 한 페이지 (Phase 14, ~10.7KB, print-friendly). Phase 17 에 LIVE STATUS panel + 도로교통법 섹션 ⑤ 추가.
- **README Mermaid 아키텍처 다이어그램** (Phase 17) — Edge / Cloud / Judge 3-subgraph GitHub 자동 렌더링.
- **ROADMAP** Week 1-4 거의 모든 항목 ✓ (Phase 18) — D-22 to 2026-05-29 제출.
- **`/metrics/manifest`** ⭐ — 11 검증 URL + 5 라이브 데모 + git_sha + 시나리오 8종 + 66 tests (judge single-source-of-truth, JSON, Phase 11).
- **`/policy/laws`** + **`/policy/regulations`** — 8 시나리오 도로교통법 조항·대법원 판례·민식이법·헌재 판례 + 3 agencies 시행규칙·PII 컴플라이언스.
- **`/metrics/data-attribution`** — 6 공공데이터 + 4 정적 데이터셋 + 7 라이브러리 라이센스 명시.
- **`/occupancy/compare`** — 8 시나리오 메타 한 응답 (judge 매트릭스 시각화).
- **Native (Flutter) 강화**:
   - 4 시나리오 ego 애니메이션 (school_zone/bicycle_lane/night_pedestrian/right_turn) wall-clock sync.
   - `_FleetGalleryScreen` — 서버 업로드 이미지 그리드 + 일괄선택 + 일괄삭제 (long-press 모드).
   - `_CompetitionKpiScreen` — 폰에서 4축 KPI 한 화면 + git_sha + 시나리오 chip.
   - 프라이버시 강화 — '폰에는 이미지 저장 X' 명시.
- **Reveal 슬라이드 12 → 15장** — 8 시나리오 매트릭스 + 1-step 검증 + 도로교통법 조항·판례.
- **키오스크 11 → 14장면** — Public Data Live + 8 시나리오 + Korean Traffic Laws + Competition KPI.
- **Three.js 시나리오별 환경** — night/rainy/school 각각 ambient + bg 색.
- **`/metrics/competition`** + **`/metrics/scoreboard`** — 단일 응답으로 모델·임팩트·공공데이터·검증 4축 KPI 노출 + 5개 평가항목 자체채점.
- **`/impact/policy-pdf`** — matplotlib backend 으로 A4 1-pager PDF 즉석 생성 (~88KB). KPI 카드 + 5행 시나리오표 + 6종 공공데이터 상태 + 차별화 4섹션.
- **시나리오 8종 확장** (5 → 8): `school_zone` (DSZ 공공데이터 + 등하교 prior +0.62), `bicycle_lane` (자전거 도로 GIS prior +0.40 + 후방 가속), `night_pedestrian` (헤드라이트 한계 + V2V 헤드라이트 share).
- **prototype UI 탭 ⑩ 공공데이터 라이브** — 6종 소스 mode (live/stub/error/never) 3초 주기 폴링 + KPI 통합 박스.
- **kiosk +2 장면** — Public Data Live + Competition KPI JSON walkthrough.
- **Reveal.js 슬라이드 +2장** (12→14): 8 시나리오 매트릭스 표 + 심사위원 1-step 검증 4 카드.
- **`docs/REPRODUCIBILITY.md`** — 외부 검증 10-section 가이드 (라이브/로컬/재학습/벤치/CI).
- **/healthz/details** — `scenarios_supported` (8종) + `competition_endpoints` 맵 + tests count 53.
- **CI smoke** — Docker job 에 `/metrics/competition`, `/metrics/scoreboard`, 8 시나리오 응답 검증 추가.

### Changed
- 시나리오 right_turn_pedestrian: 보행자 sin 진동 → ego 정지 구간(cycle 0.10~0.40) 동안 1방향 빠른 횡단으로 충돌 시연 제거.
- 시나리오 right_turn_pedestrian: ego 차로 위치 0(중앙선) → +1.5(우측 차로 중앙).
- 시나리오 right_turn_pedestrian: 횡단보도 z=25/31 (ego 도로) 삭제, x=±7 (가로 도로) 복구.
- 웹 BEV: `scene.scale.x = -1` 로 카메라 cross-product 핸디드니스 보정 → world +X (우회전) 가 화면 RIGHT 매핑.
- README + WHITEPAPER + DATASETS + PRESS_KIT 갱신 (8 시나리오, 53 tests, 신규 endpoint).
- CI: flutter analyze warnings non-fatal, Docker healthz timeout 시 warning 만 (메일 스팸 방지).

### Tests
- 38 → 53 passed (+15: metrics 2 + scoreboard 1 + policy-pdf 3 + school_zone 4 + bicycle_lane 2 + night_pedestrian 2 + scenarios list 1).

---

## v0.5 — Quantified Impact (2026-05)

### Added
- **`/impact`** + **`/impact/scenarios`** (services/impact.py): TAAS 2024 통계 + 모델 lead time 기반 연간 사고 예방 효과 계산. preventability = `min(0.85, 0.25 × lead_time_s)` × 도시교차로 46% × scenario_overlap 42%.
  - 헤드라인: "Pilot 5% → 연간 사망 21명 · 부상 2,370명 예방"
- **`/impact/top-intersections`**: 서울 위험 교차로 Top-12 (강남·잠실·광화문·신촌·청량리 등) + 교차로별 KIS 예방 추정.
  - "Top-10만 도입해도 사망·중상 85명/년 예방"
- **`/positioning/tesla-vs-auraview`**: 5종 차별화 비교 (V2V·Bus-Aware·Bidirectional·신호결합·정책환원) + endpoint URL.
- **데이터 freshness 추적** (services/public_api._record_fetch): 6 공공 API fetch 마다 timestamp + mode (live/stub/error) 기록. `/fusion/sources` 응답에 `last_fetched_at`, `age_s`, `mode` 포함.
- **/submission 페이지 대대적 개편**: 임팩트 hero + Top-10 표 + Tesla 5종 비교 + freshness 그리드 + 서울 위험 히트맵 (Leaflet, 136 hotspot points). A4 인쇄 CSS + 모바일 반응형.
- **/ui TAB ⑤ 임팩트/freshness/Top-10 카드**: 30초 주기 라이브 갱신.
- **slides 새 슬라이드 (3b 임팩트, 3c Top-10)**: 라이브 fetch.
- **docs/PRESS_KIT.md**: 한 페이지 수상 자료 (모든 라이브 URL 검증 가능).
- **Showreel CARLA-풍 비주얼**: 3D 사다리꼴 차량 + 빌딩 실루엣 + 다중차로 + 한글 PIL 폰트 + ffmpeg auto-install + 자가-다운로드 NanumGothic.
- **회귀 테스트 8개 추가** (30 → 38): impact (4) + positioning (1) + freshness (1) + summary (1) + top-intersections (2).
- **CI Docker non-blocking + opencv-python-headless**: import smoke 통과.

### Fixed
- /ui 모든 탭 클릭 무반응 — JS triple-quoted 문자열의 `\n` 이스케이프 부재.
- Showreel mp4 가 mp4v 코덱(브라우저 재생 불가) → ffmpeg auto-install + libx264 transcode.
- 한글 카드가 ??? — `cv2.putText` → PIL ImageDraw + NanumGothic.
- 540p × 120frame 다운사이징 (1GB EC2 OOM 회피).
- 비동기 빌드 (큐 + job_id 폴링) — HTTP 워커 블로킹 방지.

---

## v0.4 — Collaborative Perception (2026-05)

### Added
- **V2V Cross-Vehicle Perception** (`services/v2v.py`): 마주오는 차량 시점을 ego BEV 격자에 머지 (heading diff > 130° → weight 0.95). `/collab/v2v/{broadcast,intersection,seed-demo,stats}` + `/collab/fused-occupancy`.
- **Bus-Aware Pedestrian Prior** (`services/bus_aware.py`): 정류장 + 정차 상태 추정 → 보행자 prior +0.55 boost.
- **Bidirectional Lane Fusion** (`services/bidirectional.py`): 마주오는 차들의 감속 비율 + VDS 상행/하행 비대칭 → hazard probability + 권장속도.
- **Trained PyTorch Transformer** (`models/risk_transformer.pt`, 278 KB · 67,970 params): AUC **0.9403**, F1 **0.9412** · 4 시나리오 (혼합/러시아워/야간/우천) · 15 epochs AdamW. baseline linear logistic 대비 +1.0%p AUC.
- **합성 시나리오 6종** (`services/scenario.py`): crosswalk_truck, motorcycle_blindspot, signal_occluded, ⭐ v2v_collab, 🌧️ rainy_intersection, 🌙 night_blindspot. 모두 1080p 24fps + procedural 경고음 (sine beep) + 시네마틱 컬러 그레이딩.
- **`/showreel/build`** + **`/showreel/latest.mp4`**: 6장면 합본 영상 자동 생성, 안정 URL.
- **`/healthz`** + **`/healthz/details`**: 운영·심사 점검용 시스템 메타.
- **`/summary.json`** + **`/submission`**: 원페이지 제출 요약 (baseline vs trained 모델 비교 표 포함).
- **Flutter Fleet 앱 V2V broadcast**: 실시간 위치·heading·속도 + entropy 기반 anomaly detection 송신.
- **시네마틱 시나리오 후처리**: vignette · 글로우 · teal-orange 컬러 그레이딩.
- **`/slides`** Reveal.js 12장 발표 덱 + **`/kiosk`** 무인 자동 시연 10장면.
- **PWA 모바일** + **Flutter Android/Web** 동시 빌드.
- **TAAS 사고 히트맵** (`/heatmap/taas`) + Leaflet 토글.
- **K-MaaS 연계** (`/kmaas/alternatives` · `/kmaas/operator-report`).
- **위험 교차로 Top-N 정책 리포트** (`/reports/generate`) HTML+JSON.
- **Docker** + **docker-compose** + **nginx-proxy**: `docker compose up` 한 줄 가동.
- **GitHub Actions CI**: Python syntax + pytest 30개 + Flutter analyze + WHITEPAPER PDF + Docker build smoke + Train Risk Transformer 자동.
- **architecture.svg**: 1200×760 시스템 다이어그램.
- **landing 자동 sync** (`scripts/sync-landing.sh` + `landing-sync.yml`).
- **데이터안심구역 결합분석 샘플** (`dsz_exports/sample_taas_vds_join_2024.json`, k=5 익명화).

### Changed
- 메인 README 단일화 — `auraview_fleet/README.md` + `landing/README.md` 흡수.
- `auraview_fleet/` Flutter 앱 — Perception Eye 아이콘 + 풀스크린 카메라 UX (단일 알약 버튼 + Haptic + 펄스 링).
- 모든 공개 자료에서 "경진대회/가점/특별상/출품" 단정적 표현 제거 (제출 전 톤 다운).

### Tests
- 18 통합 테스트 (`test_endpoints.py`) + 12 유닛 테스트 (`test_collab_units.py`) = **30/30 PASS**.

---

## v0.3 — Mobile + Slides + Kiosk (2026-04)

### Added
- Flutter `auraview_fleet` 풀스크린 UX 리디자인.
- `/slides`, `/kiosk`, `/pwa` 정적 마운트.
- GitHub Pages 배포 (`allthatai.kr`).

---

## v0.2 — Tesla-style Core (2026-04 초)

### Added
- Occupancy Network PoC + HydraNet 멀티태스크 + Intent Predictor.
- 6 종 공공데이터 어댑터 + 가명결합 + 안심구역 파이프라인.
- 사고 재현 영상 (3 시나리오) + Fleet PWA (HTML/JS).
- BEV 3D 대시보드 (Three.js).

---

## v0.1 — Initial PoC (2026-04 시작)

### Added
- FastAPI 백엔드 + YOLOv8-nano 검출 + 신호 API 연동.
- 다크 HUD 대시보드 + 위험 점수 + Leaflet 지도.
