from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import intersections, signals, events, risk, detect

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AuraView Prototype")

app.include_router(intersections.router, prefix="/intersections", tags=["intersections"])
app.include_router(signals.router, prefix="/signals", tags=["signals"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(risk.router, prefix="/risk", tags=["risk"])
app.include_router(detect.router, prefix="/detect", tags=["detect"])

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/app", StaticFiles(directory="app"), name="app")


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
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title>AuraView Dashboard</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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

        <header>
          <div class="header-inner">
            <div class="header-left">
              <div class="eyebrow">AuraView · Prototype v0.1</div>
              <h1><em>AuraView</em> Dashboard</h1>
              <div class="subtitle">보이지 않는 신호를 대신 보여주는 시야 차단 대응형 안전 주행 보조 시스템</div>
            </div>
            <div class="header-badge">
              <div class="dot"></div>
              SYSTEM ONLINE
            </div>
          </div>
        </header>

        <div class="tabs">
          <div class="tabs-inner">
            <div class="tab active" data-tab="tab1">① AuraView 데모</div>
            <div class="tab" data-tab="tab2">② 실시간 위험 판단</div>
            <div class="tab" data-tab="tab3">③ 위험 지도화</div>
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

          <!-- TAB 2 -->
          <div class="tab-panel" id="tab2">
            <div class="panel-placeholder">실시간 위험 판단 기능은 준비 중입니다.</div>
          </div>

          <!-- TAB 3 -->
          <div class="tab-panel" id="tab3">
            <div class="panel-placeholder">위험 지도화 기능은 준비 중입니다.</div>
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

          loadIntersections();
          refreshAll();
        </script>
    </body>
    </html>
    """