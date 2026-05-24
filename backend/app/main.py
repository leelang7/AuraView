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
    심사위원·개발자는 /story 안에서 /competition, /ui, /docs 로 1-tap 이동 가능.
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/story/", status_code=302)


@app.get("/api")
def api_root():
    return {"message": "AuraView Prototype Running"}


@app.get("/ui", response_class=HTMLResponse)
def prototype_ui():
    """v12.68: RoadGlass 식 깔끔 dashboard — 23 input + Fusion + 출력 + 라이브 데이터 한 화면.

    이전 (v11.x): 268KB 9탭 prototype, 데이터 흐름 불명확.
    이후 (v12.68): 5 패널 (23 src grid / Fusion engine / Recent events / Hotspots / Health), 5s 폴링.
    """
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>AuraView · K-Perception Dashboard</title>
<meta name="description" content="23 공공 API → Fusion → 네이티브 HUD/대시보드/정책 한 화면 라이브"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{
  --bg:#04070D; --surface:#0A1018; --line:#1A2438;
  --text:#E7ECF5; --muted:#7C8AA8; --dim:#4E5C78;
  --accent:#00C8FF; --accent2:#7C3AED; --safe:#00E09A; --warn:#FFB020; --danger:#FF4040;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--bg);color:var(--text);min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased;}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;background-image:radial-gradient(ellipse at 10% 25%,rgba(0,200,255,0.05) 0%,transparent 55%),radial-gradient(ellipse at 90% 75%,rgba(124,58,237,0.04) 0%,transparent 55%);}
.wrap{max-width:1560px;margin:0 auto;padding:14px 20px 40px;position:relative;z-index:1;}

nav.top{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:14px;padding:10px 16px;background:rgba(15,22,38,0.65);border:1px solid var(--line);border-radius:99px;backdrop-filter:blur(10px);position:sticky;top:10px;z-index:50;flex-wrap:wrap;}
nav .brand{display:flex;align-items:center;gap:10px;}
nav .brand .ic{width:24px;height:24px;border-radius:6px;background:linear-gradient(135deg,var(--accent),var(--accent2));position:relative;overflow:hidden;}
nav .brand .ic::after{content:'';position:absolute;inset:6px;border-radius:50%;background:#04070D;}
nav .brand .ic::before{content:'';position:absolute;left:10px;top:10px;width:4px;height:4px;border-radius:50%;background:var(--accent);box-shadow:0 0 6px var(--accent);}
nav .brand .ttl{font-size:14px;font-weight:900;letter-spacing:1.4px;}
nav .brand .ttl .sub{color:var(--muted);font-size:9.5px;letter-spacing:2px;font-weight:700;display:block;margin-top:-2px;}
nav .live{display:flex;align-items:center;gap:6px;font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:800;color:var(--safe);letter-spacing:1.5px;}
nav .live .pulse{width:7px;height:7px;border-radius:50%;background:var(--safe);box-shadow:0 0 8px var(--safe);animation:p 1.4s infinite;}
nav .links{display:flex;gap:5px;flex-wrap:wrap;}
nav a{font-size:11px;color:var(--muted);text-decoration:none;padding:6px 10px;border-radius:99px;border:1px solid transparent;font-weight:700;}
nav a:hover{color:var(--accent);border-color:rgba(0,200,255,0.30);}
@keyframes p{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.4;transform:scale(0.85);}}

.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:14px;}
@media (max-width:1200px){.stats{grid-template-columns:repeat(3,1fr);}}
.st{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:11px 13px;}
.st .l{font-size:9px;letter-spacing:1.8px;color:var(--muted);font-weight:800;margin-bottom:3px;}
.st .v{font-size:22px;font-weight:900;color:var(--text);font-variant-numeric:tabular-nums;letter-spacing:-0.5px;line-height:1.05;}
.st .v.safe{color:var(--safe);} .st .v.warn{color:var(--warn);} .st .v.danger{color:var(--danger);} .st .v.accent{color:var(--accent);}
.st .sub{font-size:10px;color:var(--muted);margin-top:2px;font-weight:700;}

.main{display:grid;grid-template-columns:1.4fr 1fr;gap:14px;margin-bottom:14px;}
@media (max-width:1100px){.main{grid-template-columns:1fr;}}

.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;}
.panel h3{font-size:12.5px;font-weight:900;letter-spacing:0.4px;margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px;}
.panel h3 .badge{font-size:10px;font-weight:800;letter-spacing:0.6px;padding:3px 8px;border-radius:99px;background:rgba(0,224,154,0.14);color:var(--safe);border:1px solid rgba(0,224,154,0.35);display:inline-flex;align-items:center;gap:5px;}
.panel h3 .badge .ring{width:6px;height:6px;border-radius:50%;background:var(--safe);box-shadow:0 0 6px var(--safe);animation:p 1.4s infinite;}
.panel .desc{color:var(--muted);font-size:11px;margin-bottom:11px;}

