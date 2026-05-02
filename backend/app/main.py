from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import os

from .database import Base, engine
from .routers import (
    intersections, signals, events, risk, detect,
    occupancy, fleet, fusion, dsz, kmaas, reports, heatmap, collab,
)

# scenario / showreel 은 opencv 의존 — 없을 때 다른 탭까지 죽지 않도록 방어적 import
try:
    from .routers import scenario  # noqa: F401
    _SCENARIO_OK = True
except Exception as _exc:
    import logging
    logging.getLogger("auraview").warning(
        "scenario router disabled (install opencv-python to enable): %s", _exc
    )
    scenario = None
    _SCENARIO_OK = False

try:
    from .routers import showreel  # noqa: F401
    _SHOWREEL_OK = True
except Exception as _exc:
    showreel = None
    _SHOWREEL_OK = False

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AuraView — K-Perception Platform",
    description="테슬라식 Occupancy · HydraNet · Fleet Learning을 한국 도심 교차로에 이식한 안전 주행 지원 시스템",
    version="0.2.0",
)

# CORS — Flutter Web · 외부 데모 클라이언트가 직접 호출 가능하도록
# 운영 시 화이트리스트로 좁히려면 ALLOWED_ORIGINS 환경변수에 콤마 구분으로 지정.
_default_origins = [
    "https://auraview.allthatai.kr",
    "https://allthatai.kr",
    "http://localhost",
    "http://localhost:5180",
    "http://127.0.0.1",
    "http://127.0.0.1:5180",
]
_env_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
_allowed = [o.strip() for o in _env_origins.split(",") if o.strip()] if _env_origins else _default_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"],
    max_age=600,
)

