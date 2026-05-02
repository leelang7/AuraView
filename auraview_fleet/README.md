# AuraView Fleet — Flutter Client

> Tesla-style **Shadow Mode** dashcam 기여 단말. AuraView 백엔드(`https://auraview.allthatai.kr`)
> 의 `/fleet/contribute` 엔드포인트로 어려운 장면(불확실성·움직임 큰 프레임)만 자동 업로드합니다.
>
> **Monorepo 위치:** [github.com/leelang7/AuraView/tree/feat/k-perception/auraview_fleet](https://github.com/leelang7/AuraView/tree/feat/k-perception/auraview_fleet) — 백엔드 · Flutter · 랜딩 · 슬라이드 · 키오스크 모두 한 리포에서 관리.

| Platform | Status |
|---|---|
| Android | ✅ 빌드·실행 (Android 7.0 / API 24+) · APK 51MB |
| iOS | 🛠️ 추가 작업 필요 (Mac + Xcode) |
| Web (PWA) | ✅ Chrome/Edge 데스크톱·모바일 (HTTPS 환경에서 카메라 작동) |

## 기능

- **풀스크린 카메라 프리뷰** + 라디얼 비네트
- 상단 HUD: AuraView 로고 + 누적 카운터 + 연결 상태
- **단일 알약 버튼** — 탭=시작/정지, 길게 누르기=수동 1장 기여
- 위로 스와이프 시 상세 시트 (캡처 / 업로드 / 실패 / 서버 누적 4-tile + 마지막 entropy / reason)
- 캡처/업로드 시 cyan→safe 펄스 링 애니메이션 + Haptic 진동
- 디바이스 ID 자동 생성 (서버에서 HMAC 가명화)
- 위치 권한 허용 시 lat/lon 함께 전송
- 교차로 ID SharedPreferences 영속

## 빌드 / 실행

### Android (실기기 또는 에뮬레이터)

```bash
git clone https://github.com/leelang7/AuraView.git
cd AuraView/auraview_fleet
flutter pub get
flutter devices                 # 연결된 기기 확인
flutter run -d <device_id>      # 디버그 실행

# 릴리스 APK
flutter build apk --release \
  --dart-define=AURAVIEW_API_BASE=https://auraview.allthatai.kr
# → build/app/outputs/flutter-apk/app-release.apk

# adb 로 직접 폰에 설치
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

### Web

```bash
flutter run -d chrome --web-port 5180 \
  --dart-define=AURAVIEW_API_BASE=https://auraview.allthatai.kr
```

> `--dart-define=AURAVIEW_API_BASE=...` 로 백엔드 주소를 바꿀 수 있습니다.
> 미지정시 `https://auraview.allthatai.kr` 기본값.

### 앱 아이콘 재생성 (디자인 수정 시)

```bash
python tools/make_icons.py
# → android/app/src/main/res/mipmap-* (legacy + adaptive) 자동 갱신
# → web/icons/Icon-*.png · favicon.png 도 동시에 교체
```

## 권한

- **CAMERA** (필수): 프리뷰 + 캡처
- **INTERNET** (필수): 업로드
- **ACCESS_FINE_LOCATION** (선택): 위치 함께 보낼 때만

처음 실행하면 `permission_handler` 가 런타임 다이얼로그를 띄웁니다.

## 아키텍처

```
[ Flutter Camera ]
        │ takePicture (4초 주기)
        ▼
[ image package ]                ← decode → 64×64 grayscale
        │ entropy + motion 추정
        ▼
[ Threshold filter ]             entropy ≥ 0.55 || motion ≥ 0.7 → upload
        │
        ▼
[ http MultipartRequest ]        device_id + entropy + reason + (lat,lon) + JPEG
        │
        ▼
   POST https://auraview.allthatai.kr/fleet/contribute
                                    └─ 서버에서 PII 마스킹 + 가명화 → 저장
                                    └─ /collab/v2v/* 풀로도 분기 (TODO)
```

## TODO (다음 단계)

- [ ] **V2V broadcast 통합** — 폰이 자체 detection 을 `/collab/v2v/broadcast` 로 송신해 같은 교차로 다른 차량과 공유
- [ ] `startImageStream()` 기반 실시간 onboard 추론 (현재는 `takePicture()` 주기형)
- [ ] TFLite 로 YOLOv8-nano 온디바이스 (확률 entropy 정밀화)
- [ ] iOS 빌드 (Mac 에서 `flutter create --platforms ios .` + Info.plist 권한)
- [ ] Background Service (foreground notification 으로 차량 운행 중 지속 캡처)
- [ ] HMAC 사인 헤더로 위변조 방지

## 백엔드 연동

이 클라이언트가 호출하는 엔드포인트는 본 monorepo 의 `backend/` 에 정의:

- `backend/app/routers/fleet.py` — POST `/fleet/contribute` (PII 마스킹 후 저장)
- `backend/app/services/pii.py` — `pseudonymize()`, 얼굴·번호판 블러
- `backend/app/routers/collab.py` — V2V 차량간 협업 (Flutter 통합 예정)

향후 Flutter 앱이 `/collab/v2v/broadcast` 도 직접 호출하도록 확장 → **앱 한 번 빌드되면
같은 교차로 다른 AuraView 차량들과 자동 V2V 풀 형성**.
