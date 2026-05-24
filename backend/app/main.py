from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import os

from .database import Base, engine
from .routers import (
    intersections, signals, events, risk, detect,
    occupancy, fleet, fusion, dsz, kmaas, reports, heatmap, collab, health, summary, benchmark,
    impact, positioning, metrics, qa, policy,
    privacy, ai_analytics, competition,
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
app.include_router(health.router, prefix="/healthz", tags=["health"])
app.include_router(summary.router, prefix="/summary", tags=["summary"])
app.include_router(benchmark.router, prefix="/benchmark", tags=["benchmark"])
app.include_router(impact.router, prefix="/impact", tags=["impact"])
app.include_router(positioning.router, prefix="/positioning", tags=["positioning"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
app.include_router(policy.router, prefix="/policy", tags=["policy"])
app.include_router(qa.router, prefix="/qa", tags=["qa-rag"])
app.include_router(privacy.router, prefix="/privacy", tags=["privacy-가명정보결합"])
app.include_router(ai_analytics.router, prefix="/ai", tags=["ai-analytics"])
app.include_router(competition.router, prefix="/competition", tags=["competition-경진대회"])
if _SCENARIO_OK:
    app.include_router(scenario.router, prefix="/scenario", tags=["scenario"])
if _SHOWREEL_OK:
    app.include_router(showreel.router, prefix="/showreel", tags=["showreel"])


# RAG 인덱스 자동 복구 — 재시작 후 chunks.jsonl + embeddings.npy 디스크에서 복원
@app.on_event("startup")
def _qa_restore_index():
    """QA 인덱스 디스크 복구 (가벼움). 모델은 첫 /qa/ask 시 lazy load."""
    import logging as _log
    log = _log.getLogger("auraview.qa.startup")
    try:
        from .services import qa_engine
        if qa_engine.restore_index():
            log.info("qa: index restored from disk (%d chunks)", len(qa_engine._state["chunks"]))
        elif os.getenv("QA_AUTOSEED_ON_BOOT", "0") == "1":
            n = qa_engine.autoseed_from_project_docs()
            log.info("qa: autoseed indexed %d chunks", n)
        else:
            log.info("qa: no index — POST /qa/index-docs to seed (admin)")
    except Exception as exc:
        log.warning("qa: startup skip (%s)", exc)


# 데모 데이터 자동 시드 — 재배포 후 빈 DB 인 경우만 (idempotent)
@app.on_event("startup")
def _autoseed_demo():
    """재배포 시 events / fleet / v2v 가 비어있으면 자동 시드.

    실 데이터가 충분히 있으면 (events ≥ 5 unique intersection) skip.
    """
    import logging as _log
    log = _log.getLogger("auraview.autoseed")
    try:
        # events seed (8 Seoul intersections)
        from .database import SessionLocal
        from .models import BlindSignalEvent
        from .routers.events import DEMO_INTERSECTIONS  # type: ignore
        db = SessionLocal()
        try:
            existing = {row[0] for row in db.query(BlindSignalEvent.intersection_id).distinct().all()}
            if len(existing) < 5:
                for iid, name, lat, lon, count, dur, sig, obs in DEMO_INTERSECTIONS:
                    if iid in existing:
                        continue
                    for k in range(count):
                        jitter = 0.7 + (k % 5) * 0.15
                        ev = BlindSignalEvent(
                            intersection_id=iid, user_lat=lat, user_lon=lon,
                            event_duration=round(dur * jitter, 2),
                            obstacle_type=obs, signal_state=sig,
                            signal_remain_time=None, image_path=None,
                        )
                        db.add(ev)
                db.commit()
                log.info("[autoseed] events seeded for %d intersections", len(DEMO_INTERSECTIONS))
        finally:
            db.close()
    except Exception as exc:
        log.warning("[autoseed] events seed failed: %s", exc)

    # fleet seed
    try:
        from .routers.fleet import seed_demo_fleet  # type: ignore
        r = seed_demo_fleet(force=False)
        log.info("[autoseed] fleet: %s", r.get("status"))
    except Exception as exc:
        log.warning("[autoseed] fleet seed failed: %s", exc)

    # v2v seed (4 intersections)
    try:
        from .routers.collab import v2v_seed_demo  # type: ignore
        for iid, lat, lon in [("1007", 37.5547, 127.1295), ("2024", 37.4979, 127.0276),
                               ("4011", 37.5133, 127.1000), ("3015", 37.5723, 126.9769)]:
            v2v_seed_demo(intersection_id=iid, lat=lat, lon=lon)
        log.info("[autoseed] v2v seeded for 4 intersections")
    except Exception as exc:
        log.warning("[autoseed] v2v seed failed: %s", exc)


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
_mount_static(app, ["static", "summary"], "/submission")
_mount_static(app, ["static", "competition"], "/competition")
_mount_static(app, ["static", "story"], "/story")        # v3 2026-05-16: 일반인용 30초 스토리 페이지
_mount_static(app, ["static", "reel"], "/reel")          # v5 2026-05-16: 72초 자동재생 시네마틱 시퀀스 (영상 대체)
_mount_static(app, ["static", "gallery"], "/gallery")    # v6 2026-05-17: 17 SVG 시각자료 갤러리 (필터+라이트박스)
_mount_static(app, ["static", "bev3d"], "/bev3d")        # v7 2026-05-18: AuraView 자체 Three.js 3D BEV (네이티브앱 WebView 임베드용)
_mount_static(app, ["static", "scorecard"], "/scorecard")  # v7 2026-05-18: 심사 가산점 25점 적격 증거표 (judge-facing)
_mount_static(app, ["static", "privacy"], "/privacy")    # v7 2026-05-18: 가명정보 처리 파이프라인 라이브 데모 (5pt 실증)
_mount_static(app, ["static", "safezone"], "/safezone")  # v7 2026-05-18: 안전구역 라이브 대시보드 (5pt 실증)
_mount_static(app, ["static", "policy"], "/policy")      # v8 2026-05-18: 수집→통계분석→정책의사결정 (Tesla fleet)
_mount_static(app, ["static", "fleet"], "/fleet-dash")   # v12.17 2026-05-21: 라이브 수집 대시보드 (지도 + 피드)
_mount_static(app, ["static"], "/static")

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
    """루트 → /story (일반인용 30초 스토리 페이지) 자동 이동.

    2026-05-16 v0.10: 일반 방문자가 첫 화면에서 무엇이고 왜 중요한지 즉시 이해하도록.
    개발자는 /story 안에서 /competition, /ui, /docs 로 1-tap 이동 가능.
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/story/", status_code=302)


@app.get("/api")
def api_root():
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
        <script src="https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/controls/OrbitControls.js"></script>
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

            /* ── MOBILE (≤ 720px) ── */
            @media (max-width: 720px) {
              header, .tabs, .content { padding-left: 12px; padding-right: 12px; }
              h1 { font-size: 22px; }
              .tabs { gap: 4px; flex-wrap: wrap; padding-top: 8px; padding-bottom: 8px; }
              .tab { font-size: 11px; padding: 8px 10px; }
              .tab-panel { padding-top: 10px; }
              .card { padding: 14px; }
              .card h2, .card h3 { font-size: 16px; }
              .ranking { gap: 8px; }
              .form-grid { grid-template-columns: 1fr !important; }
              .preview-wrap { min-height: 220px !important; height: auto !important; }
              #map { min-height: 280px !important; }
              /* 표 가로 스크롤 */
              table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
              table thead, table tbody { display: table; width: 100%; }
              /* freshness/Top-N 그리드 */
              #freshGrid, #topInxList { grid-template-columns: repeat(2, 1fr) !important; }
              #impactScn { grid-template-columns: 1fr !important; }
              /* metric grid 더 작게 */
              #metricGrid { grid-template-columns: repeat(2, 1fr) !important; }
              /* 비디오 wrap 너무 크지 않게 */
              video { width: 100% !important; max-height: 240px; }
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

        <!-- v12.65: 라이브 status strip — 페이지 첫 진입 즉시 '실시간' 시그널 -->
        <div id="liveStripUi" style="position:sticky;top:0;z-index:200;display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:11px 22px;background:linear-gradient(90deg,rgba(0,200,255,0.10),rgba(124,58,237,0.06));backdrop-filter:blur(12px);border-bottom:1px solid rgba(0,200,255,0.30);font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.2px;font-weight:800;">
          <span style="display:inline-flex;align-items:center;gap:7px;color:#00E09A;">
            <span style="width:9px;height:9px;border-radius:50%;background:#00E09A;box-shadow:0 0 8px #00E09A;animation:livepulse 1.4s infinite;"></span>LIVE
          </span>
          <span style="color:#5a7a9a;">|</span>
          <span style="color:#e2eaf5;">23 SRC <span id="liveSrcCount" style="color:#00C8FF;font-weight:900;">— / 23</span> · live <span id="liveSrcLive" style="color:#00E09A;font-weight:900;">—</span> stub <span id="liveSrcStub" style="color:#FFB020;font-weight:900;">—</span></span>
          <span style="color:#5a7a9a;">|</span>
          <span style="color:#e2eaf5;">FLEET <span id="liveFleetActive" style="color:#FFB020;font-weight:900;">—</span> 디바이스(5m) · <span id="liveFleet1m" style="color:#00C8FF;font-weight:900;">—</span> 이벤트(1m) · <span id="liveFleetTotal" style="color:#e2eaf5;font-weight:900;">—</span> 누적</span>
          <span style="color:#5a7a9a;">|</span>
          <span style="color:#e2eaf5;">RISK <span id="liveRisk" style="color:#00E09A;font-weight:900;">—</span> <span id="liveRiskLv" style="color:#7C8AA8;font-weight:700;font-size:10px;">—</span></span>
          <span id="liveAge" style="margin-left:auto;color:#5a7a9a;font-size:10px;">갱신 —s 전</span>
        </div>
        <style>
          @keyframes livepulse { 0%,100% {opacity:1;transform:scale(1);} 50% {opacity:0.45;transform:scale(0.85);} }
        </style>
        <script>
          (function liveStripLoop() {
            const fmtAge = (ts) => { const s = Math.round((Date.now()-ts)/1000); return s+'s 전'; };
            async function tick() {
              try {
                const [src, live, fus] = await Promise.all([
                  fetch('/fusion/sources').then(r=>r.json()).catch(()=>null),
                  fetch('/fleet/live?limit=1').then(r=>r.json()).catch(()=>null),
                  fetch('/fusion/intersection/1007').then(r=>r.json()).catch(()=>null),
                ]);
                if (src && src.sources) {
                  const total = src.sources.length;
                  const ln = src.sources.filter(s => s.mode === 'live').length;
                  document.getElementById('liveSrcCount').textContent = total + ' / 23';
                  document.getElementById('liveSrcLive').textContent = ln;
                  document.getElementById('liveSrcStub').textContent = total - ln;
                }
                if (live) {
                  document.getElementById('liveFleetActive').textContent = live.active_devices_5m ?? 0;
                  document.getElementById('liveFleet1m').textContent = live.events_1m ?? 0;
                  document.getElementById('liveFleetTotal').textContent = (live.events_total ?? 0).toLocaleString();
                }
                if (fus && fus.fusion_summary) {
                  const risk = (fus.fusion_summary.fusion_risk_score ?? 0).toFixed(3);
                  const lv = fus.fusion_summary.risk_level || 'LOW';
                  const color = lv === 'HIGH' ? '#FF4040' : lv === 'MEDIUM' ? '#FFB020' : '#00E09A';
                  const r = document.getElementById('liveRisk');
                  r.textContent = risk;
                  r.style.color = color;
                  document.getElementById('liveRiskLv').textContent = lv + ' · 한양대 1007';
                }
                document.getElementById('liveAge').textContent = '갱신 ' + fmtAge(Date.now() - 100) ;
              } catch (e) {}
            }
            tick();
            setInterval(tick, 5000);
          })();
        </script>

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
              <div class="eyebrow">AuraView · 실시간 라이브 대시보드</div>
              <h1><em>AuraView</em> Dashboard</h1>
              <div class="subtitle">23종 공공데이터 라이브 융합 · 위험점수 · 익명 이벤트 수집 · 위험 hotspot — 5s 폴링. 데모 페이지(BEV 3D/Fleet/V2V/사고 재현/K-MaaS)는 우측 메뉴.</div>
            </div>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
              <a href="/story/" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:1.5px;color:#0a0e18;padding:9px 16px;background:linear-gradient(135deg,#FFB020,#FF6B6B);border:1px solid rgba(255,176,32,0.7);border-radius:99px;font-weight:900;box-shadow:0 0 18px rgba(255,176,32,0.45);">📖 일반인용 30초 스토리</a>
              <a href="/reel/" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:1.5px;color:#fff;padding:9px 16px;background:linear-gradient(135deg,#FF4444,#7c3aed);border:1px solid rgba(255,68,68,0.7);border-radius:99px;font-weight:900;box-shadow:0 0 18px rgba(255,68,68,0.45);">🎥 1분 시연</a>
              <a href="/competition/" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:#fff;padding:7px 14px;background:linear-gradient(135deg,rgba(0,224,154,0.30),rgba(0,200,255,0.20));border:1px solid rgba(0,224,154,0.55);border-radius:99px;font-weight:700;">🏆 JUDGE HUB</a>
              <a href="/submission/" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:var(--safe);padding:7px 14px;border:1px solid rgba(0,224,154,0.4);border-radius:99px;">≡ SUMMARY</a>
              <a href="https://github.com/leelang7/AuraView/releases/latest/download/AuraView_Whitepaper.pdf" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:var(--warn);padding:7px 14px;border:1px solid rgba(255,176,32,0.4);border-radius:99px;">📑 WHITEPAPER PDF</a>
              <a href="/slides/" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:var(--accent);padding:7px 14px;border:1px solid rgba(0,200,255,0.3);border-radius:99px;">▶ SLIDES</a>
              <a href="/kiosk/" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:var(--accent2);padding:7px 14px;border:1px solid rgba(124,58,237,0.4);border-radius:99px;">⏵ KIOSK</a>
              <div class="header-badge">
                <div class="dot"></div>
                SYSTEM ONLINE
              </div>
            </div>
          </div>
        </header>

        <!-- ═══════════════════════════════════════════════════════════════════════
             v12.72: 메인 라이브 dashboard — 9탭 위에 핵심 정보 한눈 표시
             구조: Hero strip + 6 stats + 지도(좌)/이벤트(우) 2-col + 23 src grid + breakdown + hotspot + verify
             기존 9탭은 그대로 유지 (BEV/Fleet Learning/V2V/사고재현 등 정교한 데모는 탭에서)
             5s Promise.all 폴링 7 endpoint
             ═══════════════════════════════════════════════════════════════════════ -->
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
          .av-wrap{max-width:1480px;margin:0 auto 28px;padding:0 20px;}
          .av-hero{padding:18px 22px;background:linear-gradient(135deg,rgba(0,200,255,0.12),rgba(124,58,237,0.06));border:1px solid rgba(0,200,255,0.30);border-radius:14px;display:flex;flex-wrap:wrap;gap:24px;align-items:center;margin-bottom:14px;}
          .av-hero .head{flex:1;min-width:300px;}
          .av-hero .eye{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2.4px;color:#00C8FF;font-weight:900;margin-bottom:4px;}
          .av-hero h2{font-size:22px!important;font-weight:900;color:#E7ECF5!important;letter-spacing:-0.4px;line-height:1.25;margin:0 0 5px 0!important;}
          .av-hero h2 em{font-style:normal;background:linear-gradient(120deg,#00E09A,#00C8FF 55%,#7C3AED 100%);-webkit-background-clip:text;background-clip:text;color:transparent;}
          .av-hero .sub{font-size:11.5px;color:#7C8AA8;}
          .av-hero .kpis{display:grid;grid-template-columns:repeat(4,auto);gap:18px;align-items:center;}
          .av-hero .kpi{text-align:center;}
          .av-hero .kpi .v{font-size:24px;font-weight:900;font-variant-numeric:tabular-nums;letter-spacing:-1px;}
          .av-hero .kpi .l{font-size:9px;letter-spacing:1.5px;color:#7C8AA8;font-weight:800;margin-top:2px;}
          .av-stats{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:14px;}
          @media (max-width:1200px){.av-stats{grid-template-columns:repeat(3,1fr);}}
          .av-st{background:#0A1018;border:1px solid #1A2438;border-radius:10px;padding:11px 13px;}
          .av-st .l{font-size:9px;letter-spacing:1.8px;color:#7C8AA8;font-weight:800;margin-bottom:3px;}
          .av-st .v{font-size:22px;font-weight:900;color:#E7ECF5;font-variant-numeric:tabular-nums;letter-spacing:-0.5px;line-height:1.05;}
          .av-st .v.safe{color:#00E09A;} .av-st .v.warn{color:#FFB020;} .av-st .v.danger{color:#FF4040;} .av-st .v.accent{color:#00C8FF;}
          .av-st .sub{font-size:10px;color:#7C8AA8;margin-top:2px;font-weight:700;}
          .av-row{display:grid;grid-template-columns:1.45fr 1fr;gap:14px;margin-bottom:14px;}
          @media (max-width:1100px){.av-row{grid-template-columns:1fr;}}
          .av-panel{background:#0A1018;border:1px solid #1A2438;border-radius:12px;padding:14px;}
          .av-panel h3{font-size:12.5px!important;font-weight:900;letter-spacing:0.4px;margin:0 0 8px 0!important;display:flex;align-items:center;justify-content:space-between;color:#E7ECF5!important;}
          .av-badge{font-size:10px;font-weight:800;letter-spacing:0.6px;padding:3px 8px;border-radius:99px;background:rgba(0,224,154,0.14);color:#00E09A;border:1px solid rgba(0,224,154,0.35);display:inline-flex;align-items:center;gap:5px;}
          .av-badge .ring{width:6px;height:6px;border-radius:50%;background:#00E09A;box-shadow:0 0 6px #00E09A;animation:avp 1.4s infinite;}
          @keyframes avp{0%,100%{opacity:1;}50%{opacity:0.4;}}
          .av-desc{color:#7C8AA8;font-size:11px;margin-bottom:11px;}
          #avMap{height:440px;border-radius:10px;overflow:hidden;background:#0A0F18;border:1px solid #1A2438;}
          .av-feed{max-height:440px;overflow-y:auto;}
          .av-feed::-webkit-scrollbar{width:5px;}
          .av-feed::-webkit-scrollbar-thumb{background:#1A2438;border-radius:99px;}
          .av-ev{display:grid;grid-template-columns:auto 1fr auto;gap:8px;padding:7px 10px;background:#070C16;border:1px solid #1A2438;border-radius:8px;margin-bottom:5px;}
          .av-ev .ic{width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;}
          .av-ev .ic.hi{background:rgba(255,68,68,0.16);color:#FF4040;}
          .av-ev .ic.mi{background:rgba(255,176,32,0.16);color:#FFB020;}
          .av-ev .ic.lo{background:rgba(0,224,154,0.14);color:#00E09A;}
          .av-ev .meta{font-size:11px;color:#E7ECF5;font-weight:700;}
          .av-ev .meta .sub{display:block;font-size:9.5px;color:#7C8AA8;font-weight:600;font-family:monospace;margin-top:1px;}
          .av-ev .ent{font-size:13px;font-weight:900;font-variant-numeric:tabular-nums;align-self:center;}
          .av-ev .ent.hi{color:#FF4040;} .av-ev .ent.mi{color:#FFB020;} .av-ev .ent.lo{color:#00E09A;}
          .av-src-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:6px;}
          .av-src{background:#070C16;border:1px solid #1A2438;border-radius:8px;padding:8px 10px;cursor:pointer;transition:all 0.12s;}
          .av-src:hover{border-color:#00C8FF;transform:translateY(-1px);}
          .av-src .row1{display:flex;align-items:center;gap:5px;margin-bottom:3px;}
          .av-src .led{width:6px;height:6px;border-radius:50%;background:#404858;flex-shrink:0;}
          .av-src.live .led{background:#00E09A;box-shadow:0 0 5px #00E09A;}
          .av-src.stub .led{background:#FFB020;box-shadow:0 0 5px #FFB020;}
          .av-src .nm{font-size:11px;font-weight:800;color:#E7ECF5;line-height:1.2;flex:1;}
          .av-src .age{font-size:8.5px;color:#4E5C78;font-family:monospace;}
          .av-src .val{font-size:11px;color:#00C8FF;font-weight:700;font-family:monospace;margin-top:3px;}
          .av-bd{display:grid;grid-template-columns:90px 1fr 78px;gap:8px;align-items:center;font-size:10.5px;}
          .av-bd .nm{color:#E7ECF5;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
          .av-bd .bar{height:12px;background:#0A0F18;border-radius:3px;overflow:hidden;position:relative;}
          .av-bd .bar .fill{height:100%;border-radius:3px;opacity:0.85;}
          .av-bd .bar .lab{position:absolute;left:5px;top:0;line-height:12px;font-size:9px;color:#E7ECF5;font-family:monospace;}
          .av-bd .ct{text-align:right;font-family:monospace;color:#7C8AA8;font-size:9.5px;}
          .av-tab-divider{margin:18px 0 12px;padding:14px 18px;background:rgba(124,58,237,0.06);border:1px solid rgba(124,58,237,0.25);border-radius:12px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;}
          .av-tab-divider .lab{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:2px;color:#7C3AED;font-weight:900;}
          .av-tab-divider .txt{color:#E7ECF5;font-size:13px;font-weight:800;}
          .av-tab-divider .arr{margin-left:auto;color:#7C3AED;font-size:20px;animation:avarr 1.5s infinite;}
          @keyframes avarr{0%,100%{transform:translateY(0);}50%{transform:translateY(4px);}}
        </style>
        <div class="av-wrap">
          <!-- Hero -->
          <div class="av-hero">
            <div class="head">
              <div class="eye">// AURAVIEW K-PERCEPTION · 2026 국토교통 데이터활용 경진대회</div>
              <h2>한국 도로 23종 공공데이터를 융합해 <em>평균 3.38초 먼저</em> 위험을 알려줍니다</h2>
              <div class="sub">국토부 DSZ · TAAS 결합 · k≥5 가명 · cv2 PII 블러 · ML Kit on-device · 위치 인식 stub · 22 sub-fetch 병렬 (cold 6.5s)</div>
            </div>
            <div class="kpis">
              <div class="kpi"><div class="v" style="color:#00C8FF;">23</div><div class="l">공공 API</div></div>
              <div class="kpi"><div class="v" style="color:#00E09A;">3.38<span style="font-size:14px;">s</span></div><div class="l">선행 경고</div></div>
              <div class="kpi"><div class="v" style="color:#FFB020;">21<span style="font-size:14px;">명/년</span></div><div class="l">사망 감소</div></div>
              <div class="kpi"><div class="v" style="color:#7C3AED;">0.94</div><div class="l">AI AUC</div></div>
            </div>
          </div>
          <!-- 6 stats -->
          <div class="av-stats">
            <div class="av-st"><div class="l">공공데이터</div><div class="v accent" id="avSrc">— / 23</div><div class="sub" id="avSrcSub">live · stub</div></div>
            <div class="av-st"><div class="l">위험점수 (1007)</div><div class="v" id="avRisk">—</div><div class="sub" id="avRiskSub">한양대 · 5s</div></div>
            <div class="av-st"><div class="l">활성 폰 (5분)</div><div class="v safe" id="avDev">—</div><div class="sub">실시간 fleet</div></div>
            <div class="av-st"><div class="l">최근 1분 이벤트</div><div class="v accent" id="avEv1m">—</div><div class="sub">/fleet/contribute</div></div>
            <div class="av-st"><div class="l">누적 익명 이벤트</div><div class="v" id="avEvTot">—</div><div class="sub">manifest.jsonl</div></div>
            <div class="av-st"><div class="l">파이프라인</div><div class="v safe" id="avVer">— / 6</div><div class="sub" id="avVerSub">자가검증</div></div>
          </div>
          <!-- Map (left, larger) + Recent events (right) — 2-col 한 row -->
          <div class="av-row">
            <section class="av-panel">
              <h3>🗺 위험지도 — 8 known + 익명 이벤트 + 정책 hotspot
                <span class="av-badge"><span class="ring"></span>OSM · 라이브</span>
              </h3>
              <div class="av-desc">
                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#00C8FF;box-shadow:0 0 5px #00C8FF;vertical-align:middle;margin-right:3px;"></span>파란 점 = 8 교차로
                · <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#FF4040;box-shadow:0 0 5px #FF4040;vertical-align:middle;margin-right:3px;"></span>원 = 이벤트 (entropy 비례)
                · <span style="color:#FFB020;font-size:14px;">★</span> = 정책 hotspot
              </div>
              <div id="avMap"></div>
            </section>
            <section class="av-panel">
              <h3>📥 수집 익명 이벤트 — 네이티브앱 자동 업로드
                <span class="av-badge"><span class="ring"></span>/fleet/live</span>
              </h3>
              <div class="av-desc">앱이 4s 주기 카메라 → 6 reason 분류 → 매칭 시 POST /fleet/contribute (k≥5 + 100m 그리드 + PII 블러).</div>
              <div id="avFeed" class="av-feed">
                <div style="text-align:center;color:#7C8AA8;font-size:11px;padding:18px;">⏳ /fleet/live 로딩…</div>
              </div>
            </section>
          </div>
          <!-- 23 src grid (full width) + breakdown / hotspot / verify (2-col below) -->
          <section class="av-panel" style="margin-bottom:14px;">
            <h3>📡 23 공공데이터 실시간 호출 — 한양대역 1007 응답<span class="av-badge"><span class="ring"></span>LIVE 5s</span></h3>
            <div class="av-desc">정부/공공기관 23 API. 각 카드 클릭 → fusion JSON 새 탭. <span style="color:#00E09A;">●</span>live=실 API · <span style="color:#FFB020;">●</span>stub=fixture.</div>
            <div id="avSrcGrid" class="av-src-grid">
              <div style="grid-column:1/-1;text-align:center;color:#7C8AA8;font-size:11px;padding:24px;">⏳ /fusion/sources + /fusion/intersection/1007 로딩…</div>
            </div>
          </section>
          <div class="av-row">
            <section class="av-panel">
              <h3>⚙ Fusion 엔진 — 23 소스 가중 융합 기여도<span class="av-badge"><span class="ring"></span>/fusion/risk-breakdown</span></h3>
              <div class="av-desc">22 sub-fetch ThreadPool(12) 병렬 → 17 가중치 → fusion_risk_score [0,1]. 기여도 상위 10:</div>
              <div id="avBd" style="max-height:280px;overflow-y:auto;display:flex;flex-direction:column;gap:3px;">
                <div style="text-align:center;color:#7C8AA8;font-size:11px;padding:14px;">⏳ /fusion/risk-breakdown 로딩…</div>
              </div>
            </section>
            <section class="av-panel">
              <h3>⚖ 위험 hotspot Top10 — 정책 의사결정<span class="av-badge"><span class="ring"></span>/policy/stats</span></h3>
              <div class="av-desc">TAAS 사고통계 + 정책 가중 + 시간대. iid 매핑 시 risk-breakdown drill-down.</div>
              <div id="avHot" style="display:flex;flex-direction:column;gap:5px;max-height:280px;overflow-y:auto;">
                <div style="text-align:center;color:#7C8AA8;font-size:11px;padding:14px;">⏳ /policy/stats 로딩…</div>
              </div>
            </section>
          </div>
          <!-- divider 안내 — 아래 9탭으로 -->
          <div class="av-tab-divider">
            <span class="lab">⬇ 아래 9탭에서 더 자세히:</span>
            <span class="txt">① 데모 · ② BEV 3D · ③ 융합 · ④ Fleet Learning · ⑤ 캡빌 매트릭스 · ⑥ 사고 재현 · ⑦ K-MaaS · ⑧ 정책 · ⑨ V2V · ⑩ 공공데이터 라이브</span>
            <span class="arr">⬇</span>
          </div>
        </div>
        <script>
          (function avDashboard() {
            const esc = (s) => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            const KI = [
              {iid:'1007', lat:37.5547, lon:127.1295, name:'한양대역'},
              {iid:'2024', lat:37.4979, lon:127.0276, name:'강남역'},
              {iid:'3015', lat:37.5723, lon:126.9769, name:'광화문'},
              {iid:'4011', lat:37.5133, lon:127.1000, name:'잠실역'},
              {iid:'5006', lat:37.5556, lon:126.9367, name:'신촌'},
              {iid:'6022', lat:37.4766, lon:126.9816, name:'사당역'},
              {iid:'7045', lat:37.5611, lon:127.0376, name:'왕십리역'},
              {iid:'8033', lat:37.5403, lon:127.0700, name:'건대입구'},
            ];
            const map = L.map('avMap', { zoomControl: true, attributionControl: false }).setView([37.5500, 127.020], 12);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 19, subdomains: 'abcd' }).addTo(map);
            KI.forEach(it => L.circleMarker([it.lat, it.lon], { radius: 7, color: '#00C8FF', fillColor: '#00C8FF', fillOpacity: 0.5, weight: 2 }).bindPopup('<b>' + it.name + '</b><br><code>iid=' + it.iid + '</code><br><a href="/fusion/risk-breakdown/' + it.iid + '" target="_blank">risk-breakdown →</a>').addTo(map));
            const evL = L.layerGroup().addTo(map), hotL = L.layerGroup().addTo(map);
            const SVAL = (id, sum, sd) => {
              switch (id) {
                case 'signal': { const it = sd && sd.body && sd.body.items && sd.body.items.item; const v = (it && it.stPdsgSttsNm) || '?'; return v==='go'?'진행':v==='warning'?'주의':v==='stop-And-Remain'?'정지':v; }
                case 'vds': return sum && sum.avg_vds_speed_kmh != null ? '평균 ' + sum.avg_vds_speed_kmh + ' km/h' : '—';
                case 'incidents': return '활성 ' + ((sum && sum.active_incidents) || 0) + '건';
                case 'taas': return '반경 ' + ((sum && sum.taas_accidents_nearby) || 0) + '건';
                case 'its': return '표준링크';
                case 'dsz': return 'k≥5 결합';
                case 'weather': return (sum && sum.weather_raining) ? '우천 +' + Math.round((sum.wet_road_risk_boost||0)*100) + '%' : '맑음';
                case 'medical': return (sum && sum.nearest_ER_load) ? 'ER ' + Math.round(sum.nearest_ER_load*100) + '%' : '—';
                case 'bike': return (sum && sum.bike_lane_risk_boost) ? '+' + Math.round(sum.bike_lane_risk_boost*100) + '%' : '—';
                case 'school_zone': return (sum && sum.in_school_zone) ? '진입 ×' + (sum.school_zone_multiplier||1).toFixed(1) : '구역밖';
                case 'black_ice': return (sum && sum.black_ice_risk) ? '결빙 +' + Math.round((sum.freeze_risk_boost||0)*100) + '%' : '안전';
                case 'pedestrian_hotspot': return (sum && sum.in_pedestrian_hotspot) ? '+' + Math.round((sum.ped_hotspot_boost||0)*100) + '%' : '—';
                case 'air_quality': return 'PM10 ' + Math.round((sum && sum.pm10_avg) || 0);
                case 'school_route': return (sum && sum.on_school_route) ? '통학중' : '—';
                case 'ev_charger': return (sum && sum.near_ev_station) ? 'EV ' + Math.round((sum.ev_dwelling_likelihood||0)*100) + '%' : '—';
                case 'road_surface': return (sum && sum.road_surface) || 'dry';
                case 'vehicle_inspection': return Math.round(((sum && sum.inspection_fail_rate_district) || 0)*100) + '%';
                case 'dtg': return ((sum && sum.dtg_danger_score) || 0).toFixed(2);
                case 'nfa_dispatch': return '×' + ((sum && sum.nfa_severity_multiplier) || 1).toFixed(2);
                case 'road_age': return Math.round(((sum && sum.road_aged_15y_plus_pct) || 0)*100) + '%';
                case 'av_hub': return 'V2X ' + Math.round(((sum && sum.av_confidence) || 0)*100) + '%';
                case 'police_cam': return ((sum && sum.enforcement_cam_count) || 0) + '대';
                case 'crosswalk': return (sum && sum.approaching_crosswalk) ? '50m 접근⚠' : (((sum && sum.crosswalk_count_within_radius) || 0) + '개소');
                default: return '—';
              }
            };
            async function tick() {
              try {
                const [src, fus, live, pol, bd, ver] = await Promise.all([
                  fetch('/fusion/sources').then(r=>r.json()).catch(()=>null),
                  fetch('/fusion/intersection/1007').then(r=>r.json()).catch(()=>null),
                  fetch('/fleet/live?limit=12').then(r=>r.json()).catch(()=>null),
                  fetch('/policy/stats').then(r=>r.json()).catch(()=>null),
                  fetch('/fusion/risk-breakdown/1007').then(r=>r.json()).catch(()=>null),
                  fetch('/fleet/verify').then(r=>r.json()).catch(()=>null),
                ]);
                if (src && src.sources) {
                  const ss = src.sources, ln = ss.filter(s=>s.mode==='live').length;
                  document.getElementById('avSrc').textContent = ss.length + ' / 23';
                  document.getElementById('avSrcSub').textContent = 'live ' + ln + ' · stub ' + (ss.length-ln);
                }
                if (fus && fus.fusion_summary) {
                  const s = fus.fusion_summary, r = (s.fusion_risk_score == null ? 0 : s.fusion_risk_score).toFixed(3);
                  const lv = s.risk_level || 'LOW', col = lv==='HIGH'?'danger':lv==='MEDIUM'?'warn':'safe';
                  const hR = document.getElementById('avRisk'); hR.textContent = r + ' ' + lv; hR.className = 'v ' + col;
                }
                if (live) {
                  document.getElementById('avDev').textContent = live.active_devices_5m || 0;
                  document.getElementById('avEv1m').textContent = live.events_1m || 0;
                  document.getElementById('avEvTot').textContent = (live.events_total || 0).toLocaleString();
                  const evs = live.events || [];
                  const fh = evs.length === 0 ? '<div style="text-align:center;color:#7C8AA8;font-size:11px;padding:18px;">아직 업로드 없음 — 네이티브앱 REC 활성화 시 표시</div>'
                    : evs.slice(0,10).map(ev => {
                        const ent = ev.entropy || 0;
                        const cls = ent >= 0.8 ? 'hi' : ent >= 0.6 ? 'mi' : 'lo';
                        const ic = ent >= 0.8 ? '⚠' : ent >= 0.6 ? '⚡' : '●';
                        const ts = ev.ts ? new Date(ev.ts.endsWith('Z') ? ev.ts : ev.ts + 'Z') : null;
                        const diff = ts ? Math.floor((Date.now() - ts.getTime())/1000) : 0;
                        const tStr = diff < 60 ? diff+'s ago' : Math.floor(diff/60)+'m ago';
                        return '<div class="av-ev"><div class="ic '+cls+'">'+ic+'</div><div class="meta">'+esc(ev.reason||'?')+' @ '+esc(ev.intersection_id||'—')+'<span class="sub">'+esc((ev.pseudo_device||'?').slice(0,12))+'… · '+tStr+'</span></div><div class="ent '+cls+'">'+ent.toFixed(2)+'</div></div>';
                      }).join('');
                  document.getElementById('avFeed').innerHTML = fh;
                  // 이벤트 지도 마커
                  evL.clearLayers();
                  evs.forEach(ev => { if (ev.lat==null||ev.lon==null) return; const ent=ev.entropy||0; const c=ent>=0.8?'#FF4040':ent>=0.6?'#FFB020':'#00E09A';
                    L.circleMarker([ev.lat,ev.lon],{radius:5+ent*6,color:c,fillColor:c,fillOpacity:0.6,weight:1}).bindPopup('<b>'+esc(ev.reason||'?')+'</b><br>ent='+ent.toFixed(2)).addTo(evL); });
                }
                if (ver && ver.components) {
                  const cs = Object.values(ver.components), okN = cs.filter(c=>c.ok!==false).length;
                  const hV = document.getElementById('avVer'); hV.textContent = okN + ' / ' + cs.length;
                  hV.className = 'v ' + (ver.overall_ok?'safe':'warn');
                  document.getElementById('avVerSub').textContent = ver.overall_ok ? 'OVERALL OK' : '일부 비정상';
                }
                if (bd && bd.components_sorted_by_contribution) {
                  const its = bd.components_sorted_by_contribution.slice(0,10);
                  const mx = Math.max(0.001, ...its.map(x=>x.contribution));
                  document.getElementById('avBd').innerHTML = its.map(c => { const pct=(c.contribution/mx*100).toFixed(0); const ca=c.contribution>0.02?'#FFB020':c.contribution>0.005?'#00C8FF':'#5A7090';
                    return '<div class="av-bd"><div class="nm">'+esc(c.label)+'</div><div class="bar"><div class="fill" style="width:'+pct+'%;background:'+ca+';"></div><div class="lab">'+esc(c.raw)+'</div></div><div class="ct">'+c.contribution.toFixed(4)+' ×'+c.weight+'</div></div>'; }).join('');
                }
                if (src && src.sources && fus) {
                  const fS = fus.sources || {}, sm = fus.fusion_summary || {};
                  document.getElementById('avSrcGrid').innerHTML = src.sources.map(s => { const md=s.mode||'stub'; const age=s.age_s!=null?Math.round(s.age_s)+'s':'—'; const sd=fS[s.id]?fS[s.id].data:null; const val=SVAL(s.id,sm,sd);
                    return '<div class="av-src '+md+'" onclick="window.open(\\'/fusion/intersection/1007\\',\\'_blank\\')"><div class="row1"><span class="led"></span><span class="nm">'+esc(s.name||s.id)+'</span><span class="age">'+age+'</span></div><div class="val">'+esc(val)+'</div></div>'; }).join('');
                }
                if (pol && pol.top_hotspots) {
                  hotL.clearLayers();
                  pol.top_hotspots.forEach(h => { if (!h.iid) return; const it=KI.find(x=>x.iid===h.iid); if (!it) return; const c=h.risk>=0.7?'#FF4040':h.risk>=0.5?'#FFB020':'#00E09A';
                    L.marker([it.lat+0.0015,it.lon],{icon:L.divIcon({html:'<div style="font-size:18px;color:'+c+';text-shadow:0 0 4px '+c+';">★</div>',className:'',iconSize:[22,22],iconAnchor:[11,11]})}).bindPopup('<b>#'+h.rank+' '+esc(h.name)+'</b><br>risk='+h.risk.toFixed(2)+'<br><a href="/fusion/risk-breakdown/'+h.iid+'" target="_blank">risk-breakdown →</a>').addTo(hotL); });
                  document.getElementById('avHot').innerHTML = pol.top_hotspots.slice(0,10).map(h => { const cls=h.risk>=0.7?'hi':h.risk>=0.5?'mi':'lo'; const col=cls==='hi'?'#FF4040':cls==='mi'?'#FFB020':'#00E09A'; const url=h.iid?'/fusion/risk-breakdown/'+h.iid:null;
                    return '<div style="background:#070C16;border:1px solid #1A2438;border-left:3px solid '+col+';border-radius:7px;padding:7px 11px;display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;'+(url?'cursor:pointer;':'')+'" '+(url?'onclick="window.open(\\''+url+'\\',\\'_blank\\')"':'')+'><div><div style="font-size:11px;font-weight:800;color:#E7ECF5;">'+h.rank+'. '+esc(h.name)+'</div><div style="font-size:9px;color:#7C8AA8;margin-top:2px;font-family:monospace;">'+esc((h.factors||[]).slice(0,3).join(' · '))+'</div></div><div style="font-size:14px;font-weight:900;color:'+col+';font-variant-numeric:tabular-nums;">'+h.risk.toFixed(2)+'</div></div>'; }).join('');
                }
              } catch (e) { console.error('av tick', e); }
            }
            tick();
            setInterval(tick, 5000);
          })();
        </script>

    </body>
    </html>
    """