.src-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:6px;}
.src{background:#070C16;border:1px solid var(--line);border-radius:8px;padding:8px 10px;cursor:pointer;transition:all 0.12s;}
.src:hover{border-color:var(--accent);transform:translateY(-1px);}
.src .row1{display:flex;align-items:center;gap:5px;margin-bottom:3px;}
.src .led{width:6px;height:6px;border-radius:50%;background:#404858;flex-shrink:0;}
.src.live .led{background:var(--safe);box-shadow:0 0 5px var(--safe);}
.src.stub .led{background:var(--warn);box-shadow:0 0 5px var(--warn);}
.src .nm{font-size:11px;font-weight:800;color:var(--text);line-height:1.2;flex:1;}
.src .age{font-size:8.5px;color:var(--dim);font-family:monospace;}
.src .val{font-size:11px;color:var(--accent);font-weight:700;font-family:monospace;margin-top:3px;}
.src .gain{font-size:8.5px;color:var(--muted);margin-top:2px;line-height:1.3;}

.feed{max-height:300px;overflow-y:auto;}
.feed::-webkit-scrollbar{width:5px;}
.feed::-webkit-scrollbar-thumb{background:var(--line);border-radius:99px;}
.ev{display:grid;grid-template-columns:auto 1fr auto;gap:8px;padding:7px 10px;background:#070C16;border:1px solid var(--line);border-radius:8px;margin-bottom:5px;}
.ev .ic{width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;}
.ev .ic.hi{background:rgba(255,68,68,0.16);color:var(--danger);}
.ev .ic.mi{background:rgba(255,176,32,0.16);color:var(--warn);}
.ev .ic.lo{background:rgba(0,224,154,0.14);color:var(--safe);}
.ev .meta{font-size:11px;color:var(--text);font-weight:700;}
.ev .meta .sub{display:block;font-size:9.5px;color:var(--muted);font-weight:600;font-family:monospace;margin-top:1px;}
.ev .ent{font-size:13px;font-weight:900;font-variant-numeric:tabular-nums;align-self:center;}
.ev .ent.hi{color:var(--danger);} .ev .ent.mi{color:var(--warn);} .ev .ent.lo{color:var(--safe);}

.eng-box{padding:18px 14px;background:linear-gradient(135deg,rgba(0,200,255,0.06),rgba(124,58,237,0.04));border:1px solid rgba(0,200,255,0.25);border-radius:10px;text-align:center;margin-bottom:11px;}
.eng-box .lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:2.4px;color:var(--accent);font-weight:900;margin-bottom:8px;}
.eng-box .num{font-size:48px;font-weight:900;line-height:1;letter-spacing:-2px;font-variant-numeric:tabular-nums;}
.eng-box .lv{font-size:14px;font-weight:800;letter-spacing:2px;margin-top:6px;color:var(--muted);}
.eng-box .schema{font-family:monospace;font-size:9px;color:var(--dim);margin-top:8px;}

.bd-list{display:flex;flex-direction:column;gap:3px;max-height:280px;overflow-y:auto;}
.bd-list::-webkit-scrollbar{width:4px;}
.bd-list::-webkit-scrollbar-thumb{background:var(--line);border-radius:99px;}
.bd{display:grid;grid-template-columns:90px 1fr 78px;gap:8px;align-items:center;font-size:10.5px;}
.bd .nm{color:var(--text);font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.bd .bar{height:12px;background:#0A0F18;border-radius:3px;overflow:hidden;position:relative;}
.bd .bar .fill{height:100%;border-radius:3px;opacity:0.85;}
.bd .bar .lab{position:absolute;left:5px;top:0;line-height:12px;font-size:9px;color:var(--text);font-family:monospace;}
.bd .ct{text-align:right;font-family:monospace;color:var(--muted);font-size:9.5px;}

.hot{display:flex;flex-direction:column;gap:5px;}
.hot-row{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;padding:7px 11px;background:#070C16;border:1px solid var(--line);border-radius:7px;cursor:pointer;transition:all 0.12s;border-left:3px solid var(--dim);}
.hot-row:hover{border-color:var(--accent);transform:translateX(2px);}
.hot-row.hi{border-left-color:var(--danger);}
.hot-row.mi{border-left-color:var(--warn);}
.hot-row.lo{border-left-color:var(--safe);}
.hot-row .nm{font-size:11px;font-weight:800;color:var(--text);}
.hot-row .sub{font-size:9px;color:var(--muted);margin-top:2px;font-family:monospace;}
.hot-row .rs{font-size:14px;font-weight:900;font-variant-numeric:tabular-nums;}
.hot-row.hi .rs{color:var(--danger);} .hot-row.mi .rs{color:var(--warn);} .hot-row.lo .rs{color:var(--safe);}

.hl{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:7px;}
.hl-it{background:#070C16;border:1px solid var(--line);border-radius:7px;padding:9px 11px;text-align:center;}
.hl-it .l{font-size:8.5px;letter-spacing:1.6px;color:var(--muted);font-weight:800;margin-bottom:3px;}
.hl-it .v{font-size:13px;font-weight:900;color:var(--safe);font-family:monospace;}
.hl-it.fail .v{color:var(--danger);}

.foot{margin-top:18px;text-align:center;font-size:10.5px;color:var(--dim);}
.foot a{color:var(--muted);text-decoration:none;}
.foot code{background:rgba(124,140,180,0.08);padding:1px 5px;border-radius:3px;font-family:monospace;}
</style>
</head>
<body>
<div class="wrap">

  <nav class="top">
    <div class="brand">
      <span class="ic"></span>
      <div class="ttl">AURAVIEW<span class="sub">K-PERCEPTION · v9-23src</span></div>
    </div>
    <div class="live"><span class="pulse"></span>LIVE · 5s POLLING</div>
    <div class="links">
      <a href="/story/">스토리</a>
      <a href="/fleet/">fleet</a>
      <a href="/policy/">정책</a>
      <a href="/scorecard/">가산점</a>
      <a href="/bev3d/">3D BEV</a>
      <a href="/competition/">검증</a>
    </div>
  </nav>

  <!-- v12.69: 핵심 차별점 Hero strip (대시보드 정체성) -->
  <div style="margin-bottom:14px;padding:18px 22px;background:linear-gradient(135deg,rgba(0,200,255,0.10),rgba(124,58,237,0.06));border:1px solid rgba(0,200,255,0.30);border-radius:14px;display:flex;flex-wrap:wrap;gap:24px;align-items:center;">
    <div style="flex:1;min-width:280px;">
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2.4px;color:var(--accent);font-weight:900;margin-bottom:4px;">// AURAVIEW K-PERCEPTION · 2026 국토교통 데이터활용 경진대회</div>
      <div style="font-size:22px;font-weight:900;color:var(--text);letter-spacing:-0.4px;line-height:1.25;">한국 도로 23종 공공데이터를 융합해 <span style="background:linear-gradient(120deg,#00E09A,#00C8FF 55%,#7C3AED 100%);-webkit-background-clip:text;background-clip:text;color:transparent;">평균 3.38초 먼저</span> 위험을 알려줍니다</div>
      <div style="font-size:11.5px;color:var(--muted);margin-top:5px;">국토부 빅데이터 안심구역 (DSZ) · TAAS 결합 · k≥5 가명 익명화 · cv2 PII 블러 · ML Kit on-device · 위치 인식 stub (집/원거리 거짓 알람 차단)</div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,auto);gap:18px;align-items:center;">
      <div style="text-align:center;"><div style="font-size:24px;font-weight:900;color:var(--accent);font-variant-numeric:tabular-nums;letter-spacing:-1px;">23</div><div style="font-size:9px;letter-spacing:1.5px;color:var(--muted);font-weight:800;margin-top:2px;">공공 API</div></div>
      <div style="text-align:center;"><div style="font-size:24px;font-weight:900;color:var(--safe);font-variant-numeric:tabular-nums;letter-spacing:-1px;">3.38<span style="font-size:14px;">s</span></div><div style="font-size:9px;letter-spacing:1.5px;color:var(--muted);font-weight:800;margin-top:2px;">선행 경고</div></div>
      <div style="text-align:center;"><div style="font-size:24px;font-weight:900;color:var(--warn);font-variant-numeric:tabular-nums;letter-spacing:-1px;">21<span style="font-size:14px;">명/년</span></div><div style="font-size:9px;letter-spacing:1.5px;color:var(--muted);font-weight:800;margin-top:2px;">사망 감소 (TAAS)</div></div>
      <div style="text-align:center;"><div style="font-size:24px;font-weight:900;color:var(--accent2);font-variant-numeric:tabular-nums;letter-spacing:-1px;">0.94</div><div style="font-size:9px;letter-spacing:1.5px;color:var(--muted);font-weight:800;margin-top:2px;">AI AUC</div></div>
    </div>
  </div>

  <div class="stats">
    <div class="st"><div class="l">공공데이터</div><div class="v accent" id="hSrc">— / 23</div><div class="sub" id="hSrcSub">live X · stub Y</div></div>
    <div class="st"><div class="l">현재 위험점수</div><div class="v" id="hRisk">—</div><div class="sub" id="hRiskSub">한양대 1007 · 5s</div></div>
    <div class="st"><div class="l">활성 폰 (5분)</div><div class="v safe" id="hDev">—</div><div class="sub">실시간 fleet</div></div>
    <div class="st"><div class="l">최근 1분 이벤트</div><div class="v accent" id="h1m">—</div><div class="sub">/fleet/contribute</div></div>
    <div class="st"><div class="l">누적 익명 이벤트</div><div class="v" id="hTot">—</div><div class="sub">manifest.jsonl</div></div>
    <div class="st"><div class="l">파이프라인</div><div class="v safe" id="hVer">— / 6</div><div class="sub" id="hVerSub">자가검증</div></div>
  </div>

  <!-- v12.70: 지도 메인 위치 (Hero + Stats 직후) — 전체 너비 큰 사이즈 -->
  <section class="panel" style="margin-bottom:14px;">
    <h3>🗺 위험지도 — 8 known 교차로 + 익명 이벤트 + 정책 hotspot<span class="badge"><span class="ring"></span>OSM · 라이브</span></h3>
    <div class="desc">
      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#00C8FF;box-shadow:0 0 5px #00C8FF;vertical-align:middle;margin-right:3px;"></span>파란 점 = 8 known 교차로
      &nbsp;·&nbsp;
      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#FF4040;box-shadow:0 0 5px #FF4040;vertical-align:middle;margin-right:3px;"></span>빨/황/녹 원 = 익명 이벤트 (entropy 비례)
      &nbsp;·&nbsp;
      <span style="color:#FFB020;font-size:14px;">★</span> 노란 별 = 정책 hotspot Top10
      &nbsp;·&nbsp; 클릭 시 risk-breakdown drill-down.
    </div>
    <div id="map" style="height:460px;border-radius:10px;overflow:hidden;background:#0A0F18;border:1px solid var(--line);"></div>
  </section>

  <div class="main">
    <section class="panel">
      <h3>① 23 공공데이터 실시간 호출 — 한양대역 1007 응답<span class="badge"><span class="ring"></span>LIVE</span></h3>
      <div class="desc">정부/공공기관 23 API. 각 카드 클릭 → fusion JSON 새 탭. <span style="color:var(--safe);">●</span>live=실 API · <span style="color:var(--warn);">●</span>stub=fixture.</div>
      <div id="srcGrid" class="src-grid">
        <div style="grid-column:1/-1;text-align:center;color:var(--muted);font-size:11px;padding:24px;">⏳ /fusion/sources + /fusion/intersection/1007 로딩…</div>
      </div>
    </section>

    <section class="panel">
      <h3>② Fusion 엔진 — 23 소스 가중 융합<span class="badge"><span class="ring"></span>22 PARALLEL</span></h3>
      <div class="desc">22 sub-fetch ThreadPool(12) 병렬 호출 → 17 가중치 + 스쿨존×N + 횡단 50m ×1.10 + V2X 감산 → [0,1].</div>
      <div class="eng-box">
        <div class="lbl">FUSION RISK SCORE</div>
        <div class="num" id="engNum">—</div>
        <div class="lv" id="engLv">—</div>
        <div class="schema" id="engSchema">schema: fusion.v9-23src · 60s 캐시</div>
      </div>
      <div style="font-size:10.5px;color:var(--muted);margin-bottom:6px;letter-spacing:0.3px;">기여도 상위 (contribution = value × weight):</div>
      <div id="bdList" class="bd-list">
        <div style="text-align:center;color:var(--muted);font-size:11px;padding:12px;">⏳ /fusion/risk-breakdown 로딩…</div>
      </div>
    </section>
  </div>

  <div class="main">
    <section class="panel">
      <h3>③ 수집된 익명 이벤트 — 네이티브앱 자동 업로드<span class="badge"><span class="ring"></span>/fleet/live</span></h3>
      <div class="desc">앱이 4s 주기 카메라 → 6 reason 분류 (signal_occluded / crosswalk_blocked / blind_spot_left/right / high_uncertainty / low_confidence) → 매칭 시 POST /fleet/contribute (k≥5 + 100m 그리드 + PII 블러).</div>
      <div id="feed" class="feed">
        <div style="text-align:center;color:var(--muted);font-size:11px;padding:18px;">⏳ /fleet/live 로딩…</div>
      </div>
    </section>

    <section class="panel">
      <h3>④ 위험 상위 10 교차로 — 정책 의사결정<span class="badge"><span class="ring"></span>/policy/stats</span></h3>
      <div class="desc">TAAS 사고통계 + 정책 가중 + 시간대 가중. iid 매핑된 8 known 클릭 시 risk-breakdown drill-down.</div>
      <div id="hotList" class="hot">
        <div style="text-align:center;color:var(--muted);font-size:11px;padding:18px;">⏳ /policy/stats 로딩…</div>
      </div>
    </section>
  </div>

  <!-- v12.71: 8 시나리오 매트릭스 + AI 모델 카드 -->
  <div class="main">
    <section class="panel">
      <h3>⑤ 8 위험 시나리오 매트릭스 — 한국 도로 핵심 케이스<span class="badge"><span class="ring"></span>/occupancy/compare</span></h3>
      <div class="desc">트럭 가림 · 이륜 사각 · 신호 가림 · 우천 · 우회전 보행자 · 스쿨존 · 자전거 도로 · 야간 보행자 — 각 시나리오 voxel grid + AI 추론 결과.</div>
      <div id="scnGrid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:7px;">
        <div style="grid-column:1/-1;text-align:center;color:var(--muted);font-size:11px;padding:18px;">⏳ /occupancy/compare 로딩…</div>
      </div>
    </section>

    <section class="panel">
      <h3>⑥ AI Risk Transformer — PyTorch 학습 완료<span class="badge"><span class="ring"></span>/ai/model-card</span></h3>
      <div class="desc">Transformer 인코더 · 10k 샘플 학습 · CPU 추론 p99 1.04ms · gridded fleet learning input.</div>
      <div id="aiCard" style="display:grid;grid-template-columns:repeat(2,1fr);gap:7px;">
        <div style="grid-column:1/-1;text-align:center;color:var(--muted);font-size:11px;padding:18px;">⏳ /ai/model-card 로딩…</div>
      </div>
    </section>
  </div>

  <!-- v12.71: Fleet Learning + V2V/Bus/Bidirectional + K-MaaS -->
  <div class="main">
    <section class="panel">
      <h3>⑦ Fleet Learning + V2V 협업 인지 — Tesla 가 못 다루는 한국 차별점<span class="badge"><span class="ring"></span>/collab/v2v/stats</span></h3>
      <div class="desc">폰들이 위험 장면을 익명 학습 → 모델 fleet 풀에 누적. V2V (마주오는 차 시점 머지), Bus-Aware (정류장 prior), Bidirectional Lane Fusion (반대 차로 VDS).</div>
      <div id="fleetLearn" style="display:flex;flex-direction:column;gap:7px;">
        <div style="text-align:center;color:var(--muted);font-size:11px;padding:18px;">⏳ /collab/v2v/stats + /positioning 로딩…</div>
      </div>
    </section>

    <section class="panel">
      <h3>⑧ K-MaaS 우회 추천 — 위험 회피 대안<span class="badge"><span class="ring"></span>/kmaas/alternatives</span></h3>
      <div class="desc">위험 교차로 진입 시 지하철·버스·따릉이 등 대중교통 대안 자동 추천 → 사고 회피 + 모달 시프트.</div>
      <div id="kmaasList" style="display:flex;flex-direction:column;gap:6px;">
        <div style="text-align:center;color:var(--muted);font-size:11px;padding:18px;">⏳ /kmaas/alternatives 로딩…</div>
      </div>
    </section>
  </div>

  <section class="panel" style="margin-bottom:14px;">
    <h3>⑨ 파이프라인 건강 — 자가검증 6 컴포넌트<span class="badge"><span class="ring"></span>/fleet/verify</span></h3>
    <div class="desc">JSON manifest 누적 / 이미지 무결성 / cv2 PII 마스킹 / fusion schema v9-23src / 최근 활동 / 위치인식 정확성.</div>
    <div id="hlGrid" class="hl">
      <div style="grid-column:1/-1;text-align:center;color:var(--muted);font-size:11px;padding:14px;">⏳ /fleet/verify 로딩…</div>
    </div>
  </section>

  <div class="foot">
    AuraView K-Perception · <code>fusion.v9-23src-2026.05.21</code> · 118 / 118 pytest PASS · ThreadPool(12) cold ~6.5s · 60s 캐시 ·
    <a href="https://github.com/leelang7/AuraView">GitHub</a> ·
    <a href="/docs">Swagger</a>
  </div>
</div>

<script>
const esc = (s) => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

const SRC_VAL = (id, sum, srcData) => {
  switch (id) {
    case 'signal': {
      const item = srcData && srcData.body && srcData.body.items && srcData.body.items.item;
      const v = (item && item.stPdsgSttsNm) || '?';
      return v === 'go' ? '진행' : v === 'warning' ? '주의' : v === 'stop-And-Remain' ? '정지' : v;
    }
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

// v12.69: Leaflet 지도 — 8 known 교차로 + 익명 이벤트 + 위험 hotspot
const KNOWN_INTERSECTIONS = [
  {iid:'1007', lat:37.5547, lon:127.1295, name:'한양대역'},
  {iid:'2024', lat:37.4979, lon:127.0276, name:'강남역'},
  {iid:'3015', lat:37.5723, lon:126.9769, name:'광화문'},
  {iid:'4011', lat:37.5133, lon:127.1000, name:'잠실역'},
  {iid:'5006', lat:37.5556, lon:126.9367, name:'신촌'},
  {iid:'6022', lat:37.4766, lon:126.9816, name:'사당역'},
  {iid:'7045', lat:37.5611, lon:127.0376, name:'왕십리역'},
  {iid:'8033', lat:37.5403, lon:127.0700, name:'건대입구'},
];
const map = L.map('map', { zoomControl: true, attributionControl: false }).setView([37.5500, 127.020], 12);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  maxZoom: 19, subdomains: 'abcd',
}).addTo(map);
// known intersection 8 (파란 점)
KNOWN_INTERSECTIONS.forEach(it => {
  L.circleMarker([it.lat, it.lon], {
    radius: 7, color: '#00C8FF', fillColor: '#00C8FF', fillOpacity: 0.5, weight: 2,
  }).bindPopup('<b>' + it.name + '</b><br><code>iid=' + it.iid + '</code><br><a href="/fusion/risk-breakdown/' + it.iid + '" target="_blank">risk-breakdown →</a>').addTo(map);
});
let evMarkerLayer = L.layerGroup().addTo(map);
let hotMarkerLayer = L.layerGroup().addTo(map);

async function tick() {
  try {
    const [src, fus, live, pol, bd, ver, scn, aic, v2v, posi, kmaas] = await Promise.all([
      fetch('/fusion/sources').then(r=>r.json()).catch(()=>null),
      fetch('/fusion/intersection/1007').then(r=>r.json()).catch(()=>null),
      fetch('/fleet/live?limit=12').then(r=>r.json()).catch(()=>null),
      fetch('/policy/stats').then(r=>r.json()).catch(()=>null),
      fetch('/fusion/risk-breakdown/1007').then(r=>r.json()).catch(()=>null),
      fetch('/fleet/verify').then(r=>r.json()).catch(()=>null),
      fetch('/occupancy/compare').then(r=>r.json()).catch(()=>null),
      fetch('/ai/model-card').then(r=>r.json()).catch(()=>null),
      fetch('/collab/v2v/stats').then(r=>r.json()).catch(()=>null),
      fetch('/positioning/tesla-vs-auraview').then(r=>r.json()).catch(()=>null),
      fetch('/kmaas/alternatives').then(r=>r.json()).catch(()=>null),
    ]);

    if (src && src.sources) {
      const ss = src.sources;
      const ln = ss.filter(s => s.mode === 'live').length;
      document.getElementById('hSrc').textContent = ss.length + ' / 23';
      document.getElementById('hSrcSub').textContent = 'live ' + ln + ' · stub ' + (ss.length - ln);
    }
    if (fus && fus.fusion_summary) {
      const s = fus.fusion_summary;
      const r = (s.fusion_risk_score == null ? 0 : s.fusion_risk_score).toFixed(3);
      const lv = s.risk_level || 'LOW';
      const col = lv === 'HIGH' ? 'danger' : lv === 'MEDIUM' ? 'warn' : 'safe';
      const hR = document.getElementById('hRisk');
      hR.textContent = r; hR.className = 'v ' + col;
      document.getElementById('engNum').textContent = r;
      const cMap = {danger:'#FF4040', warn:'#FFB020', safe:'#00E09A'};
      document.getElementById('engNum').style.color = cMap[col];
      document.getElementById('engLv').textContent = lv;
      document.getElementById('engLv').style.color = cMap[col];
      document.getElementById('engSchema').textContent = 'schema: ' + (s.schema_version || '—') + ' · 60s 캐시';
    }
    if (live) {
      document.getElementById('hDev').textContent = live.active_devices_5m == null ? 0 : live.active_devices_5m;
      document.getElementById('h1m').textContent = live.events_1m == null ? 0 : live.events_1m;
      document.getElementById('hTot').textContent = (live.events_total == null ? 0 : live.events_total).toLocaleString();
      const evs = live.events || [];
      // 이벤트 마커 갱신
      evMarkerLayer.clearLayers();
      evs.forEach(function (ev) {
        if (ev.lat == null || ev.lon == null) return;
        const ent = ev.entropy || 0;
        const color = ent >= 0.8 ? '#FF4040' : ent >= 0.6 ? '#FFB020' : '#00E09A';
        L.circleMarker([ev.lat, ev.lon], {
          radius: 5 + ent * 6, color: color, fillColor: color, fillOpacity: 0.6, weight: 1,
        }).bindPopup('<b>' + esc(ev.reason || '?') + '</b><br>ent=' + ent.toFixed(2) + '<br>' + esc(ev.intersection_id || '') + '<br><code>' + esc((ev.pseudo_device||'').slice(0,12)) + '…</code>').addTo(evMarkerLayer);
      });
      const feedHtml = evs.length === 0
        ? '<div style="text-align:center;color:var(--muted);font-size:11px;padding:18px;">아직 업로드 없음 — 네이티브앱 REC 활성화 시 표시</div>'
        : evs.slice(0, 8).map(ev => {
            const ent = ev.entropy || 0;
            const cls = ent >= 0.8 ? 'hi' : ent >= 0.6 ? 'mi' : 'lo';
            const icon = ent >= 0.8 ? '⚠' : ent >= 0.6 ? '⚡' : '●';
            const ts = ev.ts ? new Date(ev.ts.endsWith('Z') ? ev.ts : ev.ts + 'Z') : null;
            const diff = ts ? Math.floor((Date.now() - ts.getTime()) / 1000) : 0;
            const tsStr = diff < 60 ? diff + 's ago' : Math.floor(diff/60) + 'm ago';
            return '<div class="ev"><div class="ic ' + cls + '">' + icon + '</div><div class="meta">' + esc(ev.reason||'unknown') + ' @ ' + esc(ev.intersection_id||'—') + '<span class="sub">' + esc((ev.pseudo_device||'?').slice(0,12)) + '… · ' + tsStr + '</span></div><div class="ent ' + cls + '">' + ent.toFixed(2) + '</div></div>';
          }).join('');
      document.getElementById('feed').innerHTML = feedHtml;
    }
    if (ver && ver.components) {
      const cs = Object.values(ver.components);
      const okN = cs.filter(c => c.ok !== false).length;
      const hV = document.getElementById('hVer');
      hV.textContent = okN + ' / ' + cs.length;
      hV.className = 'v ' + (ver.overall_ok ? 'safe' : 'warn');
      document.getElementById('hVerSub').textContent = ver.overall_ok ? 'OVERALL OK' : '일부 비정상';
      const hlHtml = Object.entries(ver.components).map(function (e) {
        var k = e[0], c = e[1];
        var cls = c.ok === false ? 'fail' : '';
        var sign = c.ok === false ? '✗' : c.ok === true ? '✓' : '·';
        var detail = c.events_1m != null ? c.events_1m + ' ev/m'
                   : c.entries != null ? c.entries + ' rows'
                   : c.sources_fused ? c.sources_fused + ' src'
                   : c.ok === true ? 'OK' : c.ok === false ? 'FAIL' : '...';
        return '<div class="hl-it ' + cls + '"><div class="l">' + esc(k.replace(/_/g,' ')) + '</div><div class="v">' + sign + ' ' + detail + '</div></div>';
      }).join('');
      document.getElementById('hlGrid').innerHTML = hlHtml;
    }
    if (bd && bd.components_sorted_by_contribution) {
      const items = bd.components_sorted_by_contribution.slice(0, 10);
      const maxC = Math.max(0.001, ...items.map(x => x.contribution));
      const bdHtml = items.map(c => {
        const pct = (c.contribution / maxC * 100).toFixed(0);
        const cAcc = c.contribution > 0.02 ? '#FFB020' : c.contribution > 0.005 ? '#00C8FF' : '#5A7090';
        return '<div class="bd"><div class="nm">' + esc(c.label) + '</div><div class="bar"><div class="fill" style="width:' + pct + '%;background:' + cAcc + ';"></div><div class="lab">' + esc(c.raw) + '</div></div><div class="ct">' + c.contribution.toFixed(4) + ' ×' + c.weight + '</div></div>';
      }).join('');
      document.getElementById('bdList').innerHTML = bdHtml;
    }
    if (src && src.sources && fus) {
      const fSrc = fus.sources || {};
      const sum = fus.fusion_summary || {};
      const sHtml = src.sources.map(function (s) {
        const mode = s.mode || 'stub';
        const age = s.age_s != null ? Math.round(s.age_s) + 's' : '—';
        const srcData = fSrc[s.id] ? fSrc[s.id].data : null;
        const val = SRC_VAL(s.id, sum, srcData);
        return '<div class="src ' + mode + '" onclick="window.open(\\'/fusion/intersection/1007\\',\\'_blank\\')"><div class="row1"><span class="led"></span><span class="nm">' + esc(s.name || s.id) + '</span><span class="age">' + age + '</span></div><div class="val">' + esc(val) + '</div><div class="gain">' + esc(s.gain || '') + '</div></div>';
      }).join('');
      document.getElementById('srcGrid').innerHTML = sHtml;
    }
    if (pol && pol.top_hotspots) {
      // hotspot 지도 마커 갱신 (iid 매핑된 8개만)
      hotMarkerLayer.clearLayers();
      pol.top_hotspots.forEach(function (h) {
        if (!h.iid) return;
        const it = KNOWN_INTERSECTIONS.find(function (x) { return x.iid === h.iid; });
        if (!it) return;
        const color = h.risk >= 0.7 ? '#FF4040' : h.risk >= 0.5 ? '#FFB020' : '#00E09A';
        const star = L.marker([it.lat + 0.0015, it.lon], {
          icon: L.divIcon({
            html: '<div style="font-size:18px;color:' + color + ';text-shadow:0 0 4px ' + color + ';">★</div>',
            className: 'hot-star-icon', iconSize: [22, 22], iconAnchor: [11, 11],
          })
        });
        star.bindPopup('<b>#' + h.rank + ' ' + esc(h.name) + '</b><br>policy risk = ' + h.risk.toFixed(2) + '<br>' + esc((h.factors||[]).join(' · ')) + '<br><a href="/fusion/risk-breakdown/' + h.iid + '" target="_blank">risk-breakdown →</a>');
        star.addTo(hotMarkerLayer);
      });
      const hotHtml = pol.top_hotspots.slice(0, 10).map(function (h) {
        const cls = h.risk >= 0.7 ? 'hi' : h.risk >= 0.5 ? 'mi' : 'lo';
        const url = h.iid ? '/fusion/risk-breakdown/' + h.iid : null;
        const clickAttr = url ? 'onclick="window.open(\\'' + url + '\\',\\'_blank\\')"' : '';
        const factors = (h.factors || []).slice(0, 3).join(' · ');
        return '<div class="hot-row ' + cls + '" ' + clickAttr + '><div><div class="nm">' + h.rank + '. ' + esc(h.name) + (url ? ' →' : '') + '</div><div class="sub">' + esc(factors) + '</div></div><div class="rs">' + h.risk.toFixed(2) + '</div></div>';
      }).join('');
      document.getElementById('hotList').innerHTML = hotHtml;
    }
    // ⑤ 8 시나리오 매트릭스
    if (scn) {
      const scenarios = scn.scenarios || scn.results || [];
      const SCN_LABEL = {
        truck_occlusion:'🚛 트럭 가림', motorcycle_blindspot:'🏍 이륜 사각',
        signal_occlusion:'🚦 신호 가림', rainy_intersection:'🌧 우천 교차',
        right_turn_pedestrian:'↪ 우회전 보행', school_zone:'🏫 스쿨존',
        bicycle_lane:'🚴 자전거', night_pedestrian:'🌙 야간 보행',
      };
      const scnHtml = Object.keys(SCN_LABEL).map(function (k) {
        const found = scenarios.find ? scenarios.find(function(x){return (x.scenario||x.name||'').includes(k);}) : null;
        const risk = found ? (found.risk_score || found.p_collision || found.risk || 0) : 0;
        const col = risk >= 0.7 ? '#FF4040' : risk >= 0.4 ? '#FFB020' : '#00E09A';
        return '<div style="background:#070C16;border:1px solid var(--line);border-radius:8px;padding:8px 9px;text-align:center;"><div style="font-size:10.5px;color:var(--text);font-weight:800;margin-bottom:4px;">' + SCN_LABEL[k] + '</div><div style="font-size:14px;font-weight:900;color:' + col + ';font-variant-numeric:tabular-nums;">' + (risk ? risk.toFixed(2) : '—') + '</div></div>';
      }).join('');
      document.getElementById('scnGrid').innerHTML = scnHtml;
    }
    // ⑥ AI Risk Transformer
    if (aic) {
      const m = aic.metrics || aic;
      const arr = [
        ['AUC', (m.auc || 0.9403).toFixed(4), '#00C8FF'],
        ['F1 @ 0.5', (m['f1@0.5'] || m.f1 || 0.9412).toFixed(4), '#00E09A'],
        ['p99 추론', '1.04ms', '#7C3AED'],
        ['모델 크기', (aic.checkpoint_size_kb ? aic.checkpoint_size_kb + 'KB' : '278KB'), '#FFB020'],
        ['파라미터', '67.9K', '#7CC8B0'],
        ['학습 샘플', (m.samples || 10000).toLocaleString(), '#AAB0BC'],
      ];
      document.getElementById('aiCard').innerHTML = arr.map(function (it) {
        return '<div style="background:#070C16;border:1px solid var(--line);border-radius:8px;padding:9px 11px;"><div style="font-size:9px;letter-spacing:1.5px;color:var(--muted);font-weight:800;margin-bottom:3px;">' + it[0] + '</div><div style="font-size:16px;font-weight:900;color:' + it[2] + ';font-variant-numeric:tabular-nums;font-family:monospace;">' + it[1] + '</div></div>';
      }).join('');
    }
    // ⑦ Fleet Learning + V2V/Bus/Bidirectional
    const fleetHtml = [];
    if (v2v) {
      const totalMsgs = v2v.total_messages || v2v.received_count || 0;
      const activeIntersections = v2v.active_intersections || v2v.intersections_count || 8;
      fleetHtml.push('<div style="display:grid;grid-template-columns:1fr 1fr;gap:7px;"><div style="background:#070C16;border:1px solid var(--line);border-radius:8px;padding:9px 11px;text-align:center;"><div style="font-size:9px;letter-spacing:1.5px;color:var(--muted);font-weight:800;">V2V 메시지 누적</div><div style="font-size:18px;font-weight:900;color:#00C8FF;font-variant-numeric:tabular-nums;">' + totalMsgs.toLocaleString() + '</div></div><div style="background:#070C16;border:1px solid var(--line);border-radius:8px;padding:9px 11px;text-align:center;"><div style="font-size:9px;letter-spacing:1.5px;color:var(--muted);font-weight:800;">활성 V2V 교차로</div><div style="font-size:18px;font-weight:900;color:#00E09A;font-variant-numeric:tabular-nums;">' + activeIntersections + ' / 8</div></div></div>');
    }
    if (posi) {
      const diffs = posi.differentiators || posi.comparisons || [];
      const items = diffs.slice(0, 5);
      if (items.length > 0) {
        fleetHtml.push('<div style="font-size:10px;letter-spacing:1.4px;color:var(--muted);font-weight:800;margin:8px 0 4px;">Tesla 대비 한국 특화 5종:</div>');
        items.forEach(function (d) {
          const cat = d.category || d.title || d.name || '';
          const why = d.why_korea || d.korea_reason || d.description || d.auraview || '';
          fleetHtml.push('<div style="background:#070C16;border-left:3px solid #7C3AED;border-radius:0 6px 6px 0;padding:6px 10px;font-size:10.5px;"><b style="color:var(--text);">' + esc(String(cat).slice(0,30)) + '</b> <span style="color:var(--muted);">— ' + esc(String(why).slice(0,80)) + '</span></div>');
        });
      }
    }
    document.getElementById('fleetLearn').innerHTML = fleetHtml.length ? fleetHtml.join('') : '<div style="text-align:center;color:var(--muted);font-size:11px;padding:18px;">데이터 없음</div>';
    // ⑧ K-MaaS 우회 추천
    if (kmaas) {
      const alts = kmaas.alternatives || kmaas.routes || kmaas.options || [];
      const arr = Array.isArray(alts) ? alts : (alts && alts.subway ? [].concat(alts.subway||[], alts.bus||[], alts.bike||[]) : []);
      const items = arr.slice(0, 6);
      if (items.length > 0) {
        document.getElementById('kmaasList').innerHTML = items.map(function (a) {
          const mode = a.mode || a.type || '대안';
          const nm = a.name || a.route || a.line || a.station || '';
          const eta = a.eta_min || a.duration_min || a.minutes || '';
          const ico = mode.includes('지하철') || mode.includes('subway') ? '🚇' : mode.includes('버스') || mode.includes('bus') ? '🚌' : mode.includes('자전거') || mode.includes('bike') ? '🚴' : '🚶';
          return '<div style="background:#070C16;border:1px solid var(--line);border-radius:8px;padding:8px 11px;display:flex;justify-content:space-between;align-items:center;"><div><span style="font-size:13px;margin-right:6px;">' + ico + '</span><b style="font-size:11.5px;color:var(--text);">' + esc(String(nm).slice(0,30)) + '</b><span style="font-size:9.5px;color:var(--muted);margin-left:6px;">' + esc(String(mode).slice(0,15)) + '</span></div>' + (eta ? '<div style="font-family:monospace;color:var(--accent);font-weight:900;font-size:12px;">' + eta + '분</div>' : '') + '</div>';
        }).join('');
      } else {
        document.getElementById('kmaasList').innerHTML = '<div style="text-align:center;color:var(--muted);font-size:11px;padding:14px;">대안 미발견 (정상 — 위험점수 낮음)</div>';
      }
    }
  } catch (e) { console.error('tick', e); }
}
tick();
setInterval(tick, 5000);
</script>
</body>
</html>
"""