# Core routers
app.include_router(intersections.router, prefix="/intersections", tags=["intersections"])
app.include_router(signals.router, prefix="/signals", tags=["signals"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(risk.router, prefix="/risk", tags=["risk"])
app.include_router(detect.router, prefix="/detect", tags=["detect"])

# K-Perception extensions
app.include_router(occupancy.router, prefix="/occupancy", tags=["occupancy"])
app.include_router(fleet.router, prefix="/fleet", tags=["fleet"])
app.include_router(fusion.router, prefix="/fusion", tags=["fusion"])
app.include_router(dsz.router, prefix="/dsz", tags=["dsz"])
app.include_router(kmaas.router, prefix="/kmaas", tags=["kmaas"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(heatmap.router, prefix="/heatmap", tags=["heatmap"])
app.include_router(collab.router, prefix="/collab", tags=["collab"])
if _SCENARIO_OK:
    app.include_router(scenario.router, prefix="/scenario", tags=["scenario"])
if _SHOWREEL_OK:
    app.include_router(showreel.router, prefix="/showreel", tags=["showreel"])

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# 발표 슬라이드 (Reveal.js) — repo의 static/slides 폴더 자동 탐색
def _mount_static(app, paths_relative_to_repo, mount_url):
    """repo의 정적 폴더를 위치 자동 탐색해서 마운트."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", *paths_relative_to_repo),
        os.path.join(os.getcwd(), *paths_relative_to_repo),
        os.path.join(os.getcwd(), "..", *paths_relative_to_repo),
    ]
    for cand in candidates:
        cand = os.path.abspath(cand)
        if os.path.isdir(cand):
            app.mount(mount_url, StaticFiles(directory=cand, html=True), name=mount_url.strip("/"))
            return True
    return False


_mount_static(app, ["static", "slides"], "/slides")
_mount_static(app, ["static", "kiosk"], "/kiosk")

# Mobile PWA at /pwa (repo root에 frontend_pwa/ 존재 가정)
_PWA_DIR_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend_pwa"),
    os.path.join(os.getcwd(), "frontend_pwa"),
    os.path.join(os.getcwd(), "..", "frontend_pwa"),
]
for cand in _PWA_DIR_CANDIDATES:
    cand = os.path.abspath(cand)
    if os.path.isdir(cand):
        app.mount("/pwa", StaticFiles(directory=cand, html=True), name="pwa")
        break


@app.get("/")
def root():
    return {"message": "AuraView Prototype Running"}


@app.get("/ui", response_class=HTMLResponse)
def prototype_ui():
    return """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover"/>
        <meta name="theme-color" content="#00c8ff"/>
        <meta name="description" content="AuraView K-Perception Platform — Tesla-style occupancy · fleet learning · end-to-end risk prediction · 한국 도심 협업 인지(V2V·Bus·Bidirectional)."/>

        <!-- Open Graph -->
        <meta property="og:type" content="website"/>
        <meta property="og:title" content="AuraView · K-Perception"/>
        <meta property="og:description" content="한국 도심에 이식한 Tesla FSD — 보이지 않는 신호와 공간을 확률로 복원해 사고를 평균 5.7초 먼저 경고합니다."/>
        <meta property="og:url" content="https://auraview.allthatai.kr/ui"/>
        <meta property="og:site_name" content="AuraView"/>
        <meta name="twitter:card" content="summary_large_image"/>
        <meta name="twitter:title" content="AuraView · K-Perception"/>
        <meta name="twitter:description" content="한국 도심에 이식한 Tesla FSD"/>

        <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3CradialGradient id='g' cx='50%25' cy='45%25' r='60%25'%3E%3Cstop offset='0%25' stop-color='%2300d8ff'/%3E%3Cstop offset='100%25' stop-color='%23080c14'/%3E%3C/radialGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='14' fill='url(%23g)'/%3E%3Cpath d='M14 42 Q32 18 50 42' stroke='%23e2eaf5' stroke-width='3' fill='none' stroke-linecap='round'/%3E%3Ccircle cx='32' cy='36' r='5' fill='%2300c8ff' stroke='%23e2eaf5' stroke-width='1.5'/%3E%3C/svg%3E"/>
        <title>AuraView · K-Perception</title>

        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.147.0/build/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=JetBrains+Mono:wght@400;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap');

            :root {
              --bg: #080c14;
              --surface: #0d1520;
              --surface2: #121d2e;
              --surface3: #172035;
              --border: rgba(0, 200, 255, 0.10);
              --border2: rgba(0, 200, 255, 0.20);
              --text: #e2eaf5;
              --muted: #5a7a9a;
              --accent: #00c8ff;
              --accent-dim: rgba(0, 200, 255, 0.12);
              --accent2: #7c3aed;
              --danger: #ff3b3b;
              --danger-dim: rgba(255, 59, 59, 0.12);
              --warn: #ffb020;
              --warn-dim: rgba(255, 176, 32, 0.12);
              --safe: #00e09a;
              --safe-dim: rgba(0, 224, 154, 0.12);
              --glow-accent: 0 0 20px rgba(0, 200, 255, 0.25);
              --glow-danger: 0 0 20px rgba(255, 59, 59, 0.30);
              --glow-safe: 0 0 20px rgba(0, 224, 154, 0.25);
              --shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            }

            * { box-sizing: border-box; margin: 0; padding: 0; }

            body {
              background: var(--bg);
              color: var(--text);
              font-family: 'Noto Sans KR', sans-serif;
              min-height: 100vh;
              overflow-x: hidden;
            }

            body::before {
              content: '';
              position: fixed; inset: 0;
              background-image:
                radial-gradient(ellipse at 10% 40%, rgba(0,200,255,0.04) 0%, transparent 55%),
                radial-gradient(ellipse at 90% 10%, rgba(124,58,237,0.04) 0%, transparent 55%),
                radial-gradient(ellipse at 50% 90%, rgba(0,224,154,0.02) 0%, transparent 50%);
              pointer-events: none;
              z-index: 0;
            }

            /* ── TOAST ── */
            #toast-container {
              position: fixed;
              top: 20px; right: 20px;
              z-index: 9999;
              display: flex;
              flex-direction: column;
              gap: 10px;
            }

            .toast {
              display: flex;
              align-items: center;
              gap: 10px;
              padding: 12px 18px;
              border-radius: 12px;
              font-size: 13px;
              font-weight: 600;
              backdrop-filter: blur(12px);
              border: 1px solid;
              animation: toastIn .25s ease forwards;
              max-width: 340px;
            }

            .toast.info    { background: rgba(0,200,255,0.10); border-color: rgba(0,200,255,0.30); color: var(--accent); }
            .toast.success { background: rgba(0,224,154,0.10); border-color: rgba(0,224,154,0.30); color: var(--safe); }
            .toast.error   { background: rgba(255,59,59,0.10);  border-color: rgba(255,59,59,0.30);  color: var(--danger); }
            .toast.warn    { background: rgba(255,176,32,0.10); border-color: rgba(255,176,32,0.30); color: var(--warn); }

            @keyframes toastIn  { from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:none; } }
            @keyframes toastOut { from { opacity:1; } to { opacity:0; transform:translateX(20px); } }

            /* ── LOADER ── */
            .loader-overlay {
              display: none;
              position: fixed; inset: 0;
              background: rgba(8,12,20,0.75);
              backdrop-filter: blur(4px);
              z-index: 1000;
              align-items: center;
              justify-content: center;
              flex-direction: column;
              gap: 16px;
            }

            .loader-overlay.active { display: flex; }

            .loader-ring {
              width: 52px; height: 52px;
              border-radius: 50%;
              border: 3px solid var(--surface3);
              border-top-color: var(--accent);
              animation: spin .75s linear infinite;
            }

            @keyframes spin { to { transform: rotate(360deg); } }

            .loader-text {
              font-family: 'JetBrains Mono', monospace;
              font-size: 12px;
              letter-spacing: 3px;
              color: var(--accent);
            }

            /* ── HEADER ── */
            header {
              padding: 28px 44px 22px;
              border-bottom: 1px solid var(--border);
              background: rgba(13,21,32,0.95);
              backdrop-filter: blur(12px);
              position: sticky;
              top: 0;
              z-index: 200;
            }

            .header-inner {
              max-width: 1480px;
              margin: 0 auto;
              display: flex;
              align-items: center;
              justify-content: space-between;
            }

            .header-left {}

            .eyebrow {
              font-family: 'JetBrains Mono', monospace;
              font-size: 10px;
              letter-spacing: 4px;
              color: var(--accent);
              text-transform: uppercase;
              margin-bottom: 8px;
              opacity: 0.8;
            }

            h1 {
              font-family: 'Black Han Sans', sans-serif;
              font-size: 38px;
              line-height: 1;
              margin-bottom: 6px;
              letter-spacing: -0.5px;
            }

            h1 em {
              color: var(--accent);
              font-style: normal;
              text-shadow: 0 0 30px rgba(0,200,255,0.5);
            }

            .subtitle {
              font-size: 13px;
              color: var(--muted);
              letter-spacing: 0.2px;
            }

            .header-badge {
              display: flex;
              align-items: center;
              gap: 8px;
              padding: 8px 16px;
              background: var(--safe-dim);
              border: 1px solid rgba(0,224,154,0.25);
              border-radius: 30px;
              font-family: 'JetBrains Mono', monospace;
              font-size: 11px;
              color: var(--safe);
              letter-spacing: 1px;
            }

            .header-badge .dot {
              width: 7px; height: 7px;
              border-radius: 50%;
              background: var(--safe);
              box-shadow: 0 0 8px var(--safe);
              animation: pulse-dot 2s ease-in-out infinite;
            }

            @keyframes pulse-dot {
              0%, 100% { opacity: 1; transform: scale(1); }
              50%       { opacity: 0.5; transform: scale(0.8); }
            }

            /* ── TABS ── */
            .tabs {
              padding: 0 44px;
              border-bottom: 1px solid var(--border);
              background: rgba(13,21,32,0.90);
              backdrop-filter: blur(8px);
              overflow-x: auto;
            }

            .tabs-inner {
              max-width: 1480px;
              margin: 0 auto;
              display: flex;
            }

            .tab {
              padding: 14px 20px;
              font-size: 12px;
              font-family: 'JetBrains Mono', monospace;
              font-weight: 600;
              letter-spacing: 1px;
              border-bottom: 2px solid transparent;
              color: var(--muted);
              white-space: nowrap;
              cursor: pointer;
              transition: color .2s, border-color .2s;
              user-select: none;
            }

            .tab:hover { color: var(--text); }

            .tab.active {
              color: var(--accent);
              border-bottom-color: var(--accent);
            }

            /* ── CONTENT ── */
            .content {
              max-width: 1480px;
              margin: 0 auto;
              padding: 24px 44px 40px;
              position: relative;
              z-index: 1;
            }

            .tab-panel { display: none; }
            .tab-panel.active { display: block; }

            /* ── GRID ── */
            .dashboard-grid {
              display: grid;
              grid-template-columns: 420px minmax(0, 1fr);
              gap: 18px;
              align-items: start;
            }

            .left-col {
              display: grid;
              gap: 18px;
              min-width: 0;
            }

            .right-col {
              display: grid;
              grid-template-rows: 560px auto;
              gap: 18px;
              min-width: 0;
            }

            /* ── CARD ── */
            .card {
              background: var(--surface);
              border: 1px solid var(--border);
              border-radius: 16px;
              padding: 22px;
              position: relative;
              box-shadow: var(--shadow);
              transition: border-color .2s;
            }

            .card:hover { border-color: var(--border2); }

            .card-tag {
              position: absolute;
              top: -11px; left: 20px;
              font-family: 'JetBrains Mono', monospace;
              font-size: 9px;
              letter-spacing: 2.5px;
              padding: 3px 12px;
              border-radius: 4px;
              color: var(--bg);
              background: var(--accent);
              text-transform: uppercase;
            }

            .section-label {
              font-family: 'JetBrains Mono', monospace;
              font-size: 10px;
              letter-spacing: 3px;
              color: var(--muted);
              text-transform: uppercase;
              margin-bottom: 16px;
              padding-bottom: 10px;
              border-bottom: 1px solid var(--border);
            }

            /* ── HERO COPY ── */
            .hero-copy {
              margin-top: 14px;
              padding: 16px 18px;
              border-radius: 12px;
              background: linear-gradient(135deg, rgba(0,200,255,0.07), rgba(124,58,237,0.04));
              border: 1px solid rgba(0,200,255,0.14);
            }

            .hero-title {
              font-size: 16px;
              font-weight: 900;
              margin-bottom: 6px;
              color: var(--text);
            }

            .hero-desc {
              font-size: 12.5px;
              color: var(--muted);
              line-height: 1.75;
            }

            /* ── FORM ── */
            .form-grid {
              display: grid;
              gap: 12px;
              margin-top: 18px;
            }

            label {
              display: block;
              font-size: 11px;
              font-weight: 700;
              font-family: 'JetBrains Mono', monospace;
              letter-spacing: 1px;
              color: var(--muted);
              text-transform: uppercase;
              margin-bottom: 6px;
            }

            input, select {
              width: 100%;
              border-radius: 10px;
              border: 1px solid var(--border);
              background: var(--surface2);
              color: var(--text);
              font-family: 'Noto Sans KR', sans-serif;
              font-size: 13px;
              padding: 11px 14px;
              transition: border-color .2s, box-shadow .2s;
            }

            input:focus, select:focus {
              outline: none;
              border-color: var(--accent);
              box-shadow: 0 0 0 3px rgba(0,200,255,0.10);
            }

            select option { background: var(--surface2); }

            /* custom file input */
            .file-label {
              display: flex;
              align-items: center;
              gap: 10px;
              width: 100%;
              border-radius: 10px;
              border: 1px dashed var(--border2);
              background: var(--surface2);
              color: var(--muted);
              font-size: 12px;
              padding: 11px 14px;
              cursor: pointer;
              transition: border-color .2s, color .2s;
            }

            .file-label:hover { border-color: var(--accent); color: var(--accent); }
            .file-label.has-file { border-color: rgba(0,224,154,0.35); color: var(--safe); }

            input[type=file] { display: none; }

            /* ── BUTTONS ── */
            button {
              width: 100%;
              border: none;
              border-radius: 10px;
              cursor: pointer;
              color: #fff;
              font-family: 'Noto Sans KR', sans-serif;
              font-size: 13px;
              font-weight: 700;
              padding: 12px 16px;
              transition: transform .15s ease, box-shadow .15s ease, opacity .15s ease;
              position: relative;
              overflow: hidden;
            }

            button::after {
              content: '';
              position: absolute;
              inset: 0;
              background: rgba(255,255,255,0);
              transition: background .15s;
            }

            button:hover::after { background: rgba(255,255,255,0.07); }
            button:active { transform: scale(0.98); }

            .btn-default  { background: var(--surface3); border: 1px solid var(--border); color: var(--text); }
            .btn-default:hover { border-color: var(--border2); }

            .btn-secondary { background: #1c2840; border: 1px solid var(--border); color: var(--text); }
            .btn-secondary:hover { border-color: var(--border2); }

            .btn-accent {
              background: linear-gradient(135deg, #0078a8, #005580);
              border: 1px solid rgba(0,200,255,0.3);
              box-shadow: 0 0 16px rgba(0,200,255,0.12);
            }
            .btn-accent:hover { box-shadow: var(--glow-accent); }

            .btn-danger {
              background: linear-gradient(135deg, #8b0000, #5c0000);
              border: 1px solid rgba(255,59,59,0.3);
              box-shadow: 0 0 16px rgba(255,59,59,0.10);
            }
            .btn-danger:hover { box-shadow: var(--glow-danger); }

            .btn-video {
              background: linear-gradient(135deg, #1a0a3a, #120826);
              border: 1px solid rgba(124,58,237,0.3);
            }

            .btn-row {
              display: grid;
              grid-template-columns: 1fr 1fr;
              gap: 10px;
            }

            /* ── STATUS BOX ── */
            .status {
              border-radius: 14px;
              padding: 18px 20px;
              margin-top: 16px;
              border: 1px solid var(--border);
              background: var(--surface2);
              transition: background .3s, border-color .3s, box-shadow .3s;
            }

            .status.warning {
              background: var(--danger-dim);
              border-color: rgba(255,59,59,0.30);
              box-shadow: var(--glow-danger);
            }

            .status.safe {
              background: var(--safe-dim);
              border-color: rgba(0,224,154,0.28);
              box-shadow: var(--glow-safe);
            }

            .status.info {
              background: var(--accent-dim);
              border-color: rgba(0,200,255,0.28);
              box-shadow: var(--glow-accent);
            }

            .status-title {
              font-family: 'JetBrains Mono', monospace;
              font-size: 10px;
              letter-spacing: 3px;
              color: var(--muted);
              margin-bottom: 8px;
            }

            .status.warning .status-title { color: var(--danger); }
            .status.safe    .status-title { color: var(--safe); }
            .status.info    .status-title { color: var(--accent); }

            .status-main {
              font-size: 24px;
              font-weight: 900;
              line-height: 1.25;
              margin-bottom: 8px;
            }

            .status-meta {
              font-family: 'JetBrains Mono', monospace;
              font-size: 11.5px;
              color: var(--muted);
              line-height: 2;
            }

            /* ── PREVIEW ── */
            .preview-wrap {
              margin-top: 10px;
              height: 480px;
              border: 1px solid var(--border);
              border-radius: 12px;
              overflow: auto;
              background: var(--surface2);
            }

            .preview-single {
              width: 100%;
              height: 100%;
              object-fit: cover;
              display: block;
            }

            .placeholder {
              height: 100%;
              min-height: 120px;
              display: flex;
              align-items: center;
              justify-content: center;
              color: var(--muted);
              font-size: 13px;
              text-align: center;
              padding: 24px;
              flex-direction: column;
              gap: 10px;
            }

            .placeholder-icon {
              font-size: 32px;
              opacity: 0.3;
            }

            /* ── MAP ── */
            .map-card {
              background: var(--surface);
              border: 1px solid var(--border);
              border-radius: 16px;
              overflow: hidden;
              box-shadow: var(--shadow);
              position: relative;
            }

            .map-header {
              position: absolute;
              z-index: 500;
              top: 14px; left: 14px;
              padding: 10px 14px;
              background: rgba(13,21,32,0.90);
              backdrop-filter: blur(10px);
              border: 1px solid var(--border2);
              border-radius: 12px;
              box-shadow: var(--shadow);
            }

            .map-header .k {
              font-family: 'JetBrains Mono', monospace;
              font-size: 9px;
              letter-spacing: 2.5px;
              color: var(--accent);
              margin-bottom: 3px;
            }

            .map-header .v {
              font-size: 13px;
              font-weight: 800;
            }

            #map {
              width: 100%;
              height: 100%;
              min-height: 560px;
              filter: brightness(0.9) saturate(0.85);
            }

            /* ── RANKING ── */
            .ranking {
              display: grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap: 10px;
              margin-top: 8px;
            }

            .rank-item {
              background: var(--surface2);
              border: 1px solid var(--border);
              border-radius: 12px;
              padding: 14px 16px;
              border-left: 3px solid var(--safe);
              transition: border-color .2s, box-shadow .2s;
            }

            .rank-item:hover { border-color: var(--border2); }
            .rank-item.high { border-left-color: var(--danger); }
            .rank-item.mid  { border-left-color: var(--warn); }

            .rank-head {
              display: flex;
              justify-content: space-between;
              align-items: flex-start;
              gap: 8px;
              margin-bottom: 8px;
            }

            .rank-title {
              font-family: 'JetBrains Mono', monospace;
              font-size: 12px;
              font-weight: 700;
              line-height: 1.4;
              color: var(--text);
            }

            .badge {
              display: inline-block;
              padding: 3px 8px;
              border-radius: 5px;
              font-size: 10px;
              font-family: 'JetBrains Mono', monospace;
              font-weight: 700;
              flex-shrink: 0;
            }

            .b-g { background: var(--safe-dim);   color: var(--safe);   border: 1px solid rgba(0,224,154,0.25); }
            .b-y { background: var(--warn-dim);   color: var(--warn);   border: 1px solid rgba(255,176,32,0.25); }
            .b-r { background: var(--danger-dim); color: var(--danger); border: 1px solid rgba(255,59,59,0.25); }

            .rank-body {
              font-family: 'JetBrains Mono', monospace;
              font-size: 11px;
              color: var(--muted);
              line-height: 1.9;
            }

            /* ── VIDEO REPORT ── */
            .video-report {
              width: 100%;
              min-height: 100%;
              padding: 18px;
              background: var(--surface2);
            }

            .video-summary {
              padding: 16px 18px;
              border: 1px solid var(--border);
              border-radius: 12px;
              background: var(--surface3);
              margin-bottom: 14px;
            }

            .summary-kicker {
              font-family: 'JetBrains Mono', monospace;
              font-size: 9px;
              letter-spacing: 3px;
              color: var(--accent);
              margin-bottom: 8px;
            }

            .summary-title {
              font-size: 20px;
              font-weight: 900;
              margin-bottom: 12px;
            }

            .summary-metrics {
              display: grid;
              grid-template-columns: repeat(3, 1fr);
              gap: 10px;
            }

            .metric {
              background: var(--surface);
              border: 1px solid var(--border);
              border-radius: 10px;
              padding: 12px;
            }

            .metric span {
              display: block;
              font-family: 'JetBrains Mono', monospace;
              font-size: 10px;
              color: var(--muted);
              margin-bottom: 6px;
            }

            .metric strong {
              font-size: 22px;
              font-weight: 900;
              color: var(--text);
            }

            .video-grid { display: grid; gap: 14px; }

            .video-shot {
              border: 1px solid var(--border);
              border-radius: 12px;
              padding: 14px;
              background: var(--surface3);
            }

            .shot-label {
              font-family: 'JetBrains Mono', monospace;
              font-size: 12px;
              font-weight: 700;
              margin-bottom: 10px;
              color: var(--accent);
            }

            .shot-compare {
              display: grid;
              grid-template-columns: 1fr 1fr;
              gap: 10px;
            }

            .shot-box {
              border: 1px solid var(--border);
              border-radius: 10px;
              overflow: hidden;
              background: var(--surface2);
            }

            .shot-tag {
              font-family: 'JetBrains Mono', monospace;
              font-size: 10px;
              font-weight: 700;
              letter-spacing: 1px;
              color: var(--muted);
              padding: 7px 10px;
              border-bottom: 1px solid var(--border);
              background: var(--surface);
            }

            .shot-box img {
              width: 100%;
              height: 210px;
              object-fit: cover;
              display: block;
            }

            /* ── PANEL 2 & 3 ── */
            .panel-placeholder {
              display: flex;
              align-items: center;
              justify-content: center;
              height: 400px;
              border: 1px dashed var(--border2);
              border-radius: 16px;
              color: var(--muted);
              font-family: 'JetBrains Mono', monospace;
              font-size: 13px;
              letter-spacing: 1px;
            }

            /* ── RESPONSIVE ── */
            @media (max-width: 1180px) {
              .dashboard-grid { grid-template-columns: 1fr; }
              .right-col { grid-template-rows: auto; }
              .ranking, .summary-metrics, .shot-compare { grid-template-columns: 1fr; }
              #map { min-height: 420px; }
              .preview-wrap { height: auto; min-height: 320px; }
              header, .tabs, .content { padding-left: 20px; padding-right: 20px; }
              h1 { font-size: 28px; }
              .header-badge { display: none; }
            }

            /* ── LEAFLET DARK POPUP ── */
            .leaflet-popup-content-wrapper {
              background: var(--surface) !important;
              border: 1px solid var(--border2) !important;
              border-radius: 12px !important;
              color: var(--text) !important;
              box-shadow: var(--shadow) !important;
            }

            .leaflet-popup-tip { background: var(--surface) !important; }

            .popup-body { font-family: 'JetBrains Mono', monospace; font-size: 11px; line-height: 2; }
            .popup-id { font-size: 13px; font-weight: 800; margin-bottom: 4px; color: var(--accent); }

            .leaflet-control-zoom a {
              background: var(--surface2) !important;
              border-color: var(--border2) !important;
              color: var(--text) !important;
            }
        </style>
    </head>
    <body>

        <div id="toast-container"></div>
        <div class="loader-overlay" id="loader">
          <div class="loader-ring"></div>
          <div class="loader-text">ANALYZING...</div>
        </div>

        <!-- Boot splash: 첫 페이지 진입 임팩트 -->
        <div id="bootSplash" style="position:fixed;inset:0;background:radial-gradient(ellipse at center, #08121e 0%, #04070d 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;z-index:9999;transition:opacity .8s;">
          <div style="position:relative;width:88px;height:88px;">
            <div style="position:absolute;inset:0;border-radius:50%;border:3px solid rgba(0,200,255,0.18);border-top-color:#00c8ff;animation:bootspin 1.1s linear infinite;"></div>
            <div style="position:absolute;inset:14px;border-radius:50%;border:2px solid rgba(124,58,237,0.25);border-bottom-color:#7c3aed;animation:bootspin 1.7s linear infinite reverse;"></div>
          </div>
          <div style="font-family:'Black Han Sans',sans-serif;font-size:34px;letter-spacing:-0.5px;">
            Aura<em style="font-style:normal;background:linear-gradient(135deg,#00c8ff,#7c3aed);-webkit-background-clip:text;background-clip:text;color:transparent;">View</em>
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:5px;color:#5a7a9a;">K-PERCEPTION · BOOTING…</div>
          <style>@keyframes bootspin { to { transform: rotate(360deg); } }</style>
        </div>
        <script>
          window.addEventListener('load', () => {
            setTimeout(() => {
              const s = document.getElementById('bootSplash');
              if (s) { s.style.opacity = '0'; setTimeout(() => s.remove(), 900); }
            }, 700);
          });
        </script>

        <header>
          <div class="header-inner">
            <div class="header-left">
              <div class="eyebrow">AuraView · Prototype v0.1</div>
              <h1><em>AuraView</em> Dashboard</h1>
              <div class="subtitle">보이지 않는 신호를 대신 보여주는 시야 차단 대응형 안전 주행 보조 시스템</div>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
              <a href="/slides/" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:var(--accent);padding:7px 14px;border:1px solid rgba(0,200,255,0.3);border-radius:99px;">▶ SLIDES</a>
              <a href="/kiosk/" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:var(--accent2);padding:7px 14px;border:1px solid rgba(124,58,237,0.4);border-radius:99px;">⏵ KIOSK</a>
              <div class="header-badge">
                <div class="dot"></div>
                SYSTEM ONLINE
              </div>
            </div>
          </div>
        </header>

        <div class="tabs">
          <div class="tabs-inner">
            <div class="tab active" data-tab="tab1">① AuraView 데모</div>
            <div class="tab" data-tab="tab2">② BEV Occupancy</div>
            <div class="tab" data-tab="tab3">③ 데이터 융합</div>
            <div class="tab" data-tab="tab4">④ Fleet Learning</div>
            <div class="tab" data-tab="tab5">⑤ Capability Matrix</div>
            <div class="tab" data-tab="tab6">⑥ 사고 재현</div>
            <div class="tab" data-tab="tab7">⑦ K-MaaS 연계</div>
            <div class="tab" data-tab="tab8">⑧ 정책 리포트</div>
            <div class="tab" data-tab="tab9">⑨ V2V 협업 인지</div>
          </div>
        </div>

        <div class="content">

          <!-- TAB 1 -->
          <div class="tab-panel active" id="tab1">
            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card control-card">
                  <div class="card-tag">FIELD INPUT</div>
                  <div class="section-label">// 현장 입력</div>

                  <div class="hero-copy">
                    <div class="hero-title">보이지 않는 신호를 대신 보여준다</div>
                    <div class="hero-desc">현장 이미지·영상과 공공 신호정보를 결합해, 앞차나 대형차에 가려진 신호 상황을 감지하고 즉시 대체 안내합니다.</div>
                  </div>

                  <div class="form-grid">
                    <div>
                      <label>교차로 선택</label>
                      <select id="intersection_id"></select>
                    </div>

                    <div class="btn-row">
                      <div>
                        <label>사용자 위도</label>
                        <input id="user_lat" type="number" step="0.000001" placeholder="37.566535"/>
                      </div>
                      <div>
                        <label>사용자 경도</label>
                        <input id="user_lon" type="number" step="0.000001" placeholder="126.977969"/>
                      </div>
                    </div>

                    <div class="btn-row">
                      <div>
                        <label>지속시간 (초)</label>
                        <input id="duration" type="number" step="0.1" value="3.5"/>
                      </div>
                      <div>
                        <label>장애물 유형</label>
                        <select id="obstacle_type">
                          <option value="truck">truck</option>
                          <option value="bus">bus</option>
                          <option value="top_truck">top_truck</option>
                          <option value="van">van</option>
                          <option value="unknown_vehicle">unknown_vehicle</option>
                        </select>
                      </div>
                    </div>

                    <div>
                      <label>현장 이미지</label>
                      <label class="file-label" id="imageLabel" for="image_file">
                        <span>📷</span>
                        <span id="imageName">이미지를 선택하세요 (jpg, png)</span>
                      </label>
                      <input id="image_file" type="file" accept="image/*" capture="environment" onchange="updateFileLabel('image_file','imageLabel','imageName')"/>
                    </div>

                    <div>
                      <label>영상 업로드</label>
                      <label class="file-label" id="videoLabel" for="video_file">
                        <span>🎬</span>
                        <span id="videoName">영상을 선택하세요 (mp4, avi)</span>
                      </label>
                      <input id="video_file" type="file" accept="video/*" onchange="updateFileLabel('video_file','videoLabel','videoName')"/>
                    </div>

                    <button class="btn-video" onclick="runVideo()">영상 위험 분석 실행</button>

                    <div class="btn-row">
                      <button class="btn-secondary" onclick="getLocation()">현재 위치 가져오기</button>
                      <button class="btn-secondary" onclick="loadSignal()">신호 조회</button>
                    </div>

                    <div class="btn-row">
                      <button class="btn-danger" onclick="autoDetect()">이미지 위험 분석</button>
                      <button class="btn-default" onclick="refreshAll()">지도 데이터 갱신</button>
                    </div>
                  </div>

                  <div id="statusBox" class="status">
                    <div class="status-title">SYSTEM STATUS</div>
                    <div class="status-main">대기 중</div>
                    <div class="status-meta">이미지 또는 영상을 업로드하고 분석을 실행하세요.</div>
                  </div>
                </div>

                <div class="card">
                  <div class="section-label">// 분석 결과</div>
                  <div class="preview-wrap" id="previewWrap">
                    <div class="placeholder">
                      <div class="placeholder-icon">🔍</div>
                      오버레이 결과와 영상 분석 리포트가 여기 표시됩니다.
                    </div>
                  </div>
                </div>
              </div>

              <div class="right-col">
                <div class="map-card">
                  <div class="map-header">
                    <div class="k">LIVE RISK MAP</div>
                    <div class="v">AuraView Event Distribution</div>
                  </div>
                  <div style="position:absolute;z-index:500;top:14px;right:14px;display:flex;gap:6px;">
                    <button class="btn-secondary" style="width:auto;padding:7px 12px;font-size:11px;" onclick="toggleTaasHeatmap()">🔥 TAAS 사고 히트맵</button>
                  </div>
                  <div id="map"></div>
                </div>

                <div class="card">
                  <div class="section-label">// 위험 랭킹 TOP 5</div>
                  <div class="ranking" id="ranking">
                    <div class="placeholder" style="grid-column:1/-1;min-height:80px;">데이터 로딩 중...</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 2 : BEV Occupancy -->
          <div class="tab-panel" id="tab2">
            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card">
                  <div class="card-tag">OCCUPANCY</div>
                  <div class="section-label">// BEV 점유 추정 입력</div>
                  <div class="hero-copy">
                    <div class="hero-title">보이지 않는 공간을 확률로 채운다</div>
                    <div class="hero-desc">Tesla Occupancy Network 방식의 경량 버전. 영상 프레임에서 BEV(조감도) 40m × 40m 범위 점유 확률을 실시간으로 복원합니다.</div>
                  </div>

                  <div class="form-grid">
                    <div>
                      <label>현장 이미지</label>
                      <label class="file-label" id="occLabel" for="occ_file">
                        <span>📷</span>
                        <span id="occName">이미지를 선택하세요</span>
                      </label>
                      <input id="occ_file" type="file" accept="image/*" onchange="updateFileLabel('occ_file','occLabel','occName')"/>
                    </div>
                    <div class="btn-row">
                      <div>
                        <label>지속시간(s)</label>
                        <input id="occ_duration" type="number" step="0.1" value="3.5"/>
                      </div>
                      <div>
                        <label>장애물</label>
                        <select id="occ_obstacle">
                          <option value="truck">truck</option>
                          <option value="bus">bus</option>
                          <option value="van">van</option>
                          <option value="car">car</option>
                        </select>
                      </div>
                    </div>
                    <button class="btn-accent" onclick="runOccupancy()">BEV Occupancy 추정</button>
                    <button class="btn-secondary" onclick="loadOccupancyDemo()">데모 그리드 보기</button>
                  </div>

                  <div id="occResultBox" class="status">
                    <div class="status-title">BEV RESULT</div>
                    <div class="status-main">대기 중</div>
                    <div class="status-meta">Occupancy mass · Intent · Risk 확률이 여기에 표시됩니다.</div>
                  </div>
                </div>
              </div>

              <div class="right-col">
                <div class="card">
                  <div class="section-label">// BEV Occupancy · <span id="occModeLabel">2D Heatmap</span></div>
                  <div style="display:flex;gap:8px;margin-bottom:10px;">
                    <button class="btn-secondary" style="width:auto;padding:8px 14px;" onclick="setOccMode('2d')">2D Heatmap</button>
                    <button class="btn-accent" style="width:auto;padding:8px 14px;" onclick="setOccMode('3d')">3D Voxel (FSD-style)</button>
                  </div>
                  <div class="preview-wrap" id="occCanvasWrap" style="height:560px;display:flex;align-items:center;justify-content:center;">
                    <div class="placeholder"><div class="placeholder-icon">🗺️</div>BEV 추정 결과가 여기에 표시됩니다.</div>
                  </div>
                  <canvas id="occThreeCanvas" style="display:none;width:100%;height:560px;border-radius:12px;background:#04080e;"></canvas>
                </div>
                <div class="card">
                  <div class="section-label">// Attention (E2E Risk Transformer)</div>
                  <div id="occAttention" class="rank-body">모델이 어느 feature에 주목했는지 표시됩니다.</div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 3 : Fusion -->
          <div class="tab-panel" id="tab3">
            <div class="card">
              <div class="card-tag">FUSION · 5점</div>
              <div class="section-label">// 6종 공공데이터 한 응답 결합</div>
              <div class="hero-copy">
                <div class="hero-title">교차로 한 곳 = 6종 데이터 한 호출</div>
                <div class="hero-desc">신호 · VDS · 돌발 · TAAS · ITS · 안심구역 — 각 어댑터가 동일 교차로에 대해 동시 조회 후 단일 JSON 으로 결합 반환합니다.</div>
              </div>
              <div class="form-grid">
                <div class="btn-row">
                  <div>
                    <label>교차로 ID</label>
                    <input id="fusion_id" type="text" value="1007"/>
                  </div>
                  <div>
                    <label>Link ID</label>
                    <input id="fusion_link" type="text" value="1000000100"/>
                  </div>
                </div>
                <button class="btn-accent" onclick="runFusion()">융합 조회</button>
              </div>
              <div id="fusionCards" style="margin-top:18px;display:grid;grid-template-columns:repeat(auto-fill, minmax(310px, 1fr));gap:14px;">
                <div class="placeholder" style="grid-column:1/-1;min-height:140px;">융합 결과 카드가 여기에 표시됩니다.</div>
              </div>
              <details style="margin-top:14px;">
                <summary style="cursor:pointer;color:var(--muted);font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;">// raw JSON</summary>
                <pre id="fusionOut" style="margin-top:10px;padding:14px;background:var(--surface2);border:1px solid var(--border);border-radius:12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text);max-height:380px;overflow:auto;white-space:pre-wrap;"></pre>
              </details>
            </div>
          </div>

          <!-- TAB 4 : Fleet -->
          <div class="tab-panel" id="tab4">
            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card">
                  <div class="card-tag">FLEET · SHADOW MODE</div>
                  <div class="section-label">// Fleet Learning 기여 현황</div>
                  <div class="hero-copy">
                    <div class="hero-title">쓸수록 똑똑해지는 AuraView</div>
                    <div class="hero-desc">엣지 단말이 '어려운 장면'만 PII 마스킹 후 업로드합니다. 주기적으로 모델이 재학습됩니다.</div>
                  </div>
                  <button class="btn-secondary" onclick="loadFleetStats()" style="margin-top:12px;">통계 새로고침</button>
                  <pre id="fleetOut" style="margin-top:16px;padding:16px;background:var(--surface2);border:1px solid var(--border);border-radius:12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text);max-height:420px;overflow:auto;white-space:pre-wrap;">Fleet 통계가 여기에 표시됩니다.</pre>
                </div>
              </div>
              <div class="right-col">
                <div class="card">
                  <div class="section-label">// 엣지 단말 PWA 설치</div>
                  <div class="hero-copy">
                    <div class="hero-title">📱 스마트폰이 그대로 엣지 단말</div>
                    <div class="hero-desc">아래 QR을 스캔하면 AuraView Fleet PWA가 설치됩니다. 카메라로 Shadow Mode가 자동 시작됩니다.</div>
                  </div>
                  <div id="pwaQr" style="margin-top:14px;display:flex;justify-content:center;background:#fff;border-radius:12px;padding:16px;"></div>
                  <div style="margin-top:12px;text-align:center;">
                    <a id="pwaLink" href="/pwa" target="_blank" style="color:var(--accent);font-family:'JetBrains Mono',monospace;font-size:12px;">/pwa</a>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 6 : Accident Reenactment -->
          <div class="tab-panel" id="tab6">
            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card">
                  <div class="card-tag">REENACTMENT</div>
                  <div class="section-label">// 2분 사고 재현 영상 생성</div>
                  <div class="hero-copy">
                    <div class="hero-title">AuraView 였다면 몇 초 먼저 경고할 수 있었을까?</div>
                    <div class="hero-desc">블랙박스 영상을 업로드하거나, TAAS 사고를 바탕으로 합성된 장면을 선택해 Before/After 오버레이 영상을 자동 생성합니다.</div>
                  </div>

                  <div class="form-grid" style="margin-top:14px;">
                    <div>
                      <label>블랙박스 영상 (선택)</label>
                      <label class="file-label" id="scnLabel" for="scn_video">
                        <span>🎬</span>
                        <span id="scnName">영상을 선택하거나 합성 시나리오를 고르세요</span>
                      </label>
                      <input id="scn_video" type="file" accept="video/*" onchange="updateFileLabel('scn_video','scnLabel','scnName')"/>
                    </div>
                    <div>
                      <label>합성 시나리오</label>
                      <select id="scn_preset">
                        <option value="">— 선택 안 함 —</option>
                        <option value="crosswalk_truck">횡단보도 · 대형차 가림 · 보행자 출현</option>
                        <option value="motorcycle_blindspot">사각지대 · 이륜차 접근</option>
                        <option value="signal_occluded">신호 가림 + 급감속</option>
                        <option value="v2v_collab">⭐ V2V 협업 인지 (마주오는 차 시점)</option>
                      </select>
                    </div>
                    <button class="btn-accent" onclick="runScenario()">사고 재현 영상 생성</button>
                    <button class="btn-secondary" onclick="loadScenarioList()">최근 생성물 목록</button>
                    <button class="btn-video" onclick="buildShowreel()">⭐ 합본 시연 영상 (3장면 + 타이틀)</button>
                  </div>

                  <div id="scnStatus" class="status" style="margin-top:14px;">
                    <div class="status-title">REENACTMENT STATUS</div>
                    <div class="status-main">대기 중</div>
                    <div class="status-meta">영상 또는 합성 시나리오를 선택하세요.</div>
                  </div>
                </div>
              </div>

              <div class="right-col">
                <div class="card">
                  <div class="section-label">// Before / After Overlay</div>
                  <div id="scnVideoWrap" class="preview-wrap" style="height:480px;display:flex;align-items:center;justify-content:center;">
                    <div class="placeholder"><div class="placeholder-icon">🎞️</div>생성된 재현 영상이 여기에 재생됩니다.</div>
                  </div>
                </div>
                <div class="card">
                  <div class="section-label">// Risk Curve</div>
                  <canvas id="scnRiskChart" style="width:100%;height:140px;"></canvas>
                  <div class="muted" id="scnRiskMeta" style="margin-top:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);">선행 경고 시간 · 위험 확률 피크가 여기에 표시됩니다.</div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 7 : K-MaaS -->
          <div class="tab-panel" id="tab7">
            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card">
                  <div class="card-tag">K-MAAS</div>
                  <div class="section-label">// 위험 교차로 우회 대중교통 추천</div>
                  <div class="hero-copy">
                    <div class="hero-title">위험을 감지하면 즉시 대중교통으로</div>
                    <div class="hero-desc">전방 위험 교차로를 K-MaaS 데이터와 결합해 지하철·버스·공유 자전거 우회 경로 3종을 즉시 추천 + 노선 운영팀에 데이터 환원.</div>
                  </div>
                  <div class="form-grid" style="margin-top:14px;">
                    <div class="btn-row">
                      <div>
                        <label>출발 위도</label>
                        <input id="km_olat" type="number" step="0.000001" value="37.5601"/>
                      </div>
                      <div>
                        <label>출발 경도</label>
                        <input id="km_olon" type="number" step="0.000001" value="127.0410"/>
                      </div>
                    </div>
                    <div class="btn-row">
                      <div>
                        <label>도착 위도</label>
                        <input id="km_dlat" type="number" step="0.000001" value="37.5665"/>
                      </div>
                      <div>
                        <label>도착 경도</label>
                        <input id="km_dlon" type="number" step="0.000001" value="126.9780"/>
                      </div>
                    </div>
                    <div>
                      <label>현 위험 점수</label>
                      <input id="km_risk" type="number" step="0.1" value="11.5"/>
                    </div>
                    <button class="btn-accent" onclick="runKmaas()">K-MaaS 대안 조회</button>
                    <button class="btn-secondary" onclick="loadKmaasOperator()">노선 운영팀 리포트</button>
                  </div>
                </div>
              </div>
              <div class="right-col">
                <div class="card">
                  <div class="section-label">// 추천 결과</div>
                  <div id="kmaasOut" style="margin-top:8px;display:grid;gap:10px;">
                    <div class="placeholder" style="min-height:120px;">대안 조회 결과가 여기에 카드로 표시됩니다.</div>
                  </div>
                </div>
                <div class="card">
                  <div class="section-label">// 노선 운영팀 환원 데이터</div>
                  <pre id="kmaasOpOut" style="padding:14px;background:var(--surface2);border:1px solid var(--border);border-radius:12px;font-family:'JetBrains Mono',monospace;font-size:11px;max-height:300px;overflow:auto;white-space:pre-wrap;">시민용 추천 + 운영팀용 데이터를 동시에 제공합니다.</pre>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 8 : Hazard Report -->
          <div class="tab-panel" id="tab8">
            <div class="card">
              <div class="card-tag">POLICY REPORT</div>
              <div class="section-label">// 위험 교차로 Top-N 자동 리포트 (지자체·도로공사·K-MaaS 환원)</div>
              <div class="hero-copy">
                <div class="hero-title">데이터로 정책을 바꾼다</div>
                <div class="hero-desc">현재까지 누적된 Fleet 이벤트 + 융합 데이터로 위험 교차로 Top-N 을 자동 산출하고, 각 지점별 권고 액션과 함께 HTML/JSON 리포트를 생성합니다.</div>
              </div>
              <div class="btn-row" style="margin-top:14px;">
                <button class="btn-accent" onclick="generateReport(20)">Top 20 리포트 생성</button>
                <button class="btn-secondary" onclick="loadReportList()">최근 생성물 목록</button>
              </div>
              <div id="reportOut" style="margin-top:14px;"></div>
            </div>
          </div>

          <!-- TAB 9 : V2V Collaborative Perception -->
          <div class="tab-panel" id="tab9">
            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card">
                  <div class="card-tag">V2V · BUS · BIDIR</div>
                  <div class="section-label">// 마주오는 차가 본 것을 내 사각지대로</div>
                  <div class="hero-copy">
                    <div class="hero-title">Tesla 도 못 하는 한국 특화 협업 인지</div>
                    <div class="hero-desc">
                      마주오는 차의 시점 + 버스 정류장 prior + 상행/하행 흐름 비교 →
                      <em style="color:var(--accent);font-style:normal;">"버스가 신호등을 가린 그 너머 보행자"</em>
                      를 다중 정보로 보강해 잡아냅니다.
                    </div>
                  </div>

                  <div class="form-grid" style="margin-top:14px;">
                    <div>
                      <label>현장 이미지 (버스 가림 시나리오 권장)</label>
                      <label class="file-label" id="cvLabel" for="cv_file">
                        <span>📷</span><span id="cvName">이미지를 선택하세요</span>
                      </label>
                      <input id="cv_file" type="file" accept="image/*" onchange="updateFileLabel('cv_file','cvLabel','cvName')"/>
                    </div>
                    <div class="btn-row">
                      <div><label>교차로 ID</label><input id="cv_iid" type="text" value="1007"/></div>
                      <div><label>자차 진행방향°</label><input id="cv_head" type="number" step="1" value="270"/></div>
                    </div>
                    <div class="btn-row">
                      <div><label>위도</label><input id="cv_lat" type="number" step="0.000001" value="37.5601"/></div>
                      <div><label>경도</label><input id="cv_lon" type="number" step="0.000001" value="127.0410"/></div>
                    </div>
                    <button class="btn-secondary" onclick="seedV2VDemo()">▶ 시연용 V2V 차량 3대 풀에 게시</button>
                    <button class="btn-accent" onclick="runFusedOccupancy()">⭐ 협업 인지 실행 (V2V + Bus + Bidir 결합)</button>
                  </div>
                </div>

                <div class="card">
                  <div class="section-label">// V2V 메시지 풀 (해당 교차로)</div>
                  <pre id="v2vPool" style="max-height:220px;overflow:auto;font-family:'JetBrains Mono',monospace;font-size:10.5px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:12px;white-space:pre-wrap;">peers 정보가 여기 표시됩니다.</pre>
                </div>
              </div>

              <div class="right-col">
                <div class="card">
                  <div class="section-label">// 결합된 위험 확률 비교</div>
                  <div id="cvDiff" style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:12px;"></div>
                </div>
                <div class="card">
                  <div class="section-label">// 결합 BEV (보강된 영역 cyan glow)</div>
                  <div id="cvCanvas" class="preview-wrap" style="height:380px;display:flex;align-items:center;justify-content:center;">
                    <div class="placeholder"><div class="placeholder-icon">🛰️</div>결합 결과가 여기에 표시됩니다.</div>
                  </div>
                  <div id="cvBreakdown" class="rank-body" style="margin-top:12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 5 : Capability Matrix -->
          <div class="tab-panel" id="tab5">
            <div class="card">
              <div class="card-tag">CAPABILITIES · LIVE</div>
              <div class="section-label">// AuraView 기능 매트릭스 · 라이브 카운터</div>
              <div class="ranking">
                <div class="rank-item mid">
                  <div class="rank-head"><div class="rank-title">AI · 학습</div><span class="badge b-g">on</span></div>
                  <div class="rank-body">
                    HydraNet · Risk Transformer · Intent Predictor 학습 스크립트<br>
                    Fleet 누적 학습 데이터 · <span id="sc_fleet" style="color:var(--accent);font-weight:700;">… 건</span>
                  </div>
                </div>
                <div class="rank-item mid">
                  <div class="rank-head"><div class="rank-title">AI · 분석</div><span class="badge b-g">on</span></div>
                  <div class="rank-body">
                    BEV Occupancy 3D · E2E 위험 확률 · Attention 해석<br>
                    재현 영상 · <span id="sc_scenarios" style="color:var(--accent);font-weight:700;">… 편</span>
                  </div>
                </div>
                <div class="rank-item mid">
                  <div class="rank-head"><div class="rank-title">데이터 융합</div><span class="badge b-g">on</span></div>
                  <div class="rank-body">
                    신호 · VDS · 돌발 · TAAS · ITS · 안심구역<br>
                    소스 어댑터 활성 · <span id="sc_fusion" style="color:var(--accent);font-weight:700;">…종</span>
                  </div>
                </div>
                <div class="rank-item mid">
                  <div class="rank-head"><div class="rank-title">가명정보 결합</div><span class="badge b-g">on</span></div>
                  <div class="rank-body">
                    HMAC 가명화 · k-익명성 · 얼굴·번호판 블러<br>
                    /dsz/join/taas-vds · /fleet/contribute (자동 마스킹)
                  </div>
                </div>
                <div class="rank-item mid">
                  <div class="rank-head"><div class="rank-title">안심구역</div><span class="badge b-g">on</span></div>
                  <div class="rank-body">
                    dsz.ex.co.kr 반입·결합분석·해시 검증 반출<br>
                    정책 리포트 누적 · <span id="sc_reports" style="color:var(--accent);font-weight:700;">… 개</span>
                  </div>
                </div>
                <div class="rank-item mid" style="border-left-color:var(--accent2);">
                  <div class="rank-head"><div class="rank-title">⭐ K-MaaS</div><span class="badge" style="background:rgba(124,58,237,0.18);color:#a995ff;border:1px solid rgba(124,58,237,0.3);">on</span></div>
                  <div class="rank-body">
                    위험 교차로 → 대중교통 우회 추천 + 운영팀 환원<br>
                    /kmaas/alternatives · /kmaas/operator-report
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>

        <script>
          /* ── TAB SWITCHING ── */
          document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
              document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
              document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
              tab.classList.add('active');
              document.getElementById(tab.dataset.tab).classList.add('active');
            });
          });

          /* ── TOAST ── */
          function toast(msg, type = 'info', duration = 3500) {
            const icons = { info: 'ℹ', success: '✓', error: '✕', warn: '⚠' };
            const el = document.createElement('div');
            el.className = 'toast ' + type;
            el.innerHTML = '<span>' + icons[type] + '</span><span>' + msg + '</span>';
            document.getElementById('toast-container').appendChild(el);
            setTimeout(() => {
              el.style.animation = 'toastOut .25s ease forwards';
              setTimeout(() => el.remove(), 260);
            }, duration);
          }

          /* ── LOADER ── */
          function showLoader(text) {
            const l = document.getElementById('loader');
            l.querySelector('.loader-text').textContent = text || 'ANALYZING...';
            l.classList.add('active');
          }

          function hideLoader() {
            document.getElementById('loader').classList.remove('active');
          }

          /* ── FILE LABEL ── */
          function updateFileLabel(inputId, labelId, nameId) {
            const f = document.getElementById(inputId).files[0];
            if (f) {
              document.getElementById(nameId).textContent = f.name;
              document.getElementById(labelId).classList.add('has-file');
            }
          }

          /* ── MAP ── */
          const map = L.map('map').setView([37.5665, 126.9780], 12);

          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap'
          }).addTo(map);

          let markers = [];

          function clearMarkers() {
            markers.forEach(m => map.removeLayer(m));
            markers = [];
          }

          function markerColor(score) {
            if (score >= 10) return '#ff3b3b';
            if (score >= 6)  return '#ffb020';
            return '#00e09a';
          }

          function badgeClass(score) {
            if (score >= 10) return 'badge b-r';
            if (score >= 6)  return 'badge b-y';
            return 'badge b-g';
          }

          function rankClass(score) {
            if (score >= 10) return 'rank-item high';
            if (score >= 6)  return 'rank-item mid';
            return 'rank-item';
          }

          /* ── TAAS HEATMAP ── */
          let taasLayer = null;
          async function toggleTaasHeatmap() {
            if (taasLayer) {
              map.removeLayer(taasLayer);
              taasLayer = null;
              toast('TAAS 히트맵 OFF', 'info', 1500);
              return;
            }
            try {
              const res = await fetch(window.location.origin + '/heatmap/taas?year=2024');
              const data = await res.json();
              taasLayer = L.heatLayer(data.points, {
                radius: 28, blur: 22, minOpacity: 0.35, maxZoom: 17,
                gradient: { 0.2: '#00c8ff', 0.45: '#ffb020', 0.7: '#ff8b3b', 0.9: '#ff3b3b' },
              }).addTo(map);
              toast(`TAAS 히트맵 ON · ${data.count}건 (${data.source})`, 'success');
            } catch(e) {
              toast('TAAS 히트맵 로드 실패', 'error');
            }
          }

          /* ── INTERSECTIONS ── */
          async function loadIntersections() {
            const res = await fetch(window.location.origin + '/intersections/');
            const data = await res.json();
            const select = document.getElementById('intersection_id');
            select.innerHTML = '';

            data.slice(0, 500).forEach(item => {
              const opt = document.createElement('option');
              opt.value = item.intersection_id;
              opt.textContent = item.intersection_id + ' — ' + item.name;
              select.appendChild(opt);
            });

            const target = Array.from(select.options).find(o => o.value === '1007');
            if (target) target.selected = true;
          }

          /* ── GEOLOCATION ── */
          function getLocation() {
            if (!navigator.geolocation) {
              toast('Geolocation이 지원되지 않는 브라우저입니다.', 'error');
              return;
            }

            navigator.geolocation.getCurrentPosition(
              (pos) => {
                document.getElementById('user_lat').value = pos.coords.latitude;
                document.getElementById('user_lon').value = pos.coords.longitude;
                map.setView([pos.coords.latitude, pos.coords.longitude], 16);
                toast('현재 위치를 가져왔습니다.', 'success');
              },
              () => {
                toast('현재 위치 가져오기는 HTTPS 환경에서 동작합니다.', 'warn');
              }
            );
          }

          /* ── SIGNAL ── */
          async function loadSignal() {
            const intersectionId = document.getElementById('intersection_id').value;
            const res = await fetch(window.location.origin + '/signals/' + intersectionId);
            const data = await res.json();

            let signalState = '-';
            let remainTime = '-';

            if (data && data.body && data.body.items && data.body.items.item) {
              let item = data.body.items.item;
              if (Array.isArray(item)) item = item[0];
              signalState = item.stPdsgSttsNm || '-';
              remainTime = item.stPdsgRmndCs || '-';
            }

            const box = document.getElementById('statusBox');
            box.className = 'status info';
            box.innerHTML = `
              <div class="status-title">SIGNAL STATUS</div>
              <div class="status-main">${signalState}</div>
              <div class="status-meta">잔여시간 &nbsp;${remainTime}</div>
            `;
          }

          /* ── IMAGE DETECT ── */
          async function autoDetect() {
            const fileInput = document.getElementById('image_file');
            if (!fileInput.files || fileInput.files.length === 0) {
              toast('분석할 이미지를 먼저 선택해주세요.', 'warn');
              return;
            }

            showLoader('이미지 분석 중...');
            const formData = new FormData();
            formData.append('intersection_id', document.getElementById('intersection_id').value);

            const latVal = document.getElementById('user_lat').value;
            const lonVal = document.getElementById('user_lon').value;
            if (latVal !== '') formData.append('user_lat', latVal);
            if (lonVal !== '') formData.append('user_lon', lonVal);

            formData.append('duration', document.getElementById('duration').value);
            formData.append('obstacle_type', document.getElementById('obstacle_type').value);
            formData.append('image', fileInput.files[0]);

            try {
              const res = await fetch(window.location.origin + '/detect/frame', {
                method: 'POST',
                body: formData
              });

              const data = await res.json();
              const box = document.getElementById('statusBox');
              const isWarn = data.status === 'warning';

              box.innerHTML = `
                <div class="status-title">${isWarn ? 'AURAVIEW ALERT' : 'AURAVIEW STATUS'}</div>
                <div class="status-main">${isWarn ? '신호 가림 감지' : '신호 확인 가능'}</div>
                <div class="status-meta">
                  intersection_id &nbsp;${data.intersection_id || '-'}<br>
                  signal_state &nbsp;&nbsp;&nbsp;${data.signal_state || '-'}<br>
                  remain_time &nbsp;&nbsp;&nbsp;&nbsp;${data.signal_remain_time || '-'}초<br>
                  risk_score &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;${data.risk_score || '-'}
                </div>
              `;
              box.className = isWarn ? 'status warning' : 'status safe';

              const previewWrap = document.getElementById('previewWrap');
              if (data.overlay_image) {
                previewWrap.innerHTML = `<img class="preview-single" src="${data.overlay_image}?t=${Date.now()}" alt="overlay result"/>`;
              } else {
                previewWrap.innerHTML = `<div class="placeholder"><div class="placeholder-icon">🚫</div>오버레이 결과가 없습니다.</div>`;
              }

              toast(isWarn ? '신호 가림이 감지되었습니다.' : '신호 확인 가능 상태입니다.', isWarn ? 'error' : 'success');
              await refreshAll();
            } catch (e) {
              toast('분석 중 오류가 발생했습니다.', 'error');
            } finally {
              hideLoader();
            }
          }

          /* ── VIDEO ── */
          async function runVideo() {
            const fileInput = document.getElementById('video_file');

            if (!fileInput.files.length) {
              toast('분석할 영상을 먼저 선택해주세요.', 'warn');
              return;
            }

            showLoader('영상 분석 중...');
            const formData = new FormData();
            formData.append('video', fileInput.files[0]);

            try {
              const res = await fetch(window.location.origin + '/detect/video', {
                method: 'POST',
                body: formData
              });

              const data = await res.json();
              const box = document.getElementById('statusBox');
              box.className = 'status info';
              box.innerHTML = `
                <div class="status-title">VIDEO ANALYSIS COMPLETE</div>
                <div class="status-main">영상 분석 완료</div>
                <div class="status-meta">
                  total_frames &nbsp;${data.total_frames || 0}<br>
                  risk_frames &nbsp;&nbsp;${data.risk_frames || 0}<br>
                  risk_ratio &nbsp;&nbsp;&nbsp;${data.risk_ratio || 0}%
                </div>
              `;

              const previewWrap = document.getElementById('previewWrap');
              const topFrames = (data.highlights || []).slice(0, 3);

              let html = `
                <div class="video-report">
                  <div class="video-summary">
                    <div class="summary-kicker">VIDEO ANALYSIS REPORT</div>
                    <div class="summary-title">신호 가림 분석 결과</div>
                    <div class="summary-metrics">
                      <div class="metric"><span>TOTAL FRAMES</span><strong>${data.total_frames || 0}</strong></div>
                      <div class="metric"><span>RISK FRAMES</span><strong>${data.risk_frames || 0}</strong></div>
                      <div class="metric"><span>RISK RATIO</span><strong>${data.risk_ratio || 0}%</strong></div>
                    </div>
                  </div>
                  <div class="video-grid">
              `;

              if (topFrames.length === 0) {
                html += `<div class="placeholder" style="min-height:180px;">위험 프레임이 검출되지 않았습니다.</div>`;
              } else {
                topFrames.forEach((item, idx) => {
                  html += `
                    <div class="video-shot">
                      <div class="shot-label">STEP ${idx + 1} &nbsp;·&nbsp; 대표 위험 프레임</div>
                      <div class="shot-compare">
                        <div class="shot-box">
                          <div class="shot-tag">ORIGINAL</div>
                          <img src="${item.frame}?t=${Date.now()}" />
                        </div>
                        <div class="shot-box">
                          <div class="shot-tag">AURAVIEW RESULT</div>
                          <img src="${item.overlay}?t=${Date.now()}" />
                        </div>
                      </div>
                    </div>
                  `;
                });
              }

              html += `</div></div>`;
              previewWrap.innerHTML = html;
              toast('영상 분석이 완료되었습니다.', 'success');
            } catch (e) {
              toast('영상 분석 중 오류가 발생했습니다.', 'error');
            } finally {
              hideLoader();
            }
          }

          /* ── MAP REFRESH ── */
          async function refreshMap() {
            const res = await fetch(window.location.origin + '/events/map-data');
            const data = await res.json();

            clearMarkers();
            const valid = data.filter(x => x.last_lat !== null && x.last_lon !== null);

            valid.forEach(ev => {
              const color = markerColor(ev.risk_score);

              const marker = L.circleMarker([ev.last_lat, ev.last_lon], {
                radius: 11,
                color: color,
                fillColor: color,
                fillOpacity: 0.85,
                weight: 2
              }).addTo(map);

              marker.bindPopup(`
                <div class="popup-body">
                  <div class="popup-id">${ev.intersection_id}</div>
                  event_count &nbsp;&nbsp;${ev.event_count}<br>
                  avg_duration &nbsp;${ev.avg_duration}<br>
                  signal_state &nbsp;${ev.signal_state || '-'}<br>
                  risk_score &nbsp;&nbsp;&nbsp;${ev.risk_score}
                </div>
              `);

              let r = 11;
              const pulse = setInterval(() => {
                try {
                  r = r >= 16 ? 11 : r + 1;
                  marker.setRadius(r);
                } catch (e) {
                  clearInterval(pulse);
                }
              }, 200);

              markers.push(marker);
            });

            if (valid.length > 0) {
              map.setView([valid[0].last_lat, valid[0].last_lon], 14);
            }
          }

          /* ── RANKING ── */
          async function loadRiskRanking() {
            const res = await fetch(window.location.origin + '/risk/');
            const data = await res.json();

            const wrap = document.getElementById('ranking');
            wrap.innerHTML = '';

            if (!data.length) {
              wrap.innerHTML = '<div class="placeholder" style="grid-column:1/-1;min-height:80px;">아직 이벤트 데이터가 없습니다.</div>';
              return;
            }

            data.slice(0, 5).forEach((item, idx) => {
              const div = document.createElement('div');
              div.className = rankClass(item.risk_score);
              div.innerHTML = `
                <div class="rank-head">
                  <div class="rank-title">#${idx + 1} &nbsp;${item.intersection_id}</div>
                  <span class="${badgeClass(item.risk_score)}">RISK ${item.risk_score}</span>
                </div>
                <div class="rank-body">
                  event_count &nbsp;&nbsp;${item.event_count}<br>
                  avg_duration &nbsp;${item.avg_duration}<br>
                  signal_state &nbsp;${item.signal_state || '-'}
                </div>
              `;
              wrap.appendChild(div);
            });
          }

          async function refreshAll() {
            await refreshMap();
            await loadRiskRanking();
          }

          /* ── OCCUPANCY (2D / 3D) ── */
          let occMode = '2d';
          let lastOccData = null;
          let threeCtx = null;   // { renderer, scene, camera, voxels }

          function setOccMode(mode) {
            occMode = mode;
            document.getElementById('occModeLabel').textContent = mode === '3d' ? '3D Voxel (FSD-style)' : '2D Heatmap';
            document.getElementById('occCanvasWrap').style.display = mode === '2d' ? 'flex' : 'none';
            document.getElementById('occThreeCanvas').style.display = mode === '3d' ? 'block' : 'none';
            if (lastOccData) renderOccCanvas(lastOccData);
          }

          function renderOccCanvas(data) {
            lastOccData = data;
            if (occMode === '3d') {
              renderOcc3D(data);
            } else {
              renderOcc2D(data);
            }
          }

          function renderOcc2D(data) {
            const wrap = document.getElementById('occCanvasWrap');
            wrap.innerHTML = '';
            if (!data.grid_b64) {
              wrap.innerHTML = '<div class="placeholder"><div class="placeholder-icon">⚠️</div>BEV 이미지를 생성하지 못했습니다.</div>';
              return;
            }
            const img = document.createElement('img');
            img.src = data.grid_b64;
            img.style.width = '100%';
            img.style.height = '100%';
            img.style.objectFit = 'contain';
            img.style.imageRendering = 'pixelated';
            img.style.background = '#050a10';
            wrap.appendChild(img);
          }

          function ensureThree() {
            const canvas = document.getElementById('occThreeCanvas');
            if (threeCtx) return threeCtx;
            const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true});
            renderer.setPixelRatio(window.devicePixelRatio);
            const scene = new THREE.Scene();
            scene.background = new THREE.Color(0x04080e);

            // 전방 → Z+, 좌우 → X, 높이 → Y
            const camera = new THREE.PerspectiveCamera(55, 16/9, 0.1, 500);
            camera.position.set(-22, 20, -22);
            camera.lookAt(0, 2, 20);

            // Lighting
            scene.add(new THREE.AmbientLight(0x88aacc, 0.6));
            const dir = new THREE.DirectionalLight(0xffffff, 0.9);
            dir.position.set(30, 50, 10);
            scene.add(dir);

            // Ground + gridline
            const ground = new THREE.Mesh(
              new THREE.PlaneGeometry(40, 40),
              new THREE.MeshBasicMaterial({color:0x0a1624})
            );
            ground.rotation.x = -Math.PI / 2;
            ground.position.z = 20;
            scene.add(ground);
            const grid = new THREE.GridHelper(40, 40, 0x0f2a44, 0x0a1a2e);
            grid.position.z = 20;
            scene.add(grid);

            // Ego car (indicator)
            const ego = new THREE.Mesh(
              new THREE.BoxGeometry(1.8, 1.4, 4),
              new THREE.MeshStandardMaterial({color:0x00c8ff, emissive:0x003b55, metalness:0.6, roughness:0.3})
            );
            ego.position.set(0, 0.7, 0);
            scene.add(ego);

            const voxelGroup = new THREE.Group();
            scene.add(voxelGroup);

            threeCtx = {renderer, scene, camera, voxelGroup, t: 0};

            let yaw = 0;
            function animate() {
              threeCtx.t += 0.005;
              yaw = 0.0005 + yaw;
              camera.position.x = Math.cos(threeCtx.t * 0.25) * 30;
              camera.position.z = Math.sin(threeCtx.t * 0.25) * 30 + 10;
              camera.lookAt(0, 2, 18);
              renderer.render(scene, camera);
              requestAnimationFrame(animate);
            }
            function resize() {
              const w = canvas.clientWidth || 800;
              const h = 560;
              renderer.setSize(w, h, false);
              camera.aspect = w / h;
              camera.updateProjectionMatrix();
            }
            window.addEventListener('resize', resize);
            resize();
            animate();
            return threeCtx;
          }

          function renderOcc3D(data) {
            const ctx = ensureThree();
            // Clear previous voxels
            while (ctx.voxelGroup.children.length) {
              const m = ctx.voxelGroup.children.pop();
              m.geometry && m.geometry.dispose();
              m.material && m.material.dispose();
            }
            if (!data.grid_flat || !data.grid_shape_flat) return;

            const [rows, cols] = data.grid_shape_flat;
            const cell = data.grid_cell_m_flat || (data.cell_m * 2);
            const forward = data.forward_m || 40;
            const lateral = data.lateral_m || 20;
            const voxMat = new THREE.MeshStandardMaterial({vertexColors:false, metalness:0.1, roughness:0.6});
            const geom = new THREE.BoxGeometry(cell * 0.9, 1, cell * 0.9);

            const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
            const lerp = (a, b, t) => a + (b - a) * t;

            for (let r = 0; r < rows; r++) {
              for (let c = 0; c < cols; c++) {
                const p = data.grid_flat[r * cols + c] || 0;
                if (p < 0.08) continue;
                const height = clamp(p * 6, 0.2, 6);
                const x = -lateral + c * cell + cell / 2;
                const z = r * cell + cell / 2;
                // color ramp: cyan (low) → orange → red (high)
                const t = clamp(p, 0, 1);
                const color = new THREE.Color(
                  lerp(0.0, 1.0, t),
                  lerp(0.8, 0.2, t),
                  lerp(1.0, 0.1, t)
                );
                const mat = new THREE.MeshStandardMaterial({color, emissive: color.clone().multiplyScalar(0.25), transparent:true, opacity:0.85});
                const box = new THREE.Mesh(geom, mat);
                box.position.set(x, height / 2, z);
                box.scale.y = height;
                ctx.voxelGroup.add(box);
              }
            }
          }

          async function loadOccupancyDemo() {
            const res = await fetch(window.location.origin + '/occupancy/demo');
            const data = await res.json();
            renderOccCanvas(data);
            document.getElementById('occResultBox').className = 'status info';
            document.getElementById('occResultBox').innerHTML = `
              <div class="status-title">DEMO GRID</div>
              <div class="status-main">점유 mass ${data.occluded_mass.toFixed(1)}</div>
              <div class="status-meta">shape ${data.shape[0]}×${data.shape[1]} · cell ${data.cell_m}m</div>`;
          }

          async function runOccupancy() {
            const fileInput = document.getElementById('occ_file');
            if (!fileInput.files.length) {
              toast('이미지를 선택하세요.', 'warn');
              return;
            }
            showLoader('BEV OCCUPANCY 추정 중...');
            const fd = new FormData();
            fd.append('image', fileInput.files[0]);
            fd.append('duration', document.getElementById('occ_duration').value);
            fd.append('obstacle_type', document.getElementById('occ_obstacle').value);
            fd.append('signal_state', 'stop-And-Remain');
            fd.append('taas_nearby', '2');
            try {
              const res = await fetch(window.location.origin + '/occupancy/infer', {method:'POST', body: fd});
              const data = await res.json();
              renderOccCanvas(data.occupancy);

              const box = document.getElementById('occResultBox');
              const p = (data.risk.p_collision * 100).toFixed(1);
              box.className = data.risk.p_collision > 0.4 ? 'status warning' : 'status safe';
              box.innerHTML = `
                <div class="status-title">AURAVIEW K-PERCEPTION</div>
                <div class="status-main">충돌 확률 ${p}%</div>
                <div class="status-meta">
                  occluded_mass &nbsp;${data.occupancy.occluded_mass}<br>
                  pedestrian_prob &nbsp;${(data.intent.pedestrian_crossing_prob*100).toFixed(1)}%<br>
                  motorcycle_prob &nbsp;${(data.intent.motorcycle_approach_prob*100).toFixed(1)}%<br>
                  vehicles &nbsp;${data.hydranet.vehicles} · vrus &nbsp;${data.hydranet.vrus} · signals &nbsp;${data.hydranet.signals}
                </div>`;

              const att = data.risk.attention || {};
              const rows = Object.entries(att).sort((a,b)=>b[1]-a[1]).slice(0,6)
                .map(([k,v])=>`${k.padEnd(16)} ${'█'.repeat(Math.round(v*40)).padEnd(40)} ${(v*100).toFixed(1)}%`).join('<br>');
              document.getElementById('occAttention').innerHTML = '<pre style="font-family:JetBrains Mono, monospace;font-size:11px;color:var(--text);margin:0;white-space:pre;">' + rows + '</pre>';
              toast('BEV 추정 완료', 'success');
            } catch(e) {
              toast('BEV 추정 실패', 'error');
            } finally {
              hideLoader();
            }
          }

          /* ── FUSION ── */
          function fusionCardForSource(name, body) {
            const meta = {
              signal:    {emoji:'🚦', title:'실시간 신호 정보', sub:'apis.data.go.kr · B551982/rti', color:'var(--accent)'},
              vds:       {emoji:'🚗', title:'VDS 실시간 소통',   sub:'data.ex.co.kr · trafficapi',    color:'var(--safe)'},
              incidents: {emoji:'⚠️', title:'돌발상황',         sub:'data.ex.co.kr · incidentapi',  color:'var(--warn)'},
              accidents_history: {emoji:'📊', title:'TAAS 사고이력', sub:'taas.koroad.or.kr',         color:'var(--danger)'},
              its_link:  {emoji:'🛣️', title:'ITS 링크 속도',     sub:'openapi.its.go.kr',             color:'var(--accent2)'},
              dsz:       {emoji:'🔒', title:'안심구역 결합분석', sub:'dsz.ex.co.kr',                  color:'#a995ff'},
            };
            const m = meta[name] || {emoji:'📦', title:name, sub:'', color:'var(--muted)'};
            // 첫 의미있는 필드 3~5개 추출
            const flat = [];
            try {
              const inner = (body && body.body) ? body.body : body;
              const items = inner?.items?.item ?? inner?.list ?? inner?.accidents ?? inner?.body?.items ?? inner;
              const sample = Array.isArray(items) ? items[0] : items;
              if (sample && typeof sample === 'object') {
                for (const k of Object.keys(sample).slice(0, 5)) {
                  const v = sample[k];
                  if (v == null || typeof v === 'object') continue;
                  flat.push(`<div style="display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:11px;padding:3px 0;border-bottom:1px solid rgba(0,200,255,0.06);"><span style="color:var(--muted);">${k}</span><span>${String(v).slice(0,48)}</span></div>`);
                }
              }
            } catch(e) {}

            return `
              <div class="card" style="position:relative;border-left:3px solid ${m.color};">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                  <span style="font-size:20px;">${m.emoji}</span>
                  <div>
                    <div style="font-weight:900;font-size:14px;color:${m.color};">${m.title}</div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:1px;">${m.sub}</div>
                  </div>
                </div>
                <div style="margin-top:10px;">${flat.join('') || '<div style="color:var(--muted);font-size:11px;">응답 없음 / fallback</div>'}</div>
              </div>`;
          }

          async function runFusion() {
            const id = document.getElementById('fusion_id').value;
            const link = document.getElementById('fusion_link').value;
            showLoader('6종 데이터 융합 중...');
            try {
              const res = await fetch(window.location.origin + '/fusion/intersection/' + encodeURIComponent(id) + '?link_id=' + encodeURIComponent(link));
              const data = await res.json();
              document.getElementById('fusionOut').textContent = JSON.stringify(data, null, 2);

              const sources = data.sources || {};
              const cards = [];
              for (const k of ['signal', 'vds', 'incidents', 'accidents_history', 'its_link']) {
                cards.push(fusionCardForSource(k, sources[k]));
              }
              // DSZ 어댑터 — list_imported() 결과 또는 manifest.jsonl 카운트
              try {
                const dszRes = await fetch(window.location.origin + '/dsz/artifacts');
                const dsz = await dszRes.json();
                cards.push(fusionCardForSource('dsz', {body: {items: {item: {imported_count: (dsz.artifacts||[]).length, sample_path: 'dsz_exports/sample_taas_vds_join_2024.json'}}}}));
              } catch(e) { cards.push(fusionCardForSource('dsz', null)); }

              document.getElementById('fusionCards').innerHTML = cards.join('');
              toast(`융합 완료 (${id})`, 'success');
            } catch(e) {
              toast('융합 실패', 'error');
            } finally {
              hideLoader();
            }
          }

          /* ── PWA QR ── */
          (function drawPwaQR(){
            try {
              const url = window.location.origin + '/pwa';
              document.getElementById('pwaLink').href = url;
              document.getElementById('pwaLink').textContent = url;
              const qr = qrcode(0, 'M');
              qr.addData(url);
              qr.make();
              document.getElementById('pwaQr').innerHTML = qr.createImgTag(6, 12);
            } catch(e) {}
          })();

          /* ── FLEET ── */
          async function loadFleetStats() {
            const res = await fetch(window.location.origin + '/fleet/stats');
            const data = await res.json();
            document.getElementById('fleetOut').textContent = JSON.stringify(data, null, 2);
          }

          /* ── SCENARIO REENACTMENT ── */
          function drawRiskCurve(series) {
            const canvas = document.getElementById('scnRiskChart');
            if (!canvas || !series || !series.length) return;
            const ctx = canvas.getContext('2d');
            const dpr = window.devicePixelRatio || 1;
            const W = canvas.clientWidth, H = canvas.clientHeight || 140;
            canvas.width = W * dpr;
            canvas.height = H * dpr;
            ctx.scale(dpr, dpr);
            ctx.clearRect(0, 0, W, H);

            // axes
            ctx.strokeStyle = 'rgba(0,200,255,0.15)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            for (let i = 0; i <= 4; i++) {
              const y = (H - 10) * (i / 4) + 5;
              ctx.moveTo(0, y); ctx.lineTo(W, y);
            }
            ctx.stroke();

            // risk line
            const grad = ctx.createLinearGradient(0, 0, 0, H);
            grad.addColorStop(0, '#ff3b3b');
            grad.addColorStop(0.6, '#ffb020');
            grad.addColorStop(1, '#00c8ff');
            ctx.strokeStyle = grad;
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            series.forEach((v, i) => {
              const x = (i / (series.length - 1)) * W;
              const y = H - Math.max(2, v * (H - 10));
              if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            });
            ctx.stroke();

            // fill
            ctx.lineTo(W, H); ctx.lineTo(0, H);
            ctx.fillStyle = 'rgba(0,200,255,0.10)';
            ctx.fill();
          }

          async function runScenario() {
            const fileInput = document.getElementById('scn_video');
            const preset = document.getElementById('scn_preset').value;
            const hasVideo = fileInput.files && fileInput.files.length > 0;
            if (!hasVideo && !preset) {
              toast('영상을 선택하거나 합성 시나리오를 골라주세요.', 'warn');
              return;
            }
            showLoader('사고 재현 영상 생성 중...');
            const fd = new FormData();
            if (hasVideo) fd.append('video', fileInput.files[0]);
            if (preset) fd.append('preset', preset);
            try {
              const res = await fetch(window.location.origin + '/scenario/reenact', {method:'POST', body: fd});
              const data = await res.json();
              if (!res.ok) throw new Error(data.detail || 'fail');

              const wrap = document.getElementById('scnVideoWrap');
              wrap.innerHTML = `
                <video controls autoplay muted loop style="width:100%;height:100%;object-fit:contain;background:#000;border-radius:12px;">
                  <source src="${data.video_url}?t=${Date.now()}" type="video/mp4"/>
                </video>`;

              const box = document.getElementById('scnStatus');
              box.className = 'status info';
              box.innerHTML = `
                <div class="status-title">REENACTMENT READY</div>
                <div class="status-main">선행 경고 ${data.lead_time_s}초</div>
                <div class="status-meta">
                  피크 위험 &nbsp;${(data.peak_risk*100).toFixed(1)}%<br>
                  프레임 수 &nbsp;${data.frame_count}<br>
                  출력 &nbsp;${data.video_url}
                </div>`;

              drawRiskCurve(data.risk_curve || []);
              const meta = document.getElementById('scnRiskMeta');
              if (meta && data.risk_curve) {
                meta.textContent = `lead_time=${data.lead_time_s}s · peak=${(data.peak_risk*100).toFixed(1)}% · frames=${data.frame_count}`;
              }

              toast('재현 영상 생성 완료', 'success');
            } catch(e) {
              toast('재현 영상 생성 실패', 'error');
            } finally {
              hideLoader();
            }
          }

          async function loadScenarioList() {
            const res = await fetch(window.location.origin + '/scenario/list');
            const data = await res.json();
            const box = document.getElementById('scnStatus');
            box.className = 'status';
            box.innerHTML = `
              <div class="status-title">RECENT REENACTMENTS</div>
              <div class="status-main">${(data.items || []).length}건</div>
              <div class="status-meta" style="font-family:'JetBrains Mono',monospace;font-size:10.5px;">
                ${(data.items || []).slice(0,8).map(i => `${i.created_at.slice(0,19)} · <a href="${i.video_url}" target="_blank" style="color:var(--accent);">${i.name}</a>`).join('<br>')}
              </div>`;
          }

          /* ── COLLAB (V2V / Bus / Bidir) ── */
          // TAB 9 활성화 시 자동 V2V 풀 폴링
          let _v2vPollTimer = null;
          (function setupV2VAutoPoll(){
            const tab9 = document.querySelector('[data-tab="tab9"]');
            if (!tab9) return;
            const poll = () => {
              if (document.getElementById('tab9').classList.contains('active')) {
                const iid = document.getElementById('cv_iid')?.value;
                if (iid) refreshV2VPool(iid);
              }
            };
            tab9.addEventListener('click', () => {
              clearInterval(_v2vPollTimer);
              poll();
              _v2vPollTimer = setInterval(poll, 5000);
            });
          })();

          async function seedV2VDemo() {
            const iid = document.getElementById('cv_iid').value;
            const lat = document.getElementById('cv_lat').value;
            const lon = document.getElementById('cv_lon').value;
            try {
              const res = await fetch(window.location.origin + '/collab/v2v/seed-demo?intersection_id=' + iid + '&lat=' + lat + '&lon=' + lon, {method:'POST'});
              const data = await res.json();
              await refreshV2VPool(iid);
              toast('시연용 V2V 차량 ' + data.seeded + '대 게시', 'success');
            } catch(e) { toast('시드 실패', 'error'); }
          }

          async function refreshV2VPool(iid) {
            try {
              const res = await fetch(window.location.origin + '/collab/v2v/intersection/' + iid);
              const data = await res.json();
              document.getElementById('v2vPool').textContent =
                'count=' + data.count + '\n\n' +
                (data.messages || []).map(m =>
                  `${m.device_id || '?'}  hdg=${m.heading_deg}°  spd=${m.speed_kmh}km/h  decel=${m.decel_g||0}\n  detections=${(m.detections||[]).length}  occ=${m.occluded_mass||0}`
                ).join('\n\n');
            } catch(e) { /* ignore */ }
          }

          async function runFusedOccupancy() {
            const fileInput = document.getElementById('cv_file');
            if (!fileInput.files.length) { toast('이미지를 선택하세요', 'warn'); return; }
            const fd = new FormData();
            fd.append('image', fileInput.files[0]);
            fd.append('intersection_id', document.getElementById('cv_iid').value);
            fd.append('ego_lat', document.getElementById('cv_lat').value);
            fd.append('ego_lon', document.getElementById('cv_lon').value);
            fd.append('ego_heading_deg', document.getElementById('cv_head').value);

            showLoader('V2V + Bus + Bidir 결합 추론 중...');
            try {
              const res = await fetch(window.location.origin + '/collab/fused-occupancy', {method:'POST', body: fd});
              const data = await res.json();
              const localP = (data.risk_local_only.p_collision * 100).toFixed(1);
              const fusedP = (data.risk_fused.p_collision * 100).toFixed(1);
              const lift = (data.risk_fused.lift_from_v2v_bus_bidir * 100).toFixed(1);

              document.getElementById('cvDiff').innerHTML = `
                <div class="rank-item"><div class="rank-head"><div class="rank-title">단독 인지</div><span class="badge b-y">${localP}%</span></div>
                  <div class="rank-body">자차 카메라만 사용 (Tesla 식)</div></div>
                <div class="rank-item ${data.risk_fused.p_collision > 0.6 ? 'high' : 'mid'}">
                  <div class="rank-head"><div class="rank-title">⭐ 협업 인지</div><span class="badge b-r">${fusedP}%</span></div>
                  <div class="rank-body">+${lift}% lift · V2V ${data.v2v.peer_count}대 + 정류장 prior + 상행/하행</div></div>`;

              document.getElementById('cvCanvas').innerHTML =
                `<img src="${data.occupancy.grid_b64}" style="width:100%;height:100%;object-fit:contain;background:#050a10;image-rendering:pixelated;"/>`;

              document.getElementById('cvBreakdown').innerHTML = `
                <div>${data.risk_fused.explanation}</div>
                <div style="margin-top:6px;color:var(--accent);">${data.bus_context.boost_reason || '버스 가림 없음'}</div>
                <div style="margin-top:4px;color:${data.bidirectional.hazard_probability > 0.45 ? 'var(--danger)' : 'var(--muted)'};">
                  bidir hazard=${(data.bidirectional.hazard_probability*100).toFixed(0)}% · ${data.bidirectional.insight}</div>
                <div style="margin-top:4px;">${data.v2v.note} · boosted ${data.v2v.boosted_cells} cells (+${data.v2v.added_mass.toFixed(1)} mass)</div>`;

              await refreshV2VPool(document.getElementById('cv_iid').value);
              toast('협업 인지 완료', 'success');
            } catch(e) { toast('실행 실패', 'error'); } finally { hideLoader(); }
          }

          /* ── SHOWREEL ── */
          async function buildShowreel() {
            showLoader('합본 영상 생성 중 (60초 정도 소요)...');
            try {
              const res = await fetch(window.location.origin + '/showreel/build', {method:'POST'});
              if (!res.ok) throw new Error(await res.text());
              const data = await res.json();
              const wrap = document.getElementById('scnVideoWrap');
              wrap.innerHTML = `
                <video controls autoplay muted loop style="width:100%;height:100%;object-fit:contain;background:#000;border-radius:12px;">
                  <source src="${data.video_url}?t=${Date.now()}" type="video/mp4"/>
                </video>`;
              const box = document.getElementById('scnStatus');
              box.className = 'status info';
              box.innerHTML = `
                <div class="status-title">SHOWREEL READY</div>
                <div class="status-main">평균 선행 경고 ${data.average_lead_time_s}초</div>
                <div class="status-meta">
                  포함 시나리오 &nbsp;${data.scenarios.length}<br>
                  프레임 수 &nbsp;${data.frame_count}<br>
                  파일 &nbsp;${data.video_url}
                </div>`;
              toast('합본 영상 생성 완료', 'success');
            } catch(e) { toast('합본 영상 생성 실패', 'error'); } finally { hideLoader(); }
          }

          /* ── K-MaaS ── */
          async function runKmaas() {
            const q = new URLSearchParams({
              origin_lat: document.getElementById('km_olat').value,
              origin_lon: document.getElementById('km_olon').value,
              dest_lat: document.getElementById('km_dlat').value,
              dest_lon: document.getElementById('km_dlon').value,
              risk: document.getElementById('km_risk').value,
            }).toString();
            showLoader('K-MaaS 대안 조회 중...');
            try {
              const res = await fetch(window.location.origin + '/kmaas/alternatives?' + q);
              const data = await res.json();
              const wrap = document.getElementById('kmaasOut');
              wrap.innerHTML = '';
              const head = document.createElement('div');
              head.className = 'rank-item ' + ((data.risk_score||0) >= 10 ? 'high' : 'mid');
              head.innerHTML = `<div class="rank-head"><div class="rank-title">${data.headline||''}</div></div>`;
              wrap.appendChild(head);
              (data.alternatives || []).forEach((a, i) => {
                const div = document.createElement('div');
                div.className = 'rank-item ' + (a.risk_avoidance_score >= 0.85 ? 'high' : 'mid');
                const legs = (a.legs||[]).map(l => `<span class="badge">${l.mode} · ${l.duration_min}분 · ${l.distance_km}km</span>`).join(' ');
                div.innerHTML = `
                  <div class="rank-head">
                    <div class="rank-title">#${i+1} ${a.label}</div>
                    <span class="badge b-y">우회 가치 ${(a.risk_avoidance_score*100).toFixed(0)}%</span>
                  </div>
                  <div class="rank-body">
                    소요 ${a.total_min}분 · 요금 ${a.total_fare.toLocaleString()}원 · CO₂ ${a.total_co2_saved_g}g 절감<br>
                    <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;">${legs}</div>
                  </div>`;
                wrap.appendChild(div);
              });
              toast('K-MaaS 대안 ' + (data.alternatives||[]).length + '건', 'success');
            } catch(e) { toast('K-MaaS 조회 실패', 'error'); } finally { hideLoader(); }
          }

          async function loadKmaasOperator() {
            try {
              const res = await fetch(window.location.origin + '/kmaas/operator-report');
              const data = await res.json();
              document.getElementById('kmaasOpOut').textContent = JSON.stringify(data, null, 2);
            } catch(e) { toast('운영팀 리포트 조회 실패', 'error'); }
          }

          /* ── HAZARD REPORT ── */
          async function generateReport(top) {
            showLoader('Top ' + top + ' 리포트 생성 중...');
            try {
              const res = await fetch(window.location.origin + '/reports/generate?top=' + top, {method:'POST'});
              const data = await res.json();
              document.getElementById('reportOut').innerHTML = `
                <div class="status info" style="margin-top:14px;">
                  <div class="status-title">REPORT GENERATED</div>
                  <div class="status-main">${data.entries}개 교차로 분석 완료</div>
                  <div class="status-meta">
                    HTML &nbsp;<a style="color:var(--accent)" target="_blank" href="${data.html_url}">${data.html_url}</a><br>
                    JSON &nbsp;<a style="color:var(--accent)" target="_blank" href="${data.json_url}">${data.json_url}</a><br>
                    생성 시각 &nbsp;${data.generated_at}
                  </div>
                </div>
                <iframe src="${data.html_url}" style="width:100%;height:540px;margin-top:14px;border:1px solid var(--border);border-radius:14px;background:#fff;"></iframe>`;
              toast('리포트 생성 완료', 'success');
            } catch(e) { toast('리포트 생성 실패', 'error'); } finally { hideLoader(); }
          }

          async function loadReportList() {
            const res = await fetch(window.location.origin + '/reports/list');
            const data = await res.json();
            const items = data.items || [];
            document.getElementById('reportOut').innerHTML = `
              <div class="card" style="margin-top:14px;">
                <div class="section-label">// 최근 ${items.length}건</div>
                ${items.map(i => `
                  <div class="rank-item" style="margin-top:8px;">
                    <div class="rank-head"><div class="rank-title">${i.name}</div><span class="badge b-g">${i.size_kb} KB</span></div>
                    <div class="rank-body">${i.created_at} · <a style="color:var(--accent)" target="_blank" href="${i.html_url}">HTML</a> · <a style="color:var(--accent)" target="_blank" href="${i.json_url}">JSON</a></div>
                  </div>`).join('')}
              </div>`;
          }

          /* ── LIVE SCORECARD COUNTERS ── */
          async function refreshScorecard() {
            try {
              const [fl, sc, rep, fu] = await Promise.all([
                fetch(window.location.origin + '/fleet/stats').then(r=>r.json()).catch(()=>({})),
                fetch(window.location.origin + '/scenario/list').then(r=>r.json()).catch(()=>({items:[]})),
                fetch(window.location.origin + '/reports/list').then(r=>r.json()).catch(()=>({items:[]})),
                fetch(window.location.origin + '/fusion/sources').then(r=>r.json()).catch(()=>({count:0})),
              ]);
              const setIfExists = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
              setIfExists('sc_fleet', (fl.total ?? 0) + ' 건');
              setIfExists('sc_scenarios', (sc.items||[]).length + ' 편');
              setIfExists('sc_reports', (rep.items||[]).length + ' 개');
              setIfExists('sc_fusion', (fu.count ?? 0) + '종');
            } catch(e) {}
          }

          loadIntersections();
          refreshAll();
          refreshScorecard();
          setInterval(refreshScorecard, 15000);
        </script>
    </body>
    </html>
    """