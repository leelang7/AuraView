@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo === 1. flutter pub get ===
"C:\flutter\bin\flutter.bat" pub get
if errorlevel 1 goto :err

echo.
echo === 2. flutter build apk (release) ===
"C:\flutter\bin\flutter.bat" build apk --release --dart-define=AURAVIEW_API_BASE=https://auraview.allthatai.kr
if errorlevel 1 goto :err

echo.
echo === 3. APK location ===
dir build\app\outputs\flutter-apk\*.apk

echo.
echo === 4. adb install (connected device) ===
"C:\Users\leesc\AppData\Local\Android\Sdk\platform-tools\adb.exe" devices
"C:\Users\leesc\AppData\Local\Android\Sdk\platform-tools\adb.exe" install -r build\app\outputs\flutter-apk\app-release.apk
if errorlevel 1 goto :err

echo.
echo === DONE — open AuraView Fleet on your phone ===
goto :end

:err
echo.
echo === ERROR — see messages above ===

:end
pause
