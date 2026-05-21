# 네이티브 앱 화면 캡쳐 가이드

심사위원이 직접 디바이스에서 확인하거나, 수동으로 캡쳐해 README 에 첨부하는 절차.

## 자동 캡쳐 (디바이스 잠금 해제 상태에서)

```bash
# 1. 디바이스 깨우기 + 앱 실행
adb shell input keyevent KEYCODE_WAKEUP
adb shell monkey -p com.allthatai.auraview_fleet -c android.intent.category.LAUNCHER 1

# (사용자: 잠금 해제 + 권한 부여 + GPS 켜기)
# Galaxy Z Fold 3 메인 디스플레이 ID 는 dumpsys SurfaceFlinger --display-id 로 확인

# 2. 캡쳐 (메인 디스플레이 명시)
adb shell screencap -p /sdcard/auraview_hud.png
adb pull /sdcard/auraview_hud.png ./docs/screenshots/auraview_hud_$(date +%Y%m%d).png
```

## 캡쳐 권장 시점

심사 자료용 화면:
1. **메인 HUD** — 카메라 + BEV split + chip row (위험점수, 신호, VDS, TAAS, ER, 스쿨존, 단속존, 횡단보도 등)
2. **위치인식 stub 동작** — gps-* 모드 (집/임의 위치) — GPS 배지 + 활성 chip 없음
3. **단속존 진입 시** — 적색 "단속존 N대" chip + 횡단보도 50m 적색 알람
4. **스쿨존 등하교 시간대** — `스쿨존 ×1.5` chip + 스쿨횡단 N
5. **온보딩 첫 화면** — "23종 공공데이터와 V2V로 미리 알려주는 한국 도로 안전 AI"

## 파일 명명 규칙

- `auraview_hud_YYYYMMDD.png` — 메인 HUD 캡쳐
- `auraview_loc_unknown_YYYYMMDD.png` — 위치인식 stub 동작 증거
- `auraview_enforcement_YYYYMMDD.png` — 단속존 진입 시
- `auraview_schoolzone_YYYYMMDD.png` — 스쿨존 진입 시

## 자동화 한계

- ADB 로는 잠금 해제 불가 (PIN 입력 필요)
- 카메라/GPS 권한도 사용자 수동 부여 필요
- 따라서 심사 자료 캡쳐는 수동 시연 시 1회 진행 권장
