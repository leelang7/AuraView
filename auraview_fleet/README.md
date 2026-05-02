# AuraView Fleet — Flutter Client

> Tesla-style **Shadow Mode** dashcam 기여 단말. AuraView 백엔드(`https://auraview.allthatai.kr`)
> 의 `/fleet/contribute` 엔드포인트로 어려운 장면(불확실성·움직임 큰 프레임)만 자동 업로드합니다.

| Platform | Status |
|---|---|
| Android | ✅ 빌드·실행 (Android 7.0 / API 24+) |
| iOS | 🛠️ 추가 작업 필요 (Mac + Xcode) |
| Web (PWA) | ✅ Chrome/Edge 데스크톱·모바일 (HTTPS 환경에서 카메라 작동) |

## 기능

- 카메라 라이브 프리뷰 + HUD chips (entropy / reason / GPS)
- **Shadow Mode**: 4초 주기 자동 캡처 → 임계치 초과만 업로드
- 수동 1장 기여 버튼
- 누적 captures / uploads / fails 카운터
- 디바이스 ID 자동 생성 (서버에서 HMAC 가명화)
- 위치 권한 허용 시 lat/lon 함께 전송

## 빌드 / 실행

### Android (실기기 또는 에뮬레이터)

```bash
cd auraview_fleet
flutter pub get
flutter devices                 # 연결된 기기 확인
flutter run -d <device_id>      # 디버그 실행

# 릴리스 APK
flutter build apk --release \
  --dart-define=AURAVIEW_API_BASE=https://auraview.allthatai.kr
# → build/app/outputs/flutter-apk/app-release.apk
```

### Web

```bash
flutter run -d chrome --web-port 5180 \
  --dart-define=AURAVIEW_API_BASE=https://auraview.allthatai.kr
```

> `--dart-define=AURAVIEW_API_BASE=...` 로 백엔드 주소를 바꿀 수 있습니다.
> 미지정시 `https://auraview.allthatai.kr` 기본값.

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
```

## TODO (다음 단계)

- [ ] `startImageStream()` 기반 실시간 onboard 추론 (현재는 `takePicture()` 주기형)
- [ ] TFLite 로 YOLOv8-nano 온디바이스 (확률 entropy 정밀화)
- [ ] iOS 빌드 (Mac 에서 `flutter create --platforms ios .` + Info.plist 권한)
- [ ] Background Service (foreground notification 으로 차량 운행 중 지속 캡처)
- [ ] HMAC 사인 헤더로 위변조 방지

## 백엔드 연동

이 클라이언트가 호출하는 엔드포인트는 AuraView 메인 리포에 정의:
- `routers/fleet.py` — POST /fleet/contribute (PII 마스킹 후 저장)
- `services/pii.py` — `pseudonymize()`, 얼굴·번호판 블러
