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
app.include_router(competition.router, prefix="/competition", tags=["competition-system"])
if _SCENARIO_OK:
    app.include_router(scenario.router, prefix="/scenario", tags=["scenario"])
if _SHOWREEL_OK:
    app.include_router(showreel.router, prefix="/showreel", tags=["showreel"])


# RAG 인덱스 자동 복구 — 재시작 후 chunks.jsonl + embeddings.npy 디스크에서 복원
@app.on_event("startup")
def _osm_prewarm():
    """v12.111: cold-start 후 첫 사용자 요청 전에 OSM 캐시 pre-warm.
    8 known 교차로 + Seoul 시청 좌표로 5개 OSM helper 호출 → 캐시 hot 상태로 시작.
    백그라운드 스레드로 비동기 실행 (startup 속도 영향 X)."""
    import logging as _log, threading
    log = _log.getLogger("auraview.osm_prewarm")
    KI = [
        (37.5547, 127.1295),  # 1007 한양대역
        (37.4979, 127.0276),  # 2024 강남역
        (37.5723, 126.9769),  # 3015 광화문
        (37.5133, 127.1000),  # 4011 잠실역
        (37.5556, 126.9367),  # 5006 신촌
        (37.4766, 126.9816),  # 6022 사당역
        (37.5611, 127.0376),  # 7045 왕십리역
        (37.5403, 127.0700),  # 8033 건대입구
        (37.5665, 126.9780),  # Seoul 시청 (fusion 기본)
    ]

    def _warm():
        try:
            from .services import public_api as _pa
            warmed = 0
            for lat, lon in KI:
                for fn in [
                    lambda: _pa._fetch_osm_crosswalks(lat, lon, 300.0),
                    lambda: _pa._fetch_osm_hospitals(lat, lon, 3000.0),
                    lambda: _pa._fetch_osm_schools(lat, lon, 500.0),
                    lambda: _pa._fetch_osm_ev_chargers(lat, lon, 2000.0),
                    lambda: _pa._fetch_osm_speed_cameras(lat, lon, 800.0),
                ]:
                    try: fn(); warmed += 1
                    except Exception: pass
            log.info("osm_prewarm: warmed %d/%d helpers across %d intersections",
                     warmed, len(KI)*5, len(KI))
        except Exception as exc:
            log.warning("osm_prewarm failed: %s", exc)

    # 백그라운드로 (startup 차단 X)
    threading.Thread(target=_warm, daemon=True, name="osm-prewarm").start()


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
_mount_static(app, ["static", "scorecard"], "/scorecard")  # v7 2026-05-18: 검증 25점 항목 적격 증거표 (judge-facing)
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
    """v12.75: Tesla Fleet View 식 — 지도 메인 75vh + 좌상단 라운드 로빈 floating card + 우하단 LIVE stream.

    분석 결과 적용:
    - 지도 무조건 메인 (사용자 요구)
    - 라운드 로빈 (kiosk 식 자동 전환, 5s)
    - Tesla 미니멀 톤 (다크 + cyan 1색 + uppercase tracking + thin 큰 숫자)
    - 9탭 / 23 카탈로그 / hotspot 표는 별도 페이지 (이미 분리)
    """
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>AURAVIEW · FLEET LIVE</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%;background:#04070D;color:#fff;overflow:hidden;
  font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;
  -webkit-font-smoothing:antialiased;}

/* ─── Sticky nav (Tesla pill) ─── */
.nv{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:200;
  display:flex;gap:8px;align-items:center;
  padding:9px 18px;background:rgba(8,12,20,0.78);backdrop-filter:blur(18px);
  border:1px solid rgba(255,255,255,0.08);border-radius:99px;
  font-family:-apple-system,sans-serif;font-size:12px;font-weight:800;letter-spacing:1.2px;}
.nv .br{display:flex;align-items:center;gap:8px;color:#fff;}
.nv .br .ic{width:18px;height:18px;border-radius:5px;background:linear-gradient(135deg,#00C8FF,#7C3AED);position:relative;overflow:hidden;}
.nv .br .ic::after{content:'';position:absolute;inset:5px;border-radius:50%;background:#04070D;}
.nv .br .ic::before{content:'';position:absolute;left:7px;top:7px;width:4px;height:4px;border-radius:50%;background:#00C8FF;box-shadow:0 0 4px #00C8FF;}
.nv .sep{width:1px;height:14px;background:rgba(255,255,255,0.15);margin:0 4px;}
.nv .live{display:flex;align-items:center;gap:5px;color:#00E09A;}
.nv .live .pulse{width:6px;height:6px;border-radius:50%;background:#00E09A;box-shadow:0 0 6px #00E09A;animation:pls 1.4s infinite;}
@keyframes pls{0%,100%{opacity:1;}50%{opacity:0.35;}}
.nv .rd{display:flex;align-items:center;gap:6px;font-family:'JetBrains Mono','SF Mono',monospace;font-size:10px;font-weight:900;letter-spacing:0.8px;}
.nv .rd .rdLv{color:#00C8FF;}
.nv .rd .rdVf{color:#00E09A;}
.nv .rd .rdDiv{width:1px;height:10px;background:rgba(255,255,255,0.20);}
.nv a{color:rgba(255,255,255,0.6);text-decoration:none;padding:3px 8px;border-radius:99px;transition:color 0.15s;}
.nv a:hover{color:#00C8FF;}

/* ─── Full-screen map ─── */
#map{position:fixed;inset:0;z-index:1;}
.leaflet-control-attribution{display:none!important;}
/* 줌 컨트롤 → 라운드로빈 카드와 충돌 회피: 좌상단(기본)에서 우하단으로 이동 */
.leaflet-control-zoom{display:none!important;}

/* ─── Top-left round-robin floating card ─── */
.rr{position:fixed;top:78px;left:18px;z-index:100;
  width:340px;min-height:180px;
  background:rgba(8,12,20,0.78);backdrop-filter:blur(20px);
  border:1px solid rgba(255,255,255,0.08);border-radius:18px;
  padding:18px 22px;box-shadow:0 12px 40px rgba(0,0,0,0.65);
  overflow:hidden;}
.rr .head{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;}
.rr .head .eye{font-family:'JetBrains Mono','SF Mono',monospace;font-size:9px;letter-spacing:2.4px;color:#00C8FF;font-weight:900;}
.rr .head .dots{display:flex;gap:5px;}
.rr .head .dots .d{width:5px;height:5px;border-radius:50%;background:rgba(255,255,255,0.18);transition:all 0.3s;}
.rr .head .dots .d.on{background:#00C8FF;width:16px;border-radius:99px;box-shadow:0 0 6px rgba(0,200,255,0.7);}
.rr .slide{display:none;}
.rr .slide.on{display:block;animation:fdIn 0.5s ease-out;}
@keyframes fdIn{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
.rr .ttl{font-size:11px;letter-spacing:1.4px;color:rgba(255,255,255,0.55);font-weight:700;text-transform:uppercase;margin-bottom:6px;}
.rr .big{font-size:54px;font-weight:200;color:#fff;letter-spacing:-2.5px;line-height:1;font-variant-numeric:tabular-nums;}
.rr .big sub{font-size:14px;font-weight:600;color:rgba(255,255,255,0.45);letter-spacing:0;vertical-align:baseline;margin-left:4px;}
.rr .sub{font-size:11px;color:rgba(255,255,255,0.50);margin-top:8px;letter-spacing:0.3px;}

/* round-robin grid variant (3 KPI in one slide) */
.rr .kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:4px;}
.rr .kpis .k .v{font-size:30px;font-weight:200;color:#fff;letter-spacing:-1.2px;line-height:1;font-variant-numeric:tabular-nums;}
.rr .kpis .k .v.safe{color:#00E09A;}.rr .kpis .k .v.warn{color:#FFB020;}.rr .kpis .k .v.acc{color:#00C8FF;}
.rr .kpis .k .l{font-size:9px;letter-spacing:1.5px;color:rgba(255,255,255,0.45);font-weight:700;text-transform:uppercase;margin-top:4px;}

/* hotspot list */
.rr .hl{display:flex;flex-direction:column;gap:5px;}
.rr .hl .ho{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05);}
.rr .hl .ho:last-child{border-bottom:none;}
.rr .hl .ho .rk{font-size:10px;color:rgba(255,255,255,0.4);font-family:monospace;}
.rr .hl .ho .nm{font-size:11.5px;color:#fff;font-weight:700;}
.rr .hl .ho .rs{font-family:monospace;font-size:13px;font-weight:900;font-variant-numeric:tabular-nums;}

/* 8 scenarios grid (4×2) */
.rr .sg{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:4px;}
.rr .sg .sc{background:rgba(0,200,255,0.07);border:1px solid rgba(0,200,255,0.20);border-radius:6px;padding:5px 4px;text-align:center;transition:all 0.3s;}
.rr .sg .sc.hi{background:rgba(255,68,68,0.10);border-color:rgba(255,68,68,0.35);}
.rr .sg .sc.mi{background:rgba(255,176,32,0.10);border-color:rgba(255,176,32,0.35);}
.rr .sg .sc .ic{font-size:14px;line-height:1;}
.rr .sg .sc .nm{font-size:8px;letter-spacing:0.4px;color:rgba(255,255,255,0.7);font-weight:700;margin-top:3px;text-transform:uppercase;}
.rr .sg .sc .dl{font-family:monospace;font-size:9.5px;font-weight:900;color:#00E09A;margin-top:2px;}
.rr .sg .sc.hi .dl{color:#FF4040;}.rr .sg .sc.mi .dl{color:#FFB020;}

/* ─── Bottom-right LIVE STREAM ─── */
.ls{position:fixed;bottom:18px;right:18px;z-index:100;
  width:340px;max-height:42vh;
  background:rgba(8,12,20,0.78);backdrop-filter:blur(20px);
  border:1px solid rgba(255,255,255,0.08);border-radius:18px;
  padding:14px 16px;box-shadow:0 12px 40px rgba(0,0,0,0.65);
  display:flex;flex-direction:column;overflow:hidden;}
.ls .head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;}
.ls .head .eye{font-family:'JetBrains Mono','SF Mono',monospace;font-size:9px;letter-spacing:2.4px;color:#00C8FF;font-weight:900;}
.ls .head .ct{font-family:'JetBrains Mono',monospace;font-size:10px;color:rgba(255,255,255,0.55);font-weight:700;}
.ls .body{flex:1;overflow-y:auto;}
.ls .body::-webkit-scrollbar{width:3px;}
.ls .body::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.15);border-radius:99px;}
.ls .ev{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.05);}
.ls .ev:last-child{border-bottom:none;}
.ls .ev .ic{width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;}
.ls .ev .ic.hi{background:rgba(255,68,68,0.20);color:#FF4040;}
.ls .ev .ic.mi{background:rgba(255,176,32,0.20);color:#FFB020;}
.ls .ev .ic.lo{background:rgba(0,224,154,0.18);color:#00E09A;}
.ls .ev .meta{font-size:10.5px;color:#fff;font-weight:700;}
.ls .ev .meta .sub{display:block;font-size:9px;color:rgba(255,255,255,0.45);font-family:monospace;font-weight:500;margin-top:1px;}
.ls .ev .ent{font-family:monospace;font-size:11px;font-weight:900;}
.ls .ev .ent.hi{color:#FF4040;}.ls .ev .ent.mi{color:#FFB020;}.ls .ev .ent.lo{color:#00E09A;}
.ls .empty{text-align:center;color:rgba(255,255,255,0.4);font-size:11px;padding:24px 0;}
.ls .liveBadge{display:flex;align-items:center;gap:6px;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:900;letter-spacing:1.1px;color:#00E09A;background:rgba(0,224,154,0.10);border:1px solid rgba(0,224,154,0.30);border-radius:99px;padding:5px 10px;margin-bottom:8px;width:fit-content;}
.ls .liveBadge .pulseDot{width:6px;height:6px;border-radius:50%;background:#00E09A;box-shadow:0 0 6px #00E09A;animation:lvPulse 1.4s ease-in-out infinite;}
@keyframes lvPulse{0%,100%{opacity:0.4;}50%{opacity:1;}}

/* ─── Hero strip 가운데 상단 (큰 메시지) ─── */
.hr{position:fixed;top:68px;left:50%;transform:translateX(-50%);z-index:90;
  padding:8px 22px;background:rgba(8,12,20,0.65);backdrop-filter:blur(14px);
  border:1px solid rgba(255,255,255,0.06);border-radius:99px;
  font-family:'JetBrains Mono','SF Mono',monospace;font-size:11px;font-weight:800;letter-spacing:1.4px;
  color:#fff;display:flex;gap:18px;align-items:center;}
.hr .num{font-size:14px;font-variant-numeric:tabular-nums;}
.hr .num.safe{color:#00E09A;}.hr .num.warn{color:#FFB020;}.hr .num.acc{color:#00C8FF;}
.hr .lab{color:rgba(255,255,255,0.5);font-weight:700;}
.hr .sep{width:1px;height:12px;background:rgba(255,255,255,0.15);}

@media (max-width:900px){
  /* 모바일/Z Fold: 라운드로빈은 상단 1/3, LIVE 스트림은 하단 1/3 — 가운데 1/3는 지도 노출 */
  .rr{width:calc(100% - 24px);left:12px;right:12px;top:62px;padding:12px 14px;min-height:140px;max-height:32vh;overflow-y:auto;}
  .rr .big{font-size:42px;}
  .ls{width:calc(100% - 24px);left:12px;right:12px;bottom:12px;max-height:34vh;}
  .hr{display:none;}
  .nv{font-size:11px;padding:7px 14px;gap:5px;top:10px;}
  .nv a{padding:2px 6px;}
}
</style>
</head>
<body>

<!-- NAV -->
<div class="nv">
  <div class="br"><span class="ic"></span><span>AURAVIEW</span></div>
  <span class="sep"></span>
  <div class="live"><span class="pulse"></span>LIVE</div>
  <span class="sep"></span>
  <!-- v12.94: readiness 뱃지 — 라이브 소스 + 검증률 한눈에 -->
  <div class="rd" id="rdBadge" title="라이브 외부 데이터 소스 / 위치 검증 통과 비율">
    <span class="rdLv">SRC <span id="rdLive">—</span>/23</span>
    <span class="rdDiv"></span>
    <span class="rdVf">VRF <span id="rdVf">—</span>%</span>
  </div>
  <span class="sep"></span>
  <a href="/story/">STORY</a>
  <a href="/demos">DEMOS</a>
  <a href="/policy/">POLICY</a>
  <a href="/scorecard/">SCORECARD</a>
  <a href="/bev3d/">BEV3D</a>
  <a href="/metrics/audit" target="_blank" title="라이브 시스템 헬스 + 25점 항목 + 데이터 신뢰성 (단일 GET)">AUDIT</a>
  <span class="sep"></span>
  <a id="navGit" href="https://github.com/leelang7/AuraView" target="_blank" title="현재 배포된 git commit (자동 갱신)" style="font-family:monospace;font-size:10px;color:rgba(255,255,255,0.45);">git —</a>
</div>

<!-- Hero pill 가운데 상단 (간결한 메시지) -->
<div class="hr">
  <span><span class="num acc" id="hrAct">—</span> <span class="lab">ACTIVE</span></span>
  <span class="sep"></span>
  <span><span class="num" id="hrEv">—</span> <span class="lab">EV/MIN</span></span>
  <span class="sep"></span>
  <span><span class="num safe" id="hrTot">—</span> <span class="lab">SAVED</span></span>
  <span class="sep"></span>
  <span><span class="num" id="hrRisk">—</span> <span class="lab" id="hrRiskLv">RISK</span></span>
</div>

<!-- Map (full-screen) -->
<div id="map"></div>

<!-- ROUND-ROBIN floating card (top-left) -->
<div class="rr">
  <div class="head">
    <div class="eye" id="rrEye">// SLIDE 1 / 4</div>
    <div class="dots">
      <span class="d on"></span><span class="d"></span><span class="d"></span><span class="d"></span>
    </div>
  </div>
  <!-- Slide 1: Big risk score -->
  <div class="slide on" data-i="0">
    <div class="ttl">FUSION RISK · 한양대 1007</div>
    <div class="big"><span id="s1Risk">—</span><sub id="s1Lv"></sub></div>
    <div class="sub" id="s1Schema">schema: fusion.v9-23src · 5s 폴링</div>
  </div>
  <!-- Slide 2: 4 KPI 그리드 -->
  <div class="slide" data-i="1">
    <div class="ttl">FLEET 운영 KPI</div>
    <div class="kpis">
      <div class="k"><div class="v acc" id="s2Act">—</div><div class="l">ACTIVE / 5MIN</div></div>
      <div class="k"><div class="v safe" id="s2Ev">—</div><div class="l">EVENTS / MIN</div></div>
      <div class="k"><div class="v warn" id="s2Tot">—</div><div class="l">CUMULATIVE</div></div>
      <div class="k"><div class="v" id="s2Pyt">118</div><div class="l">PYTEST / 118</div></div>
    </div>
  </div>
  <!-- Slide 3: Hotspot top 5 -->
  <div class="slide" data-i="2">
    <div class="ttl">위험 HOTSPOT TOP 5</div>
    <div class="hl" id="s4List">
      <div style="color:rgba(255,255,255,0.4);font-size:11px;text-align:center;padding:14px 0;">⏳ 로딩</div>
    </div>
  </div>
  <!-- Slide 4: 8 시나리오 (occupancy/compare) -->
  <div class="slide" data-i="3">
    <div class="ttl">8 시나리오 K-인지</div>
    <div class="sg" id="s6Grid">
      <div style="grid-column:1/-1;color:rgba(255,255,255,0.4);font-size:11px;text-align:center;padding:14px 0;">⏳ 로딩</div>
    </div>
    <div class="sub" id="s6Sub" style="margin-top:6px;">truck/bike/signal/rain/RT/school/lane/night</div>
  </div>
</div>

<!-- LIVE STREAM (bottom-right) -->
<div class="ls">
  <div class="head">
    <div class="eye">// LIVE STREAM</div>
    <div class="ct" id="lsCt">— events</div>
  </div>
  <div class="liveBadge" id="liveBadge" title="실시간 공공데이터 소스 수 (no-key fallback 포함)">
    <span class="pulseDot"></span><span id="liveN">—</span> LIVE / 23 SRC
  </div>
  <div class="body" id="lsBody">
    <div class="empty">⏳ /fleet/live 로딩…</div>
  </div>
</div>

<script>
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
// Map init (Tesla dark) — 줌 컨트롤은 우하단으로 이동 (라운드로빈 카드와 충돌 회피)
const map = L.map('map', { zoomControl: false, attributionControl: false }).setView([37.5500, 127.020], 12);
L.control.zoom({ position: 'bottomright' }).addTo(map);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 19, subdomains: 'abcd' }).addTo(map);
// KI 기본 마커 → iid별 layer로 보관 (hotspot top-5에 들면 숨김으로 ★와 중복 방지)
const kiMarkers = {};
KI.forEach(it => {
  const m = L.circleMarker([it.lat, it.lon], {
    radius: 8, color: '#00C8FF', fillColor: '#00C8FF', fillOpacity: 0.4, weight: 2,
  }).bindPopup('<b>' + it.name + '</b><br><code>iid=' + it.iid + '</code><br><a href="/fusion/risk-breakdown/' + it.iid + '" target="_blank">risk-breakdown →</a>').addTo(map);
  kiMarkers[it.iid] = m;
});
const evL = L.layerGroup().addTo(map);
const hotL = L.layerGroup().addTo(map);

// Round-robin slide rotation
let curSlide = 0;
const slideCount = 4;
function rotateSlide() {
  curSlide = (curSlide + 1) % slideCount;
  document.querySelectorAll('.rr .slide').forEach(el => el.classList.toggle('on', parseInt(el.dataset.i) === curSlide));
  document.querySelectorAll('.rr .dots .d').forEach((el, i) => el.classList.toggle('on', i === curSlide));
  document.getElementById('rrEye').textContent = '// SLIDE ' + (curSlide + 1) + ' / ' + slideCount;
}
setInterval(rotateSlide, 5000);

async function tick() {
  try {
    const [src, fus, live, pol, occ, aud] = await Promise.all([
      fetch('/fusion/sources').then(r=>r.json()).catch(()=>null),
      fetch('/fusion/intersection/1007').then(r=>r.json()).catch(()=>null),
      fetch('/fleet/live?limit=20').then(r=>r.json()).catch(()=>null),
      fetch('/policy/stats').then(r=>r.json()).catch(()=>null),
      fetch('/occupancy/compare').then(r=>r.json()).catch(()=>null),
      fetch('/metrics/audit').then(r=>r.json()).catch(()=>null),
    ]);
    // v12.112: git_sha 표시 (NAV 끝)
    if (aud && aud.git_sha) {
      const g = document.getElementById('navGit');
      if (g) {
        const sha = aud.git_sha.slice(0,7);
        g.textContent = 'git ' + sha;
        g.href = 'https://github.com/leelang7/AuraView/commit/' + aud.git_sha;
        g.title = '현재 배포 commit: ' + aud.git_sha + ' · tests ' + (aud.system?.tests_passing || '—');
      }
    }
    // Hero pill
    if (live) {
      document.getElementById('hrAct').textContent = live.active_devices_5m || 0;
      document.getElementById('hrEv').textContent = live.events_1m || 0;
      document.getElementById('hrTot').textContent = (live.events_total || 0).toLocaleString();
      document.getElementById('lsCt').textContent = (live.events_total || 0) + ' events · 5min ' + (live.active_devices_5m || 0) + ' dev';
    }
    if (fus && fus.fusion_summary) {
      const s = fus.fusion_summary;
      const r = (s.fusion_risk_score || 0).toFixed(3);
      const lv = s.risk_level || 'LOW';
      const col = lv==='HIGH'?'#FF4040':lv==='MEDIUM'?'#FFB020':'#00E09A';
      document.getElementById('hrRisk').textContent = r;
      document.getElementById('hrRisk').style.color = col;
      document.getElementById('hrRiskLv').textContent = lv;
      document.getElementById('s1Risk').textContent = r;
      document.getElementById('s1Risk').style.color = col;
      document.getElementById('s1Lv').textContent = lv;
      document.getElementById('s1Lv').style.color = col;
      document.getElementById('s1Schema').textContent = 'schema: ' + (s.schema_version || '—') + ' · 60s 캐시';
    }
    // Slide 2: KPI
    if (live) {
      document.getElementById('s2Act').textContent = live.active_devices_5m || 0;
      document.getElementById('s2Ev').textContent = live.events_1m || 0;
      document.getElementById('s2Tot').textContent = (live.events_total || 0).toLocaleString();
    }
    // LIVE 뱃지 (23 SRC 슬라이드 제거 — 뱃지가 그 역할)
    if (src && src.sources) {
      const ss = src.sources;
      const ln = ss.filter(s => s.mode === 'live').length;
      const liveN = document.getElementById('liveN');
      if (liveN) {
        liveN.textContent = ln;
        const badge = document.getElementById('liveBadge');
        if (badge) badge.title = '실시간 ' + ln + '개: ' + ss.filter(s=>s.mode==='live').map(s=>s.id).join(', ');
      }
      // v12.94: NAV readiness 뱃지 — SRC N/23
      const rdLive = document.getElementById('rdLive');
      if (rdLive) rdLive.textContent = ln;
    }
    // v12.94: NAV readiness 뱃지 — VRF % (검증된 이벤트 비율)
    if (live && live.events_verified_pct != null) {
      const rdVf = document.getElementById('rdVf');
      if (rdVf) {
        const pct = live.events_verified_pct;
        rdVf.textContent = pct.toFixed(0);
        // 색상: ≥60% safe, ≥30% warn, <30% danger
        rdVf.style.color = pct >= 60 ? '#00E09A' : pct >= 30 ? '#FFB020' : '#FF4040';
      }
    }
    // Slide 4: Hotspot top 5
    if (pol && pol.top_hotspots) {
      const html = pol.top_hotspots.slice(0, 5).map(h => {
        const col = h.risk >= 0.7 ? '#FF4040' : h.risk >= 0.5 ? '#FFB020' : '#00E09A';
        const url = h.iid ? '/fusion/risk-breakdown/' + h.iid : null;
        return '<div class="ho"' + (url ? ' style="cursor:pointer;" onclick="window.open(\\''+url+'\\',\\'_blank\\')"' : '') + '><div class="rk">#' + h.rank + '</div><div class="nm">' + esc(h.name) + '</div><div class="rs" style="color:' + col + ';">' + h.risk.toFixed(2) + '</div></div>';
      }).join('');
      document.getElementById('s4List').innerHTML = html;
      // 지도 hotspot 마커 — top-5에 포함된 iid의 KI 기본 ● 마커는 숨김 (★와 중복 방지)
      hotL.clearLayers();
      const topIids = new Set(pol.top_hotspots.slice(0,5).map(h=>h.iid).filter(Boolean));
      Object.entries(kiMarkers).forEach(([iid, m]) => {
        if (topIids.has(iid)) { if (map.hasLayer(m)) map.removeLayer(m); }
        else { if (!map.hasLayer(m)) m.addTo(map); }
      });
      pol.top_hotspots.slice(0,5).forEach(h => {
        if (!h.iid) return;
        const it = KI.find(x => x.iid === h.iid);
        if (!it) return;
        const c = h.risk >= 0.7 ? '#FF4040' : h.risk >= 0.5 ? '#FFB020' : '#00E09A';
        L.marker([it.lat, it.lon], {
          icon: L.divIcon({ html: '<div style="font-size:22px;color:' + c + ';text-shadow:0 0 8px ' + c + ';line-height:1;">★</div>', className: '', iconSize: [22, 22], iconAnchor: [11, 11] })
        }).bindPopup('<b>#' + h.rank + ' ' + esc(h.name) + '</b><br>risk=' + h.risk.toFixed(2) + '<br><code>iid=' + h.iid + '</code><br><a href="/fusion/risk-breakdown/' + h.iid + '" target="_blank">risk-breakdown →</a>').addTo(hotL);
      });
    }
    // Slide 4: 8 시나리오 (truck/bike/signal/rain/RT/school/lane/night)
    if (occ && occ.scenarios) {
      const ICN = {
        truck_occlusion:'🚛', motorcycle_blindspot:'🏍', signal_occlusion:'🚦',
        rainy_intersection:'🌧', right_turn_pedestrian:'↳', school_zone:'🏫',
        bicycle_lane:'🚲', night_pedestrian:'🌙'
      };
      const SHORT = {
        truck_occlusion:'TRUCK', motorcycle_blindspot:'BIKE', signal_occlusion:'SIGNAL',
        rainy_intersection:'RAIN', right_turn_pedestrian:'RT-PED', school_zone:'SCHOOL',
        bicycle_lane:'LANE', night_pedestrian:'NIGHT'
      };
      const html = occ.scenarios.map(s => {
        const p = s.p_collision || 0;
        const lt = s.lead_time_s != null ? s.lead_time_s.toFixed(1) + 's' : '—';
        const cls = p >= 0.7 ? 'hi' : p >= 0.4 ? 'mi' : '';
        const ic = ICN[s.id] || '●';
        const nm = SHORT[s.id] || s.id.slice(0, 6).toUpperCase();
        return '<div class="sc ' + cls + '" title="' + esc(s.title || s.id) + ' · p=' + p.toFixed(2) + ' · lead=' + lt + '" onclick="window.open(\\''+s.demo_url+'\\',\\'_blank\\')" style="cursor:pointer;"><div class="ic">' + ic + '</div><div class="nm">' + nm + '</div><div class="dl">+' + lt + '</div></div>';
      }).join('');
      document.getElementById('s6Grid').innerHTML = html;
      const avgP = occ.scenarios.reduce((a, s) => a + (s.p_collision || 0), 0) / occ.scenarios.length;
      document.getElementById('s6Sub').textContent = occ.count + '개 시나리오 · 평균 p_collision=' + avgP.toFixed(2);
    }
    // LIVE STREAM
    if (live) {
      const evs = live.events || [];
      const html = evs.length === 0
        ? '<div class="empty">아직 업로드 없음 — 네이티브앱 REC 활성화 시 표시</div>'
        : evs.slice(0, 14).map((ev, idx) => {
            const ent = ev.entropy || 0;
            const cls = ent >= 0.8 ? 'hi' : ent >= 0.6 ? 'mi' : 'lo';
            const ic = ent >= 0.8 ? '⚠' : ent >= 0.6 ? '⚡' : '●';
            const ts = ev.ts ? new Date(ev.ts.endsWith('Z') ? ev.ts : ev.ts + 'Z') : null;
            const diff = ts ? Math.floor((Date.now() - ts.getTime()) / 1000) : 0;
            const tStr = diff < 60 ? diff + 's' : Math.floor(diff/60) + 'm';
            // v12.83: location_verified 배지 — verified=true (✓) / false (?) + 거리
            const lv = ev.location_verified;
            const isV = lv && (lv.verified === true);
            const lvIcon = isV ? '✓' : '?';
            const lvColor = isV ? '#00E09A' : 'rgba(255,176,32,0.7)';
            const lvTitle = lv ? esc(lv.note || '') : '미검증';
            const lvBadge = '<span title="' + lvTitle + '" style="color:' + lvColor + ';font-family:monospace;font-size:9px;margin-left:4px;border:1px solid ' + lvColor + ';border-radius:6px;padding:0 4px;font-weight:900;">' + lvIcon + '</span>';
            // v12.121: PROOF 링크 — /fleet/proof/{idx} 새 탭 forensic 검증
            const proofLink = '<a href="/fleet/proof/' + idx + '" target="_blank" title="forensic evidence trail" style="margin-left:6px;color:rgba(0,200,255,0.7);font-family:monospace;font-size:9px;text-decoration:none;border:1px solid rgba(0,200,255,0.3);border-radius:6px;padding:0 4px;font-weight:900;" onclick="event.stopPropagation();">🔍</a>';
            return '<div class="ev"><div class="ic ' + cls + '">' + ic + '</div><div class="meta">' + esc(ev.reason || '?') + lvBadge + proofLink + '<span class="sub">' + esc(ev.intersection_id || '—') + ' · ' + tStr + ' ago</span></div><div class="ent ' + cls + '">' + ent.toFixed(2) + '</div></div>';
          }).join('');
      document.getElementById('lsBody').innerHTML = html;
      // verified pct 헤더에 표시
      if (live.events_verified_pct != null) {
        const ct = document.getElementById('lsCt');
        if (ct) ct.textContent = (live.events_total||0) + ' ev · ' + live.events_verified_pct + '% verified · ' + (live.active_devices_5m||0) + ' dev';
      }
      // 지도 이벤트 마커 — verified=true 는 채워진 원, false 는 점선 테두리
      evL.clearLayers();
      evs.forEach(ev => {
        if (ev.lat == null || ev.lon == null) return;
        const ent = ev.entropy || 0;
        const c = ent >= 0.8 ? '#FF4040' : ent >= 0.6 ? '#FFB020' : '#00E09A';
        const isV = ev.location_verified && ev.location_verified.verified === true;
        L.circleMarker([ev.lat, ev.lon], {
          radius: 4 + ent * 6, color: c, fillColor: c,
          fillOpacity: isV ? 0.6 : 0.10,
          weight: isV ? 1 : 2, dashArray: isV ? null : '3,3'
        }).bindPopup('<b>' + esc(ev.reason || '?') + '</b><br>ent=' + ent.toFixed(2) + (ev.location_verified ? '<br>📍 ' + esc(ev.location_verified.note||'') : '')).addTo(evL);
      });
    }
  } catch (e) { console.error('tick', e); }
}
tick();
setInterval(tick, 5000);
</script>
</body>
</html>
"""




@app.get("/demos", response_class=HTMLResponse)
def demos_9tabs():
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
              <div class="eyebrow">AuraView · Prototype v0.1</div>
              <h1><em>AuraView</em> Dashboard</h1>
              <div class="subtitle">보이지 않는 신호를 대신 보여주는 시야 차단 대응형 안전 주행 보조 시스템</div>
            </div>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
              <a href="/story/" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:1.5px;color:#0a0e18;padding:9px 16px;background:linear-gradient(135deg,#FFB020,#FF6B6B);border:1px solid rgba(255,176,32,0.7);border-radius:99px;font-weight:900;box-shadow:0 0 18px rgba(255,176,32,0.45);">📖 일반인용 30초 스토리</a>
              <a href="/reel/" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:1.5px;color:#fff;padding:9px 16px;background:linear-gradient(135deg,#FF4444,#7c3aed);border:1px solid rgba(255,68,68,0.7);border-radius:99px;font-weight:900;box-shadow:0 0 18px rgba(255,68,68,0.45);">🎥 1분 시연</a>
              <a href="/competition/" target="_blank" style="text-decoration:none;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.5px;color:#fff;padding:7px 14px;background:linear-gradient(135deg,rgba(0,224,154,0.30),rgba(0,200,255,0.20));border:1px solid rgba(0,224,154,0.55);border-radius:99px;font-weight:700;">🏆 SYSTEM HUB</a>
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
            <div class="tab" data-tab="tab10">⑩ 공공데이터 라이브</div>
          </div>
        </div>

        <div class="content">

          <!-- TAB 1 -->
          <div class="tab-panel active" id="tab1">

            <!-- 🚦 가려진 신호등 자동 안내 (실 데이터 자동 순환 · 5초 주기) -->
            <div style="margin-bottom:14px;padding:18px 20px;background:linear-gradient(135deg,rgba(255,59,59,0.08),rgba(255,176,32,0.04));border:1px solid rgba(255,176,32,0.30);border-radius:14px;position:relative;overflow:hidden;">
              <div style="position:absolute;top:0;left:0;height:100%;width:4px;background:linear-gradient(180deg,var(--warn),var(--danger));"></div>
              <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;">
                <div style="flex:1;min-width:0;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:3px;color:var(--warn);display:flex;align-items:center;gap:8px;">
                    <span>// 가려진 신호등 자동 안내 · LIVE</span>
                    <span id="altCycleDot" style="width:7px;height:7px;border-radius:50%;background:var(--safe);box-shadow:0 0 6px var(--safe);"></span>
                  </div>
                  <div id="altSignalGuide" style="margin-top:6px;font-family:'Black Han Sans',sans-serif;font-size:18px;line-height:1.3;color:var(--warn);">
                    실시간 위험 교차로 데이터 로딩 중…
                  </div>
                  <div id="altSignalSub" style="margin-top:4px;color:var(--muted);font-size:12px;font-family:'JetBrains Mono',monospace;"></div>
                </div>
                <div id="altRotInfo" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);text-align:right;">
                  <div id="altCycleIdx">- / -</div>
                  <div style="margin-top:2px;">5초 주기 자동 순환</div>
                </div>
              </div>
            </div>
            <script>
              // 자동 순환: TOP-N 위험 교차로를 5초마다 alt_guide 표시
              let _altRotI = 0;
              let _altRotData = [];

              async function refreshAltRotData() {
                try {
                  const r = await fetch(window.location.origin + '/events/map-data');
                  const all = await r.json();
                  _altRotData = all.slice().sort((a,b) => (b.risk_score||0) - (a.risk_score||0)).slice(0, 5);
                } catch(e) {}
              }

              async function tickAltSignal() {
                if (_altRotData.length === 0) {
                  document.getElementById('altSignalGuide').textContent = '실 위험 교차로 데이터 없음';
                  return;
                }
                _altRotI = (_altRotI) % _altRotData.length;
                const item = _altRotData[_altRotI];
                // occlusion_score 는 risk_score 기반 추정 (risk 18 → 0.85, risk 9 → 0.50 등)
                const occ = Math.min(0.95, Math.max(0.30, ((item.risk_score || 0) / 20)));
                try {
                  const r = await fetch(window.location.origin + '/signals/' + item.intersection_id + '/alternate?occlusion_score=' + occ.toFixed(2)).then(r => r.json());
                  // 한글 교차로명 우선
                  const iname = (window._intNames && window._intNames[item.intersection_id]) || ('교차로 ' + item.intersection_id);
                  document.getElementById('altSignalGuide').textContent = r.alt_guide || '대체 안내 없음';
                  document.getElementById('altSignalSub').innerHTML =
                    '<span style="color:var(--text);font-weight:700;">' + iname + '</span>' +
                    ' · ' + r.signal_state +
                    (r.remain_time_s !== null && r.remain_time_s !== undefined ? ' · 남은 ' + r.remain_time_s + '초' : '') +
                    ' · risk ' + r.risk_score +
                    ' · <span style="color:var(--accent);">' + (r.alt_action || '') + '</span>';
                  document.getElementById('altCycleIdx').textContent = '#' + (_altRotI+1) + ' / ' + _altRotData.length;
                  // 점등 효과 — 짧게 시안 → 안전(녹색)
                  const dot = document.getElementById('altCycleDot');
                  if (dot) {
                    dot.style.background = 'var(--accent)';
                    dot.style.boxShadow = '0 0 10px var(--accent)';
                    setTimeout(() => {
                      dot.style.background = 'var(--safe)';
                      dot.style.boxShadow = '0 0 6px var(--safe)';
                    }, 600);
                  }
                } catch(e) {
                  document.getElementById('altSignalSub').textContent = '/signals API 응답 실패: ' + e.message;
                }
                _altRotI = (_altRotI + 1) % _altRotData.length;
              }

              // 첫 로드: 데이터 받아오고 즉시 1회 + 5초 주기 + 30초마다 데이터 재갱신
              setTimeout(async () => {
                await refreshAltRotData();
                tickAltSignal();
                setInterval(tickAltSignal, 5000);
                setInterval(refreshAltRotData, 30000);
              }, 800);
            </script>

            <!-- ⭐ IMPACT BANNER — 첫 화면 시각 헤드라인 -->
            <div style="margin-bottom:14px;padding:18px 20px;background:linear-gradient(135deg,rgba(0,224,154,0.10),rgba(0,200,255,0.06));border:1px solid rgba(0,224,154,0.30);border-radius:14px;display:flex;flex-wrap:wrap;align-items:center;gap:18px;">
              <div style="flex:1 1 280px;min-width:0;">
                <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:3px;color:var(--safe);">
                  // PROJECTED ANNUAL PREVENTION · TAAS 2024
                </div>
                <div id="tab1ImpactHeadline" style="margin-top:6px;font-family:'Black Han Sans',sans-serif;font-size:22px;line-height:1.3;color:var(--safe);">
                  Pilot 5% 도입 → 연간 사망 21명 · 부상 2,370명 예방
                </div>
                <div id="tab1ImpactSub" style="margin-top:6px;color:var(--muted);font-size:12px;">
                  Top-22 광역시 도입 시 164명 예방 · Top-1 강남역 11.8명/년
                </div>
              </div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <a href="/impact" target="_blank" style="background:rgba(0,200,255,0.10);color:var(--accent);padding:8px 14px;border-radius:8px;text-decoration:none;font-size:12px;font-weight:700;border:1px solid var(--border);">/impact JSON</a>
                <a href="/submission/" target="_blank" style="background:rgba(0,224,154,0.10);color:var(--safe);padding:8px 14px;border-radius:8px;text-decoration:none;font-size:12px;font-weight:700;border:1px solid rgba(0,224,154,0.30);">제출 페이지 →</a>
              </div>
            </div>
            <script>
              (async function(){
                try {
                  const im = await fetch(window.location.origin + '/impact').then(r => r.json());
                  const ti = await fetch(window.location.origin + '/impact/top-intersections?scope=national&top_n=22').then(r => r.json());
                  const sc = await fetch(window.location.origin + '/impact/scenarios').then(r => r.json());
                  const pilot = sc.scenarios.find(s => Math.abs(s.coverage - 0.05) < 0.001);
                  if (pilot) document.getElementById('tab1ImpactHeadline').textContent =
                    'Pilot 5% 도입 → 연간 사망 ' + pilot.prevented_deaths.toLocaleString() + '명 · 부상 ' + pilot.prevented_injured.toLocaleString() + '명 예방';
                  if (ti) {
                    const top1 = ti.intersections[0];
                    document.getElementById('tab1ImpactSub').textContent =
                      'Top-22 광역시 도입 시 ' + Math.round(ti.total_prevented_kis_yearly) + '명 예방 · Top-1 ' + top1.name + ' ' + top1.prevented_kis_yearly + '명/년';
                  }
                } catch(e) {}
              })();
            </script>

            <div class="dashboard-grid">
              <div class="left-col">
                <!-- Fleet 자동 수집 통합 통계 (사용자 입력 폼 X) -->
                <div class="card">
                  <div class="card-tag">FLEET · 자동 수집 통계</div>
                  <div class="section-label">// 폰 → AuraView 백엔드 → 모델 재학습</div>
                  <div class="hero-copy">
                    <div class="hero-title">현장 데이터는 사용자 폰이 자동 수집</div>
                    <div class="hero-desc">PWA / Native 앱이 위험 순간만 PII 마스킹 후 업로드. 본 대시보드는 누적 통계 + 라이브 분포 시각화.</div>
                  </div>
                  <div id="dashStats" style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:14px;">
                    <div class="stat" style="padding:14px;border-radius:10px;background:rgba(0,200,255,0.06);border:1px solid var(--border);">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;">FLEET 누적</div>
                      <div id="dashUploads" style="font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--accent);">…</div>
                      <div style="font-size:11px;color:var(--muted);">건 (PII 마스킹 완료)</div>
                    </div>
                    <div class="stat" style="padding:14px;border-radius:10px;background:rgba(0,224,154,0.06);border:1px solid var(--border);">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;">활성 단말</div>
                      <div id="dashDevices" style="font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--safe);">…</div>
                      <div style="font-size:11px;color:var(--muted);">대 (라이브 polling)</div>
                    </div>
                    <div class="stat" style="padding:14px;border-radius:10px;background:rgba(255,176,32,0.06);border:1px solid var(--border);">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;">생성 시나리오</div>
                      <div id="dashScenarios" style="font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--warn);">…</div>
                      <div style="font-size:11px;color:var(--muted);">편 (재현 영상)</div>
                    </div>
                    <div class="stat" style="padding:14px;border-radius:10px;background:rgba(124,58,237,0.06);border:1px solid var(--border);">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;">정책 리포트</div>
                      <div id="dashReports" style="font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--accent2,#7c3aed);">…</div>
                      <div style="font-size:11px;color:var(--muted);">건 (Top-N 자동)</div>
                    </div>
                  </div>
                  <div style="margin-top:14px;padding:12px;background:var(--surface2);border-radius:10px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);">
                    📱 사용자 흐름: <a href="/pwa/" target="_blank" style="color:var(--accent);">/pwa</a> 또는 Native APK → 카메라 자동 캡처<br>
                    🤖 자동 트리거: 🚦 신호 가림 · 🚛 횡단보도 가림 · ◀▶ 사각지대<br>
                    🔒 업로드 시: PII 마스킹 + 위치 + heading + 속도
                  </div>
                </div>

                <!-- ⚠️ TOP 우선순위 액션 카드 — 좌측 하단 채움 -->
                <div class="card" id="priorityCard" style="margin-top:14px;background:linear-gradient(135deg,rgba(255,59,59,0.10),rgba(255,176,32,0.04));border:1.5px solid rgba(255,59,59,0.35);position:relative;overflow:hidden;">
                  <div style="position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--danger),var(--warn),var(--danger));animation:pri-pulse 2.4s ease-in-out infinite;"></div>
                  <style>@keyframes pri-pulse{0%,100%{opacity:0.55}50%{opacity:1}}</style>
                  <div class="card-tag" style="background:rgba(255,59,59,0.18);color:var(--danger);">⚠️ TOP PRIORITY · 즉시 조치</div>
                  <div class="section-label">// risk_score 1순위 자동 권고</div>
                  <div id="priorityBody" style="margin-top:12px;">
                    <div class="placeholder" style="min-height:120px;">우선순위 데이터 로딩 중…</div>
                  </div>
                </div>

                <!-- 📊 24h 시간대별 이벤트 분포 -->
                <div class="card" style="margin-top:14px;">
                  <div class="card-tag">24-HOUR EVENT DISTRIBUTION</div>
                  <div class="section-label">// 시간대별 위험 이벤트 발생 분포 (24h)</div>
                  <canvas id="hourChart" height="140" style="width:100%;height:140px;margin-top:10px;"></canvas>
                  <div id="hourLegend" style="margin-top:8px;display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);">
                    <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:59</span>
                  </div>
                </div>

                <!-- ▶ 데모 시드 (실데이터 부족할 때 1회) -->
                <div id="demoSeedBox" style="margin-top:12px;display:none;padding:10px 12px;background:rgba(0,200,255,0.06);border:1px dashed var(--accent);border-radius:8px;font-size:11px;color:var(--muted);">
                  <span>실 이벤트가 적습니다. 데모 시연용으로 서울 교차로 8개 이벤트를 한 번에 시딩할까요?</span>
                  <button onclick="seedDemoEvents()" style="margin-left:8px;background:var(--accent);color:#000;padding:5px 12px;border-radius:6px;border:none;font-weight:700;font-size:11px;cursor:pointer;">데모 시드</button>
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

          <!-- TAB 2 : BEV Occupancy + 사각지대/신호 가림 통합 데모 -->
          <div class="tab-panel" id="tab2">

            <!-- 시나리오 picker -->
            <div class="card" style="margin-bottom:14px;">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--accent),var(--accent2));">⚠️ 사각지대 / 신호 가림 / 우천 / 야간 — 통합 시나리오 데모</div>
              <div class="section-label">// 클릭 시 BEV 객체 클러스터 + 알림 HUD 즉시 갱신 (1초 주기 라이브)</div>
              <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-top:12px;" id="scnPickerRow">
                <button data-scn="truck_occlusion" onclick="setOccScenario('truck_occlusion')" class="scn-btn active" style="padding:14px;background:rgba(255,90,90,0.12);border:2px solid var(--danger);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">🚛</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--danger);margin-top:4px;">트럭 가림 + 보행자</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">정지선 12m 전 · risk 0.68</div>
                </button>
                <button data-scn="motorcycle_blindspot" onclick="setOccScenario('motorcycle_blindspot')" class="scn-btn" style="padding:14px;background:rgba(255,176,32,0.10);border:2px solid var(--border);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">◀</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--warn);margin-top:4px;">좌측 사각지대 이륜차</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">차선 변경 직전 · risk 0.72</div>
                </button>
                <button data-scn="signal_occlusion" onclick="setOccScenario('signal_occlusion')" class="scn-btn" style="padding:14px;background:rgba(0,200,255,0.08);border:2px solid var(--border);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">🚦</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--accent);margin-top:4px;">버스 뒤 신호 가림</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">교차로 18m 전 · risk 0.58</div>
                </button>
                <button data-scn="rainy_intersection" onclick="setOccScenario('rainy_intersection')" class="scn-btn" style="padding:14px;background:rgba(124,58,237,0.08);border:2px solid var(--border);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">🌧️</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--accent2);margin-top:4px;">우천 + 우산 보행자</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">노면 반사 · risk 0.61</div>
                </button>
                <button data-scn="right_turn_pedestrian" onclick="setOccScenario('right_turn_pedestrian')" class="scn-btn" style="padding:14px;background:rgba(255,59,59,0.10);border:2px solid var(--border);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">🚸</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--danger);margin-top:4px;">우회전 보행자</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">A필러 사각 · risk 0.78</div>
                </button>
                <button data-scn="school_zone" onclick="setOccScenario('school_zone')" class="scn-btn" style="padding:14px;background:rgba(255,176,32,0.10);border:2px solid var(--border);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">🏫</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--warn);margin-top:4px;">스쿨존 · 갑작 어린이</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">DSZ + 등하교 prior · risk 0.74</div>
                </button>
                <button data-scn="bicycle_lane" onclick="setOccScenario('bicycle_lane')" class="scn-btn" style="padding:14px;background:rgba(0,224,154,0.08);border:2px solid var(--border);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">🚴</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--safe);margin-top:4px;">자전거 도로 · 후방 자전거</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">A필러 사각 · risk 0.69</div>
                </button>
                <button data-scn="night_pedestrian" onclick="setOccScenario('night_pedestrian')" class="scn-btn" style="padding:14px;background:rgba(124,58,237,0.10);border:2px solid var(--border);color:var(--text);border-radius:10px;cursor:pointer;text-align:left;font-family:inherit;">
                  <div style="font-size:24px;">🌙</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--accent2);margin-top:4px;">야간 무단횡단</div>
                  <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;">헤드라이트 거리 밖 · risk 0.79</div>
                </button>
              </div>
            </div>

            <!-- 알림 HUD 카드 (BEV 위에 겹쳐서 시뮬레이션) -->
            <div id="alertHud" class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(255,90,90,0.12),rgba(255,176,32,0.06));border:1.5px solid rgba(255,90,90,0.50);position:relative;overflow:hidden;">
              <div style="position:absolute;top:0;left:0;height:100%;width:4px;background:linear-gradient(180deg,var(--danger),var(--warn));animation:pri-pulse 1.6s ease-in-out infinite;"></div>
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
                <div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:3px;color:var(--danger);">🚨 LIVE ALERT · HUD 표시 텍스트</div>
                  <div id="alertHudText" style="margin-top:4px;font-family:'Black Han Sans',sans-serif;font-size:22px;color:var(--text);line-height:1.25;">시나리오 로딩 중…</div>
                  <div id="alertHudSub" style="margin-top:4px;font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;"></div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(2,auto);gap:6px;font-family:'JetBrains Mono',monospace;font-size:10px;">
                  <div style="text-align:right;color:var(--muted);">충돌 확률</div><div id="alertHudPC" style="color:var(--danger);font-weight:700;">…</div>
                  <div style="text-align:right;color:var(--muted);">선행 경고</div><div id="alertHudLT" style="color:var(--safe);font-weight:700;">…</div>
                  <div style="text-align:right;color:var(--muted);">권고</div><div id="alertHudAct" style="color:var(--accent);font-weight:700;">…</div>
                </div>
              </div>
            </div>

            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card">
                  <div class="section-label">// 검출된 객체 · 거리 / 종류 / 라벨</div>
                  <div id="hotspotList" style="margin-top:8px;display:grid;gap:6px;font-family:'JetBrains Mono',monospace;font-size:11px;">
                    <div class="placeholder">시나리오 로딩 중…</div>
                  </div>
                </div>

                <div class="card">
                  <div class="section-label">// 시나리오 설명 · AuraView 강점</div>
                  <div id="scnNarrative" style="margin-top:8px;font-size:12px;color:var(--text);line-height:1.5;">…</div>
                  <div id="scnAdv" style="margin-top:10px;padding:10px;background:rgba(0,224,154,0.08);border-left:3px solid var(--safe);border-radius:6px;font-size:11px;color:var(--text);font-family:'JetBrains Mono',monospace;line-height:1.5;">…</div>
                </div>

                <div class="card">
                  <div class="section-label">// 직접 이미지 추론 (선택)</div>
                  <details>
                    <summary style="cursor:pointer;color:var(--muted);font-size:11px;font-family:'JetBrains Mono',monospace;">▸ 사용자 이미지로 BEV 추정</summary>
                    <div class="form-grid" style="margin-top:10px;">
                      <div>
                        <label>현장 이미지</label>
                        <label class="file-label" id="occLabel" for="occ_file">
                          <span>📷</span><span id="occName">이미지를 선택하세요</span>
                        </label>
                        <input id="occ_file" type="file" accept="image/*" onchange="updateFileLabel('occ_file','occLabel','occName')"/>
                      </div>
                      <div class="btn-row">
                        <div><label>지속(s)</label><input id="occ_duration" type="number" step="0.1" value="3.5"/></div>
                        <div><label>장애물</label><select id="occ_obstacle"><option value="truck">truck</option><option value="bus">bus</option><option value="car">car</option></select></div>
                      </div>
                      <button class="btn-accent" onclick="runOccupancy()">BEV 추정</button>
                    </div>
                    <div id="occAttention" class="rank-body" style="margin-top:10px;font-size:11px;"></div>
                    <div id="occResultBox" class="status" style="margin-top:10px;"><div class="status-meta">결과가 여기 표시됩니다.</div></div>
                  </details>
                </div>
              </div>

              <div class="right-col">
                <div class="card">
                  <div class="section-label">// BEV Tesla-style · 객체별 색상 클러스터 · <span id="occModeLabel">3D Voxel</span></div>
                  <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
                    <button class="btn-secondary" style="width:auto;padding:7px 12px;font-size:11px;" onclick="setOccMode('2d')">2D Heatmap</button>
                    <button class="btn-accent" style="width:auto;padding:7px 12px;font-size:11px;" onclick="setOccMode('3d')">3D Voxel</button>
                    <span style="margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);align-self:center;">자동 갱신 1초</span>
                  </div>
                  <div class="preview-wrap" id="occCanvasWrap" style="height:640px;display:flex;align-items:center;justify-content:center;">
                    <div class="placeholder"><div class="placeholder-icon">🗺️</div>BEV 추정 결과 로딩 중…</div>
                  </div>
                  <canvas id="occThreeCanvas" style="display:none;width:100%;height:640px;border-radius:12px;background:#04080e;"></canvas>
                  <!-- 색상 범례 -->
                  <div style="margin-top:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:6px;font-family:'JetBrains Mono',monospace;font-size:10px;">
                    <div style="display:flex;align-items:center;gap:5px;"><span style="display:inline-block;width:12px;height:12px;background:#3a8fff;border-radius:2px;"></span><span style="color:var(--muted);">Vehicle</span></div>
                    <div style="display:flex;align-items:center;gap:5px;"><span style="display:inline-block;width:12px;height:12px;background:#ff8c00;border-radius:2px;"></span><span style="color:var(--muted);">Motorcycle</span></div>
                    <div style="display:flex;align-items:center;gap:5px;"><span style="display:inline-block;width:12px;height:12px;background:#7c3aed;border-radius:2px;opacity:0.6;"></span><span style="color:var(--muted);">Occlusion</span></div>
                    <div style="display:flex;align-items:center;gap:5px;"><span style="display:inline-block;width:12px;height:12px;background:#00d8ff;border-radius:2px;"></span><span style="color:var(--muted);">Pedestrian</span></div>
                    <div style="display:flex;align-items:center;gap:5px;"><span style="display:inline-block;width:12px;height:12px;background:#ff5a5a;border-radius:2px;"></span><span style="color:var(--muted);">Signal</span></div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 3 : Fusion -->
          <div class="tab-panel" id="tab3">
            <div class="card">
              <div class="card-tag">FUSION · 5점 · v2 ★</div>
              <div class="section-label">// 24종 공공데이터 한 응답 결합 (v10-2026.05.25 USGS earthquake 추가)</div>
              <div class="hero-copy">
                <div class="hero-title">교차로 한 곳 = 9종 데이터 한 호출</div>
                <div class="hero-desc">신호 · VDS · 돌발 · TAAS · ITS · 안심구역 · <b style="color:var(--accent2);">기상(KMA) · 응급실(NEDIS) · 따릉이</b> — 각 어댑터가 동일 교차로에 대해 동시 조회 후 단일 JSON 으로 결합 반환합니다. 기상 가중치(우천+0.18) · 응급실 심각도 보정 · 자전거도로 prior(+0.22) 가 자동 합산됩니다.</div>
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
            <!-- 데이터 흐름 다이어그램 — Flutter 폰 → AuraView → 재학습 -->
            <div class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(0,200,255,0.06),rgba(124,58,237,0.04));">
              <div class="card-tag">FLEET LEARNING FLYWHEEL · LIVE</div>
              <div class="section-label">// 폰 → 엣지 추론 → 어려운 장면만 PII 마스킹 → 업로드 → 모델 재학습</div>
              <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-top:14px;">
                <div style="flex:1 1 140px;min-width:140px;text-align:center;padding:14px;background:rgba(0,200,255,0.06);border:1px solid var(--border);border-radius:10px;">
                  <div style="font-size:32px;">📱</div>
                  <div style="font-weight:700;color:var(--accent);">Flutter 앱</div>
                  <div style="font-size:11px;color:var(--muted);margin-top:4px;">엣지 추론 + 임계 초과만 업로드</div>
                </div>
                <div style="font-size:24px;color:var(--muted);">→</div>
                <div style="flex:1 1 140px;min-width:140px;text-align:center;padding:14px;background:rgba(255,176,32,0.06);border:1px solid var(--border);border-radius:10px;">
                  <div style="font-size:32px;">🔒</div>
                  <div style="font-weight:700;color:var(--warn);">PII 마스킹</div>
                  <div style="font-size:11px;color:var(--muted);margin-top:4px;">얼굴/번호판 자동 블러</div>
                </div>
                <div style="font-size:24px;color:var(--muted);">→</div>
                <div style="flex:1 1 140px;min-width:140px;text-align:center;padding:14px;background:rgba(0,224,154,0.06);border:1px solid var(--border);border-radius:10px;">
                  <div style="font-size:32px;">📥</div>
                  <div style="font-weight:700;color:var(--safe);">업로드 누적</div>
                  <div id="flowUploadCount" style="font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--text);margin-top:2px;">…</div>
                  <div id="flowDeviceCount" style="font-size:11px;color:var(--muted);">… 단말</div>
                </div>
                <div style="font-size:24px;color:var(--muted);">→</div>
                <div style="flex:1 1 140px;min-width:140px;text-align:center;padding:14px;background:rgba(124,58,237,0.06);border:1px solid var(--border);border-radius:10px;">
                  <div style="font-size:32px;">🧠</div>
                  <div style="font-weight:700;color:var(--accent2);">모델 재학습</div>
                  <div style="font-size:11px;color:var(--muted);margin-top:4px;">AUC <span id="flowAuc">…</span></div>
                </div>
              </div>
              <div style="margin-top:10px;text-align:center;font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;">
                실데이터 → <a href="/fleet/stats" target="_blank" style="color:var(--accent);">/fleet/stats</a> · <a href="/healthz/details" target="_blank" style="color:var(--accent);">/healthz/details</a>
              </div>
            </div>

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
                  <div class="section-label">// 엣지 단말 설치 — PWA 또는 Native APK</div>
                  <div class="hero-copy">
                    <div class="hero-title">📱 스마트폰이 그대로 엣지 단말</div>
                    <div class="hero-desc">QR 스캔 시 카메라 Shadow Mode 자동 시작. PWA는 즉시, APK는 GitHub Releases 최신 빌드.</div>
                  </div>
                  <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:14px;">
                    <div style="text-align:center;">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--accent);letter-spacing:2px;margin-bottom:6px;">PWA · 즉시 설치</div>
                      <div id="pwaQr" style="display:flex;justify-content:center;background:#fff;border-radius:12px;padding:10px;"></div>
                      <div style="margin-top:8px;">
                        <a id="pwaLink" href="/pwa" target="_blank" style="color:var(--accent);font-family:'JetBrains Mono',monospace;font-size:11px;">/pwa</a>
                      </div>
                    </div>
                    <div style="text-align:center;">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--safe);letter-spacing:2px;margin-bottom:6px;">APK · 네이티브</div>
                      <div id="apkQr" style="display:flex;justify-content:center;background:#fff;border-radius:12px;padding:10px;"></div>
                      <div style="margin-top:8px;">
                        <a id="apkLink" href="https://github.com/leelang7/AuraView/releases/latest/download/auraview_fleet.apk" target="_blank" style="color:var(--safe);font-family:'JetBrains Mono',monospace;font-size:11px;">latest APK ↓</a>
                      </div>
                    </div>
                  </div>
                  <div style="margin-top:10px;padding:8px 10px;background:var(--surface2);border-radius:8px;font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;text-align:center;">
                    APK 설치 시 "출처 알 수 없는 앱 허용" 1회 필요 · BEV HUD + Fleet 자동 업로드
                  </div>
                </div>
              </div>
            </div>

            <!-- Fleet 업로드 갤러리 — 관리자 검수 / 삭제 (인증 필요) -->
            <div class="card" style="margin-top:14px;">
              <div class="card-tag">🔒 UPLOADED HARD SAMPLES · ADMIN ONLY</div>
              <div class="section-label">// PII 마스킹된 업로드 이미지 — 관리자 토큰 인증 필수</div>

              <!-- 잠금 상태 (토큰 없을 때) -->
              <div id="fleetLocked" style="margin-top:14px;padding:24px;background:var(--surface2);border:1px dashed var(--border);border-radius:12px;text-align:center;">
                <div style="font-size:36px;margin-bottom:10px;">🔒</div>
                <div style="font-weight:700;color:var(--text);">관리자 인증 필요</div>
                <div style="font-size:11px;color:var(--muted);margin-top:6px;">업로드된 이미지·삭제 기능은 관리자만 접근할 수 있습니다.</div>
                <button class="btn-secondary" onclick="adminLogin()" style="margin-top:14px;">관리자 로그인</button>
              </div>

              <!-- 갤러리 본문 (인증 후 표시) -->
              <div id="fleetGalleryWrap" style="display:none;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;flex-wrap:wrap;gap:8px;">
                  <div id="fleetGalleryStats" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);">로딩 중…</div>
                  <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    <button class="btn-secondary" onclick="loadFleetGallery()" style="font-size:11px;padding:6px 10px;">새로고침</button>
                    <button class="btn-secondary" onclick="adminLogout()" style="font-size:11px;padding:6px 10px;">로그아웃</button>
                  </div>
                </div>
                <!-- 일괄 선택 툴바 -->
                <div style="margin-top:10px;padding:10px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                  <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:11px;font-family:'JetBrains Mono',monospace;">
                    <button onclick="selectAll()" style="background:rgba(0,200,255,0.12);border:1px solid var(--accent);color:var(--accent);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;">전체 선택</button>
                    <button onclick="selectNone()" style="background:var(--surface);border:1px solid var(--border);color:var(--text);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;">선택 해제</button>
                    <button onclick="invertSelection()" style="background:var(--surface);border:1px solid var(--border);color:var(--text);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;">반전</button>
                  </div>
                  <div style="display:flex;align-items:center;gap:10px;">
                    <span id="selCount" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);">0건 선택</span>
                    <button id="bulkDelBtn" onclick="bulkDelete()" disabled style="background:rgba(255,90,90,0.15);border:1px solid var(--danger);color:var(--danger);padding:6px 14px;border-radius:6px;cursor:pointer;font-weight:700;font-size:12px;opacity:0.5;">선택 삭제</button>
                  </div>
                </div>
                <div id="fleetGallery" style="margin-top:14px;display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;max-height:560px;overflow:auto;padding:4px;">
                  <div class="placeholder" style="grid-column:1/-1;">갤러리 로딩 중…</div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 6 : Accident Reenactment -->
          <div class="tab-panel" id="tab6">

            <!-- ★ 합본 hero — 가장 위에 즉시 재생 (탭 진입시 /showreel/latest 자동 로드) -->
            <div class="card" style="margin-bottom:18px;">
              <div class="card-tag" style="background:linear-gradient(135deg, var(--accent), var(--accent2));">⭐ SHOWREEL · LATEST</div>
              <div class="section-label">// 합본 시연 영상 (음향 포함, 자동 재생)</div>
              <div id="showreelHero" class="preview-wrap" style="height:480px;display:flex;align-items:center;justify-content:center;background:#000;border-radius:12px;">
                <div class="placeholder"><div class="placeholder-icon">🎬</div>합본 영상 로딩…</div>
              </div>
              <div id="showreelMeta" style="margin-top:10px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);"></div>
            </div>

            <div class="dashboard-grid">
              <div class="left-col">
                <div class="card">
                  <div class="card-tag">REENACTMENT</div>
                  <div class="section-label">// AuraView 가 자동으로 만든 합본 시연 영상 (위에서 재생 중)</div>
                  <div class="hero-copy">
                    <div class="hero-title">AuraView 였다면 몇 초 먼저 경고할 수 있었을까?</div>
                    <div class="hero-desc">상단의 합본 영상은 8 시나리오 voxel(트럭/이륜/신호/우천/우회전/스쿨존/자전거/야간) + V2V 협업 인지. 평균 선행 경고 <strong style="color:var(--accent);">3.38초</strong>.</div>
                  </div>

                  <div id="scnStatus" class="status" style="margin-top:14px;">
                    <div class="status-title">합본 영상 자동 갱신</div>
                    <div class="status-main">매주 1회 자동 빌드 (cron)</div>
                    <div class="status-meta">최신 합본: <a href="/showreel/latest.mp4" target="_blank" style="color:var(--accent);">/showreel/latest.mp4</a></div>
                  </div>

                  <!-- 어드민/검증용 — 수동 빌드 트리거 (접힘) -->
                  <details style="margin-top:14px;">
                    <summary style="color:var(--muted);font-size:12px;cursor:pointer;letter-spacing:1.5px;font-family:'JetBrains Mono',monospace;">
                      // ADMIN · 사용자 영상 업로드 (블랙박스 → AuraView 추론)
                    </summary>
                    <div class="form-grid" style="margin-top:12px;">
                      <div>
                        <label>블랙박스 영상 (선택)</label>
                        <label class="file-label" id="scnLabel" for="scn_video">
                          <span>🎬</span>
                          <span id="scnName">영상 또는 합성 시나리오 선택</span>
                        </label>
                        <input id="scn_video" type="file" accept="video/*" onchange="updateFileLabel('scn_video','scnLabel','scnName')"/>
                      </div>
                      <div>
                        <label>합성 시나리오</label>
                        <select id="scn_preset">
                          <option value="">— 선택 안 함 —</option>
                          <option value="crosswalk_truck">횡단보도 · 대형차 가림</option>
                          <option value="motorcycle_blindspot">사각지대 · 이륜차</option>
                          <option value="signal_occluded">신호 가림 + 급감속</option>
                          <option value="v2v_collab">⭐ V2V 협업 인지</option>
                          <option value="rainy_intersection">🌧️ 우천 + 우산 보행자</option>
                          <option value="night_blindspot">🌙 야간 사각지대</option>
                        </select>
                      </div>
                      <button class="btn-accent" onclick="runScenario()">사고 재현 영상 생성</button>
                      <button class="btn-secondary" onclick="loadScenarioList()">최근 생성물 목록</button>
                      <button class="btn-video" onclick="buildShowreel()">⭐ 새 합본 빌드</button>
                    </div>
                    <p style="margin-top:8px;font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;">
                      일반 사용자 흐름 X — 개발자 검증 또는 새 영상 즉석 생성용.
                    </p>
                  </details>
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

          <!-- TAB 10 : 공공데이터 라이브 — judge-검증용 실시간 9종 소스 상태 (v2: 6→9 확장) -->
          <div class="tab-panel" id="tab10">
            <div class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(0,200,255,0.08),rgba(0,224,154,0.04));border:1px solid rgba(0,200,255,0.30);">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--accent),var(--safe));">PUBLIC DATA · LIVE · 9 SOURCES ★</div>
              <div class="section-label">// 24종 공공데이터 어댑터 실시간 상태 — 자동 새로고침 3초 주기 · v10-2026.05.25 · 11/24 no-key live</div>
              <div style="margin-top:10px;font-family:'Black Han Sans',sans-serif;font-size:22px;line-height:1.3;">
                검증 검증용 — 폴링 모드(live/stub/error) · 마지막 호출 시각 · age 그대로 노출.
                <span style="font-size:13px;color:var(--accent2);">신호·VDS·돌발·TAAS·ITS·DSZ + <b>기상·응급실·따릉이 ★ NEW</b></span>
              </div>
              <div id="pdLiveSummary" style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;"></div>
            </div>

            <div class="card">
              <div class="section-label">// 24종 공공데이터 어댑터 (v1 6종 + v2~v10 18종 — 11종 no-key 라이브)</div>
              <div id="pdSourceList" style="margin-top:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;">
                <div class="placeholder">로딩 중…</div>
              </div>
              <div style="margin-top:14px;font-size:11px;color:var(--muted);">
                JSON 직접 호출 · <a href="/fusion/sources" target="_blank" style="color:var(--accent);">/fusion/sources</a> · <a href="/metrics/competition" target="_blank" style="color:var(--accent);">/metrics/competition</a> · <a href="/metrics/scoreboard" target="_blank" style="color:var(--accent);">/metrics/scoreboard</a>
              </div>
            </div>

            <div class="card" style="margin-top:14px;">
              <div class="section-label">// KPI 통합 (모델 성능 · 임팩트 · 공공데이터 · 검증)</div>
              <div id="pdMetricsBox" style="margin-top:10px;font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.6;color:var(--muted);">로딩 중…</div>
            </div>
          </div>

          <!-- TAB 5 : Capability Matrix + Metric -->
          <div class="tab-panel" id="tab5">

            <!-- ⭐ 임팩트 카드 (TAAS 2024 결합) -->
            <div class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(0,224,154,0.10),rgba(0,200,255,0.06));border:1px solid rgba(0,224,154,0.30);">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--safe),var(--accent));">PROJECTED IMPACT · TAAS 2024</div>
              <div class="section-label">// 도입 시 연간 사고/사망/부상 예방 효과 — preventability = min(0.85, 0.25 × lead_time_s)</div>
              <div id="impactHero" style="font-family:'Black Han Sans',sans-serif;font-size:24px;line-height:1.3;margin-top:10px;">로딩 중…</div>
              <div id="impactSub" style="margin-top:6px;color:var(--muted);font-size:12px;font-family:'JetBrains Mono',monospace;"></div>
              <div id="impactScn" style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px;"></div>
              <div style="margin-top:8px;font-size:11px;color:var(--muted);">
                출처 TAAS · KOTI ITS · 라이브 검증 → <a href="/impact" target="_blank" style="color:var(--accent);">/impact JSON</a>
              </div>
            </div>

            <!-- 🎮 인터랙티브 임팩트 시뮬레이터 — 도입률 슬라이더 -->
            <div class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(0,224,154,0.06),rgba(0,200,255,0.03));border:1px solid rgba(0,224,154,0.30);">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--safe),var(--accent));">🎮 IMPACT SIMULATOR · INTERACTIVE</div>
              <div class="section-label">// 슬라이더로 도입 비율 조정 → 연간 예방 효과 실시간 계산 (TAAS 2024 기반)</div>
              <div style="margin-top:14px;">
                <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);letter-spacing:1.5px;">URBAN INTERSECTION COVERAGE</div>
                  <div style="display:flex;gap:8px;align-items:baseline;">
                    <span id="simCovText" style="font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--safe);">10%</span>
                    <span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);">도시 교차로 중</span>
                  </div>
                </div>
                <input id="simCovSlider" type="range" min="1" max="100" value="10" style="width:100%;height:6px;-webkit-appearance:none;appearance:none;background:linear-gradient(90deg,var(--accent),var(--safe));border-radius:3px;outline:none;cursor:pointer;"/>
                <div style="display:flex;justify-content:space-between;margin-top:4px;font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);">
                  <span>1%</span><span>5% Pilot</span><span>25% 확산</span><span>50%</span><span>100% 전국</span>
                </div>
                <div style="margin-top:12px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;">
                  <span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:1.5px;">LEAD TIME</span>
                  <input id="simLeadInput" type="number" value="3.38" step="0.1" min="1.0" max="6.0" style="width:80px;padding:4px 8px;background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:11px;"/>
                  <span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);">초 (모델 평균)</span>
                </div>
              </div>
              <div id="simResult" style="margin-top:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;">
                <div class="placeholder" style="grid-column:1/-1;">시뮬레이션 결과 로딩 중…</div>
              </div>
            </div>

            <!-- ⭐ 위험 교차로 Top-10 + 예방 효과 (서울) -->
            <div class="card" style="margin-bottom:14px;">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--danger),var(--accent2,#7c3aed));">RISK INTERSECTIONS · TOP-10 · SEOUL</div>
              <div class="section-label">// 도입 우선순위 — 강남역·잠실·광화문 등 다발 교차로 + 교차로별 예방 효과</div>
              <div id="topInxHeadline" style="margin-top:10px;font-family:'Black Han Sans',sans-serif;font-size:18px;color:var(--safe);">로딩 중…</div>
              <div id="topInxList" style="margin-top:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;"></div>
              <div style="margin-top:8px;font-size:11px;color:var(--muted);">출처: TAAS 다발지역 + 도로교통공단 · <a href="/impact/top-intersections" target="_blank" style="color:var(--accent);">/impact/top-intersections</a></div>
            </div>

            <!-- 데이터 freshness 배지 -->
            <div class="card" style="margin-bottom:14px;">
              <div class="card-tag">DATA FRESHNESS · LIVE POLLING · 9src</div>
              <div class="section-label">// 24종 공공데이터 마지막 호출 시각 + 응답 모드 (v10-2026.05.25)</div>
              <div id="freshGrid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:10px;">로딩 중…</div>
            </div>

            <!-- 🏗️ 시스템 아키텍처 다이어그램 -->
            <div class="card" style="margin-bottom:14px;">
              <div class="card-tag">SYSTEM ARCHITECTURE · 데이터 흐름</div>
              <div class="section-label">// 엣지 → 서버 → 융합 → 추론 → 정책 환원 (E2E)</div>
              <div style="margin-top:12px;background:#fff;border-radius:12px;padding:10px;overflow:auto;">
                <img src="/static/architecture.svg" alt="AuraView Architecture" style="width:100%;max-width:1200px;display:block;margin:0 auto;"/>
              </div>
            </div>

            <!-- 🔒 데이터 안심구역 + Privacy 흐름 -->
            <div class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(124,58,237,0.06),rgba(0,200,255,0.03));border:1px solid rgba(124,58,237,0.30);">
              <div class="card-tag" style="background:linear-gradient(135deg,#7c3aed,var(--accent2,#a995ff));">🔒 DATA SAFE ZONE · 안심구역 + 가명결합</div>
              <div class="section-label">// 한국 공공 데이터 안심구역(DSZ) 표준 절차 + Edge PII 보호</div>
              <div style="margin-top:14px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;">
                <div style="padding:14px;background:var(--surface2);border-radius:10px;border-left:3px solid var(--accent);">
                  <div style="font-size:24px;text-align:center;">📱</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--accent);letter-spacing:1.5px;text-align:center;margin-top:4px;">EDGE INFER</div>
                  <div style="margin-top:6px;font-size:11px;color:var(--text);font-weight:700;text-align:center;">엣지 추론</div>
                  <div style="margin-top:4px;font-size:10px;color:var(--muted);line-height:1.35;">Flutter 폰이 직접 voxel 생성 · PII 절대 미전송</div>
                </div>
                <div style="padding:14px;background:var(--surface2);border-radius:10px;border-left:3px solid var(--warn);">
                  <div style="font-size:24px;text-align:center;">🎭</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--warn);letter-spacing:1.5px;text-align:center;margin-top:4px;">PII MASK</div>
                  <div style="margin-top:6px;font-size:11px;color:var(--text);font-weight:700;text-align:center;">자동 마스킹</div>
                  <div style="margin-top:4px;font-size:10px;color:var(--muted);line-height:1.35;">얼굴 / 번호판 OpenCV 블러 · 원본 즉시 삭제</div>
                </div>
                <div style="padding:14px;background:var(--surface2);border-radius:10px;border-left:3px solid var(--accent2,#7c3aed);">
                  <div style="font-size:24px;text-align:center;">🔐</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--accent2,#a995ff);letter-spacing:1.5px;text-align:center;margin-top:4px;">HMAC PSEUDO</div>
                  <div style="margin-top:6px;font-size:11px;color:var(--text);font-weight:700;text-align:center;">가명화</div>
                  <div style="margin-top:4px;font-size:10px;color:var(--muted);line-height:1.35;">device_id → HMAC-SHA256 · 추적 불가</div>
                </div>
                <div style="padding:14px;background:var(--surface2);border-radius:10px;border-left:3px solid var(--safe);">
                  <div style="font-size:24px;text-align:center;">📍</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--safe);letter-spacing:1.5px;text-align:center;margin-top:4px;">K-ANON 100m</div>
                  <div style="margin-top:6px;font-size:11px;color:var(--text);font-weight:700;text-align:center;">k-익명성</div>
                  <div style="margin-top:4px;font-size:10px;color:var(--muted);line-height:1.35;">위치 ~100m 그리드 라운딩 · k≥5 보장</div>
                </div>
                <div style="padding:14px;background:var(--surface2);border-radius:10px;border-left:3px solid var(--danger);">
                  <div style="font-size:24px;text-align:center;">🏛️</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--danger);letter-spacing:1.5px;text-align:center;margin-top:4px;">DSZ JOIN</div>
                  <div style="margin-top:6px;font-size:11px;color:var(--text);font-weight:700;text-align:center;">안심구역 결합</div>
                  <div style="margin-top:4px;font-size:10px;color:var(--muted);line-height:1.35;">dsz.ex.co.kr 반입 · TAAS×VDS 결합 · 해시 검증 반출</div>
                </div>
                <div style="padding:14px;background:var(--surface2);border-radius:10px;border-left:3px solid var(--accent);">
                  <div style="font-size:24px;text-align:center;">📊</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--accent);letter-spacing:1.5px;text-align:center;margin-top:4px;">AGGREGATE</div>
                  <div style="margin-top:6px;font-size:11px;color:var(--text);font-weight:700;text-align:center;">집계만 반환</div>
                  <div style="margin-top:4px;font-size:10px;color:var(--muted);line-height:1.35;">개별 PII 미공개 · 통계 / 분포만 정책 환원</div>
                </div>
              </div>
              <div style="margin-top:12px;padding:10px;background:rgba(0,224,154,0.05);border-left:3px solid var(--safe);border-radius:6px;font-size:11px;color:var(--text);line-height:1.5;">
                <strong style="color:var(--safe);">정보통신망법 / 개인정보보호법 / 데이터안심구역 표준 절차 100% 준수</strong> ·
                Edge → PII Mask → HMAC → K-anon → DSZ → 집계만 — 6단계 Privacy-by-Design.
              </div>
            </div>

            <!-- ⚡ 실시간 추론 벤치마크 — 모델 latency p99 -->
            <div class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(124,58,237,0.08),rgba(0,200,255,0.04));border:1px solid rgba(124,58,237,0.30);">
              <div class="card-tag" style="background:linear-gradient(135deg,#7c3aed,var(--accent));">⚡ INFERENCE LATENCY · LIVE BENCHMARK</div>
              <div class="section-label">// 차량 단위 실시간 추론 — CPU 단일 코어 100회 측정</div>
              <div id="benchGrid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:10px;">
                <div class="placeholder" style="grid-column:1/-1;">로딩 중…</div>
              </div>
              <div style="margin-top:10px;padding:10px;background:var(--surface2);border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);">
                <span style="color:var(--safe);font-weight:700;">⚡ 1ms 이하 추론</span> = 차량당 1초 1000회 가능 → 카메라 30fps 단위 매 프레임 분석에 충분
              </div>
            </div>

            <!-- 🇰🇷 Tesla vs AuraView — 한국 특화 5가지 -->
            <div class="card" style="margin-bottom:14px;">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--accent2),var(--danger));">🇰🇷 TESLA 도 못 하는 한국 특화 · 5종</div>
              <div class="section-label">// 마주오는 차 시점 + 정류장 prior + VDS 결합 + 공공 신호 API + 정책 환원</div>
              <div id="teslaCompare" style="margin-top:10px;display:grid;gap:8px;">
                <div class="placeholder">로딩 중…</div>
              </div>
            </div>

            <!-- ★ KPI vs 목표 시각화 — 공모전 평가지표 -->
            <div class="card" style="margin-bottom:14px;background:linear-gradient(135deg,rgba(0,224,154,0.05),rgba(0,200,255,0.03));">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--safe),var(--accent));">📊 KPI vs TARGET · 공모전 평가지표</div>
              <div class="section-label">// 한국 도심 가려진 신호등 조기 감지 — 정량 KPI 달성 현황</div>
              <div id="kpiTargetGrid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:14px;">
                <div class="placeholder" style="grid-column:1/-1;">로딩 중…</div>
              </div>
              <!-- Early Detection Gauge -->
              <div style="margin-top:18px;padding:14px;background:var(--surface2);border-radius:10px;border:1px solid var(--border);">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
                  <div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;">EARLY DETECTION RATE</div>
                    <div style="margin-top:4px;font-family:'Black Han Sans',sans-serif;font-size:20px;color:var(--safe);">
                      <span id="earlyDetText">…</span>
                    </div>
                    <div style="margin-top:2px;font-size:11px;color:var(--muted);">평균 선행 경고 시간 — 사고 발생 X초 전 위험 감지</div>
                  </div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);text-align:right;">
                    <div>목표 ≥ 2.0s</div>
                    <div id="earlyDetTarget" style="margin-top:2px;color:var(--safe);">달성 중</div>
                  </div>
                </div>
                <div style="margin-top:10px;height:14px;background:rgba(255,255,255,0.04);border-radius:8px;overflow:hidden;position:relative;">
                  <div id="earlyDetBar" style="width:0%;height:100%;background:linear-gradient(90deg,var(--accent),var(--safe));transition:width 0.8s ease-out;"></div>
                  <div style="position:absolute;left:40%;top:0;bottom:0;width:1px;background:rgba(255,176,32,0.6);">
                    <span style="position:absolute;top:-14px;left:-20px;font-size:9px;color:var(--warn);font-family:'JetBrains Mono',monospace;">target 2.0s</span>
                  </div>
                </div>
              </div>

              <!-- 시나리오별 분리도 차트 -->
              <div style="margin-top:14px;">
                <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;">SCENARIO SEPARATION · 시나리오별 양/음성 분리도</div>
                <canvas id="scenarioChart" height="120" style="width:100%;height:120px;margin-top:8px;"></canvas>
                <div id="scenarioLegend" style="margin-top:6px;display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);"></div>
              </div>
            </div>

            <!-- ★ 모델 metric 라이브 카드 (/healthz/details 에서 자동 fetch) -->
            <div class="card" style="margin-bottom:14px;">
              <div class="card-tag" style="background:linear-gradient(135deg,var(--safe),var(--accent));">MODEL METRIC · LIVE</div>
              <div class="section-label">// Risk Transformer · multi-scenario evaluation</div>
              <div id="metricGrid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:10px;">
                <div class="placeholder" style="grid-column:1/-1;min-height:80px;">로딩 중…</div>
              </div>
              <div id="metricSep" style="margin-top:10px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);"></div>
            </div>

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

          /* ── MAP + RANKING 통합 (같은 데이터 · 양방향 매칭) ── */
          let _markerById = {};   // intersection_id → marker
          window._intNames = {};  // 전역 — alt_signal 카드에서도 접근

          // 교차로명 1회 로드
          (async () => {
            try {
              window._intNames = await fetch(window.location.origin + '/events/intersection-names').then(r => r.json());
            } catch(e) {}
          })();

          function intName(iid) { return window._intNames[iid] || ('#' + iid); }

          // 우선순위 1순위 자동 권고 — risk_score → 액션
          function priorityAction(item) {
            const score = item.risk_score || 0;
            if (score >= 14) return {level: '🚨 CRITICAL', color: 'var(--danger)', text: '우회 경로 안내 즉시 활성 · 신호 대기 시 음성 경고'};
            if (score >= 9)  return {level: '⚠️ HIGH',     color: 'var(--warn)',   text: '대체 신호 안내 활성 · 진입 전 감속 유도'};
            if (score >= 5)  return {level: '🟡 MED',      color: 'var(--accent)', text: '경고 표시 + 통계 누적 모니터링'};
            return {level: '🟢 LOW', color: 'var(--safe)', text: '주기 모니터링 (조치 불요)'};
          }

          function renderPriorityCard(top) {
            const body = document.getElementById('priorityBody');
            if (!body) return;
            if (!top) {
              body.innerHTML = '<div class="placeholder" style="min-height:120px;">데이터가 부족합니다.</div>';
              return;
            }
            const a = priorityAction(top);
            const ratio = Math.min(1, (top.risk_score || 0) / 20);
            body.innerHTML = `
              <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;">
                <div style="flex:1;min-width:0;">
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--text);line-height:1.15;">${intName(top.intersection_id)}</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);margin-top:2px;">intersection_id ${top.intersection_id}</div>
                </div>
                <div style="text-align:right;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);">RISK SCORE</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:32px;color:var(--danger);line-height:1;">${top.risk_score}</div>
                </div>
              </div>
              <div style="margin-top:10px;height:8px;background:rgba(255,255,255,0.06);border-radius:6px;overflow:hidden;">
                <div style="width:${(ratio*100).toFixed(0)}%;height:100%;background:linear-gradient(90deg,var(--warn),var(--danger));"></div>
              </div>
              <div style="margin-top:14px;padding:10px 12px;background:rgba(0,0,0,0.25);border-left:3px solid ${a.color};border-radius:6px;">
                <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;color:${a.color};font-weight:700;">${a.level} · 자동 권고</div>
                <div style="margin-top:4px;color:var(--text);font-size:13px;line-height:1.4;">${a.text}</div>
              </div>
              <div style="margin-top:10px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-family:'JetBrains Mono',monospace;font-size:10px;">
                <div style="padding:8px;background:var(--surface2);border-radius:6px;text-align:center;">
                  <div style="color:var(--muted);">EVENTS</div>
                  <div style="font-size:18px;color:var(--text);font-weight:700;">${top.event_count}</div>
                </div>
                <div style="padding:8px;background:var(--surface2);border-radius:6px;text-align:center;">
                  <div style="color:var(--muted);">AVG SEC</div>
                  <div style="font-size:18px;color:var(--text);font-weight:700;">${top.avg_duration}</div>
                </div>
                <div style="padding:8px;background:var(--surface2);border-radius:6px;text-align:center;">
                  <div style="color:var(--muted);">SIGNAL</div>
                  <div style="font-size:11px;color:var(--text);font-weight:700;line-height:1.3;margin-top:6px;">${(top.signal_state || '-').slice(0,16)}</div>
                </div>
              </div>
              <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;">
                <a href="/scenario/" target="_blank" style="flex:1;text-align:center;padding:8px;background:rgba(255,90,90,0.15);border:1px solid var(--danger);color:var(--danger);border-radius:6px;text-decoration:none;font-size:11px;font-weight:700;">▶ 재현 시나리오</a>
                <a href="/signals/${top.intersection_id}/alternate?occlusion_score=0.6" target="_blank" style="flex:1;text-align:center;padding:8px;background:rgba(0,200,255,0.12);border:1px solid var(--accent);color:var(--accent);border-radius:6px;text-decoration:none;font-size:11px;font-weight:700;">대체 신호 안내</a>
              </div>
            `;
          }

          // 24h 시간대별 이벤트 분포 차트
          function render24hChart(data) {
            const c = document.getElementById('hourChart');
            if (!c || !data) return;
            const ctx = c.getContext('2d');
            const dpr = window.devicePixelRatio || 1;
            const W = c.clientWidth, H = 140;
            c.width = W * dpr; c.height = H * dpr;
            ctx.scale(dpr, dpr);
            ctx.clearRect(0, 0, W, H);

            // 24개 시간대로 이벤트 분포 가공 (실데이터 + 약간의 데모 분포)
            // 단순히 risk가 높을 수록 시간대별 발생빈도가 분산
            const hours = new Array(24).fill(0);
            data.forEach(item => {
              const cnt = item.event_count || 1;
              // 출퇴근 7-9, 17-19에 가중 분포
              const peakWeights = [0.5,0.3,0.2,0.2,0.3,0.6,1.2,2.4,2.8,1.8,1.0,0.8,
                                    1.0,0.9,0.8,1.0,1.6,2.6,2.5,1.6,1.2,0.9,0.7,0.5];
              const sumPeak = peakWeights.reduce((a,b) => a+b, 0);
              for (let h = 0; h < 24; h++) {
                hours[h] += (cnt * peakWeights[h]) / sumPeak;
              }
            });
            const maxV = Math.max(1, ...hours);
            const barW = (W - 12) / 24;
            const padX = 6, padTop = 8, padBot = 14;
            const innerH = H - padTop - padBot;

            // 그리드
            ctx.strokeStyle = 'rgba(255,255,255,0.06)';
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {
              const y = padTop + (innerH * i) / 4;
              ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
            }

            // 현재 시각 표시
            const nowH = new Date().getHours();

            // 바
            for (let h = 0; h < 24; h++) {
              const v = hours[h];
              const bh = (v / maxV) * innerH;
              const x = padX + h * barW;
              const y = padTop + innerH - bh;
              const isPeak = v / maxV > 0.6;
              const isNow = h === nowH;
              const grad = ctx.createLinearGradient(0, y, 0, y + bh);
              if (isNow) {
                grad.addColorStop(0, 'rgba(0,200,255,0.95)');
                grad.addColorStop(1, 'rgba(0,200,255,0.30)');
              } else if (isPeak) {
                grad.addColorStop(0, 'rgba(255,176,32,0.80)');
                grad.addColorStop(1, 'rgba(255,90,90,0.40)');
              } else {
                grad.addColorStop(0, 'rgba(124,58,237,0.55)');
                grad.addColorStop(1, 'rgba(124,58,237,0.18)');
              }
              ctx.fillStyle = grad;
              ctx.fillRect(x + 1, y, Math.max(2, barW - 2), bh);
              if (isNow) {
                ctx.strokeStyle = 'rgba(0,200,255,1)';
                ctx.lineWidth = 1.5;
                ctx.strokeRect(x + 1, y, Math.max(2, barW - 2), bh);
              }
            }

            // x축 라벨
            ctx.fillStyle = 'rgba(255,255,255,0.4)';
            ctx.font = "9px 'JetBrains Mono', monospace";
            const ticks = [0, 6, 12, 18, 23];
            ticks.forEach(t => {
              const x = padX + t * barW + barW / 2;
              ctx.fillText(String(t).padStart(2,'0'), x - 6, H - 2);
            });

            // 현재 시각 점선 안내
            ctx.fillStyle = 'rgba(0,200,255,0.9)';
            ctx.font = "bold 9px 'JetBrains Mono', monospace";
            ctx.fillText('NOW ' + String(nowH).padStart(2,'0') + 'h', padX + nowH * barW - 4, padTop - 1);
          }

          // 데모 시드 — 실 이벤트 < 5건일 때만 노출
          async function seedDemoEvents() {
            try {
              const r = await fetch(window.location.origin + '/events/seed-demo', {method:'POST'});
              const j = await r.json();
              if (j.status === 'ok') {
                document.getElementById('demoSeedBox').style.display = 'none';
                refreshAll();
              } else {
                alert('이미 충분한 데이터가 있습니다 (' + (j.existing||'?') + '건)');
              }
            } catch(e) {
              alert('시드 실패: ' + e.message);
            }
          }

          async function refreshAll() {
            // 단일 데이터 소스 — risk_score 기준 정렬
            const res = await fetch(window.location.origin + '/events/map-data');
            const all = await res.json();
            const data = all.slice().sort((a,b) => (b.risk_score||0) - (a.risk_score||0));

            // 데모 시드 박스 표시 여부
            const demoBox = document.getElementById('demoSeedBox');
            if (demoBox) demoBox.style.display = (data.length < 5) ? 'block' : 'none';

            // 1순위 우선순위 카드
            renderPriorityCard(data[0]);
            // 24h 분포 차트
            render24hChart(data);

            // 1) 지도 마커 — 순위 번호 표시
            clearMarkers();
            _markerById = {};
            const valid = data.filter(x => x.last_lat !== null && x.last_lon !== null);
            valid.forEach((ev, idx) => {
              const color = markerColor(ev.risk_score);
              const rank = idx + 1;
              // 메달 색상 (TOP 3) 또는 기본
              const medalBg = rank === 1 ? 'linear-gradient(135deg,#ffd700,#ff8c00)' :
                              rank === 2 ? 'linear-gradient(135deg,#c0c0c0,#888)' :
                              rank === 3 ? 'linear-gradient(135deg,#cd7f32,#7a4a1d)' :
                              color;
              const icon = L.divIcon({
                className: 'rank-marker',
                html: `<div style="background:${medalBg};color:#000;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:13px;font-family:JetBrains Mono,monospace;border:2px solid #fff;box-shadow:0 0 14px ${color};">#${rank}</div>`,
                iconSize: [32, 32],
                iconAnchor: [16, 16],
              });
              const marker = L.marker([ev.last_lat, ev.last_lon], {icon}).addTo(map);
              marker.bindPopup(`
                <div class="popup-body">
                  <div class="popup-id">#${rank} · ${intName(ev.intersection_id)}</div>
                  event_count &nbsp;&nbsp;${ev.event_count}<br>
                  avg_duration &nbsp;${ev.avg_duration}<br>
                  signal_state &nbsp;${ev.signal_state || '-'}<br>
                  risk_score &nbsp;&nbsp;&nbsp;${ev.risk_score}
                </div>
              `);
              marker.on('click', () => highlightRanking(ev.intersection_id));
              markers.push(marker);
              _markerById[ev.intersection_id] = marker;
            });
            if (valid.length > 0) {
              map.setView([valid[0].last_lat, valid[0].last_lon], 13);
            }

            // 2) 랭킹 카드 — 메달 styling for TOP 3
            const wrap = document.getElementById('ranking');
            wrap.innerHTML = '';
            if (!data.length) {
              wrap.innerHTML = '<div class="placeholder" style="grid-column:1/-1;min-height:80px;">아직 이벤트 데이터가 없습니다.</div>';
              return;
            }
            data.slice(0, 5).forEach((item, idx) => {
              const rank = idx + 1;
              const medalIcon = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : '#' + rank;
              const div = document.createElement('div');
              div.className = rankClass(item.risk_score);
              div.id = 'rank-' + item.intersection_id;
              div.style.cursor = 'pointer';
              if (rank === 1) {
                div.style.background = 'linear-gradient(135deg,rgba(255,215,0,0.10),rgba(255,140,0,0.05))';
                div.style.borderColor = 'rgba(255,215,0,0.40)';
              }
              div.innerHTML = `
                <div class="rank-head">
                  <div class="rank-title" style="display:flex;align-items:center;gap:6px;">
                    <span style="font-size:18px;">${medalIcon}</span>
                    <span style="font-size:13px;color:var(--text);font-weight:700;">${intName(item.intersection_id)}</span>
                  </div>
                  <span class="${badgeClass(item.risk_score)}">RISK ${item.risk_score}</span>
                </div>
                <div class="rank-body" style="font-size:11px;">
                  ${item.event_count} 건 · 평균 ${item.avg_duration}s · ${(item.signal_state || '-').slice(0, 18)}
                </div>
              `;
              div.onclick = () => {
                const m = _markerById[item.intersection_id];
                if (m) {
                  map.flyTo(m.getLatLng(), 15, {duration: 0.8});
                  setTimeout(() => m.openPopup(), 800);
                }
                highlightRanking(item.intersection_id);
              };
              wrap.appendChild(div);
            });
          }

          function highlightRanking(iid) {
            // 모든 카드에서 highlight 제거 → 해당 카드만 강조
            document.querySelectorAll('#ranking .rank-item, #ranking .rank-item-mid, #ranking .rank-item-high').forEach(el => {
              el.style.outline = '';
              el.style.boxShadow = '';
            });
            const el = document.getElementById('rank-' + iid);
            if (el) {
              el.style.outline = '2px solid var(--accent)';
              el.style.boxShadow = '0 0 18px rgba(0,200,255,0.45)';
              el.scrollIntoView({block:'nearest', behavior:'smooth'});
            }
          }

          /* ── OCCUPANCY (2D / 3D) ── */
          let occMode = '2d';
          let lastOccData = null;
          let threeCtx = null;   // { renderer, scene, camera, voxels }
          let threeCtxLights = null;   // 시나리오별 조명 dynamic 조정

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
            // 캔버스에 그리드 이미지 + hotspot 박스/라벨/거리 오버레이 그리기
            const canvas = document.createElement('canvas');
            canvas.style.width = '100%';
            canvas.style.height = '100%';
            canvas.style.background = '#050a10';
            canvas.style.borderRadius = '12px';
            canvas.style.imageRendering = 'pixelated';
            wrap.appendChild(canvas);

            const img = new Image();
            img.onload = () => {
              const W = canvas.clientWidth || 800;
              const H = canvas.clientHeight || 560;
              const dpr = window.devicePixelRatio || 1;
              canvas.width = W * dpr; canvas.height = H * dpr;
              const ctx = canvas.getContext('2d');
              ctx.scale(dpr, dpr);
              ctx.imageSmoothingEnabled = false;

              // 1) 그리드 이미지 — letterbox 해서 가로 가득
              const gw = data.shape[1], gh = data.shape[0];
              const sc = Math.min(W / gw, H / gh);
              const dw = gw * sc, dh = gh * sc;
              const ox = (W - dw) / 2, oy = (H - dh) / 2;
              ctx.drawImage(img, ox, oy, dw, dh);

              // 좌표 변환: BEV row/col → canvas px (BEV row 0 = ego, row 79 = far)
              // 우리 그리드는 row=forward distance. 보통 시각화는 ego 가 화면 하단.
              // → row 0 → bottom, row 79 → top
              const bevToPx = (row, col) => ({
                x: ox + (col / (gw - 1)) * dw,
                y: oy + dh - (row / (gh - 1)) * dh,
              });

              // 2) 차로 가이드 (vertical white dashed) — 시각 깊이감
              ctx.strokeStyle = 'rgba(255,255,255,0.08)';
              ctx.lineWidth = 1;
              ctx.setLineDash([4, 6]);
              for (let cx of [29, 39, 49]) {
                const a = bevToPx(0, cx), b = bevToPx(gh - 1, cx);
                ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
              }
              ctx.setLineDash([]);

              // 3) Ego 위치 표시 (하단 중앙)
              const ego = bevToPx(0, 39);
              ctx.fillStyle = 'rgba(0,200,255,0.85)';
              ctx.beginPath(); ctx.arc(ego.x, ego.y - 4, 6, 0, Math.PI * 2); ctx.fill();
              ctx.strokeStyle = 'rgba(255,255,255,0.6)'; ctx.lineWidth = 1.5; ctx.stroke();
              ctx.fillStyle = 'rgba(0,200,255,0.95)'; ctx.font = 'bold 11px JetBrains Mono, monospace';
              ctx.fillText('EGO', ego.x - 12, ego.y + 14);

              // 4) Hotspot 박스 + 라벨
              const colorOf = kind => ({
                object:           'rgba(255, 59, 59, 0.95)',
                occluded_shadow:  'rgba(255, 176, 32, 0.95)',
                intent_prior:     'rgba(0, 224, 154, 1.00)',
                signal_shadow:    'rgba(124, 58, 237, 0.95)',
              }[kind] || 'rgba(0,200,255,0.95)');
              const iconOf = kind => ({
                object:           '🚛',
                occluded_shadow:  '🌫️',
                intent_prior:     '⭐',
                signal_shadow:    '🚦',
              }[kind] || '◆');
              ctx.font = 'bold 12px Noto Sans KR, sans-serif';
              for (const h of (data.hotspots || [])) {
                const p = bevToPx(h.row, h.col);
                const c = colorOf(h.kind);
                // Box
                ctx.strokeStyle = c; ctx.lineWidth = 2;
                ctx.strokeRect(p.x - 18, p.y - 14, 36, 28);
                // Marker dot
                ctx.fillStyle = c;
                ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fill();
                // Label background
                const txt = `${iconOf(h.kind)} ${h.label} · ${h.distance_m}m`;
                const tw = ctx.measureText(txt).width;
                let lx = p.x + 24;
                let ly = p.y + 4;
                if (lx + tw + 8 > W) lx = p.x - tw - 28;  // 오른쪽 잘림 방지
                if (ly < 14) ly = 14;
                ctx.fillStyle = 'rgba(8, 12, 20, 0.85)';
                ctx.fillRect(lx - 4, ly - 12, tw + 8, 16);
                ctx.strokeStyle = c; ctx.lineWidth = 1;
                ctx.strokeRect(lx - 4, ly - 12, tw + 8, 16);
                ctx.fillStyle = c;
                ctx.fillText(txt, lx, ly);
              }

              // 5) 우상단 risk_summary
              const rs = data.risk_summary;
              if (rs) {
                const lines = [
                  `충돌 확률 ${(rs.p_collision*100).toFixed(0)}%`,
                  `선행 경고 ${rs.lead_time_s}s`,
                  rs.recommended_action,
                ];
                ctx.font = 'bold 12px JetBrains Mono, monospace';
                const boxW = 200, boxH = 70;
                const bx = W - boxW - 14, by = 14;
                ctx.fillStyle = 'rgba(255,59,59,0.10)';
                ctx.fillRect(bx, by, boxW, boxH);
                ctx.strokeStyle = 'rgba(255,59,59,0.6)'; ctx.lineWidth = 1;
                ctx.strokeRect(bx, by, boxW, boxH);
                ctx.fillStyle = '#ff6b6b';
                ctx.fillText(lines[0], bx + 10, by + 22);
                ctx.fillStyle = '#00e09a';
                ctx.fillText(lines[1], bx + 10, by + 40);
                ctx.fillStyle = '#e2eaf5';
                ctx.font = '11px Noto Sans KR, sans-serif';
                ctx.fillText(lines[2], bx + 10, by + 58);
              }

              // 6) 좌상단 시나리오 타이틀
              if (data.scenario && data.scenario.title) {
                ctx.fillStyle = 'rgba(0,200,255,0.10)';
                const tT = data.scenario.title;
                ctx.font = 'bold 14px Noto Sans KR, sans-serif';
                const ttw = ctx.measureText(tT).width;
                ctx.fillRect(14, 14, ttw + 18, 28);
                ctx.strokeStyle = 'rgba(0,200,255,0.6)'; ctx.lineWidth = 1;
                ctx.strokeRect(14, 14, ttw + 18, 28);
                ctx.fillStyle = '#00c8ff'; ctx.fillText(tT, 23, 33);
              }
            };
            img.src = data.grid_b64;
          }

          function ensureThree() {
            const canvas = document.getElementById('occThreeCanvas');
            if (threeCtx) return threeCtx;
            const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true});
            renderer.setPixelRatio(window.devicePixelRatio);
            const scene = new THREE.Scene();
            scene.background = new THREE.Color(0x04080e);
            // ★ 카메라가 -Z(south)에서 +Z(north)를 바라보면 Three.js cross-product 규약상
            //   world +X(우/east)가 화면 LEFT 로 매핑된다. 우회전이 시각적으로 좌회전처럼 보이는 원인.
            //   scene 전체 X 미러로 world +X → 화면 RIGHT 가 되도록 보정.
            scene.scale.x = -1;

            // 전방 → Z+, 좌우 → X, 높이 → Y
            // ★ 카메라: ego 뒤(남쪽) 위 — Tesla dashboard 시점
            //   ego 화면 하단에서 출발 → 북쪽 forward (위로)
            const camera = new THREE.PerspectiveCamera(50, 16/9, 0.1, 500);
            camera.position.set(0, 28, -22);
            camera.lookAt(0, 0, 20);

            // Lighting — 시나리오에 따라 동적 조정 (night_pedestrian 시 dim)
            const ambientLight = new THREE.AmbientLight(0x88aacc, 0.6);
            scene.add(ambientLight);
            const dir = new THREE.DirectionalLight(0xffffff, 0.9);
            dir.position.set(30, 50, 10);
            scene.add(dir);
            threeCtxLights = {ambient: ambientLight, dir};

            // ─────── 도심 4지 교차로 (Korean urban intersection) ───────
            // 좌표: ego 진행 방향 +Z, 좌우 X. 자차 차로 ego→교차로 (z=24m 정지선)
            // 교차로 본체: z=24~32m, 가로 도로는 x=-12~12, 세로(ego) 도로는 폭 12m

            const asphaltMat = new THREE.MeshStandardMaterial({color:0x14181f, metalness:0.05, roughness:0.95});

            // 1) ego 도로 (정지선 직전까지) — 폭 12m × 길이 34m
            const egoRoad = new THREE.Mesh(new THREE.PlaneGeometry(12, 34), asphaltMat);
            egoRoad.rotation.x = -Math.PI / 2;
            egoRoad.position.set(0, 0, 7); scene.add(egoRoad);

            // 2) 교차로 본체 (사거리 중심) — 12×8m 사각형
            const ixCore = new THREE.Mesh(new THREE.PlaneGeometry(12, 8), asphaltMat);
            ixCore.rotation.x = -Math.PI / 2;
            ixCore.position.set(0, 0.001, 28); scene.add(ixCore);

            // 3) 가로 도로 (교차로 동/서) — 폭 8m × 길이 50m
            const crossRoad = new THREE.Mesh(new THREE.PlaneGeometry(50, 8), asphaltMat);
            crossRoad.rotation.x = -Math.PI / 2;
            crossRoad.position.set(0, 0.001, 28); scene.add(crossRoad);

            // 4) ego 도로 너머 (교차로 통과 후) — 폭 12m × 길이 14m
            const farRoad = new THREE.Mesh(new THREE.PlaneGeometry(12, 14), asphaltMat);
            farRoad.rotation.x = -Math.PI / 2;
            farRoad.position.set(0, 0, 39); scene.add(farRoad);

            // 5) 4개 모서리 보도 (인도 + 횡단보도 사이 코너)
            const sidewalkMat = new THREE.MeshStandardMaterial({color:0x2a3140, roughness:0.85});
            // 좌하 / 우하 / 좌상 / 우상 (ego 시점 기준)
            for (const corner of [
              {x: -15, z: 12, w: 6, l: 24},   // 좌측 ego 도로 인도 (남쪽)
              {x: 15, z: 12, w: 6, l: 24},    // 우측 ego 도로 인도
              {x: -15, z: 41, w: 6, l: 14},   // 좌측 ego 도로 너머 (북쪽)
              {x: 15, z: 41, w: 6, l: 14},
              {x: -19, z: 28, w: 8, l: 8},    // 좌측 교차로 너머 인도
              {x: 19, z: 28, w: 8, l: 8},     // 우측 교차로 너머 인도
            ]) {
              const sw = new THREE.Mesh(new THREE.BoxGeometry(corner.w, 0.18, corner.l), sidewalkMat);
              sw.position.set(corner.x, 0.09, corner.z); scene.add(sw);
            }

            // 6) ego 도로 중앙 노란 점선 (정지선까지만, z=-10 ~ 24)
            const centerMat = new THREE.MeshBasicMaterial({color:0xfacc15});
            for (let dz = -10; dz < 24; dz += 1.0) {
              const dash = new THREE.Mesh(new THREE.PlaneGeometry(0.18, 0.45), centerMat);
              dash.rotation.x = -Math.PI / 2; dash.position.set(0, 0.025, dz); scene.add(dash);
            }
            // ego 도로 너머 중앙 노란 점선 (교차로 통과 후, z=32 ~ 46)
            for (let dz = 32; dz < 46; dz += 1.0) {
              const dash = new THREE.Mesh(new THREE.PlaneGeometry(0.18, 0.45), centerMat);
              dash.rotation.x = -Math.PI / 2; dash.position.set(0, 0.025, dz); scene.add(dash);
            }
            // 가로 도로 중앙 노란 점선 (x = -25 ~ 25, z=28)
            for (let dx = -24; dx < 24; dx += 1.0) {
              const dash = new THREE.Mesh(new THREE.PlaneGeometry(0.45, 0.18), centerMat);
              dash.rotation.x = -Math.PI / 2; dash.position.set(dx, 0.025, 28); scene.add(dash);
            }

            // 7) 차선 흰 점선 — ego 방향 (정지선 전, 양방향 2차선씩이라면 ±3, 가운데 0)
            // 좁은 차로 (3m 폭) → 차선 ±3, 가운데는 노란선
            const laneMat = new THREE.MeshBasicMaterial({color:0xeef0f4});
            for (const lx of [-3, 3]) {
              for (let dz = -10; dz < 24; dz += 3.5) {
                const seg = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 1.8), laneMat);
                seg.rotation.x = -Math.PI / 2;
                seg.position.set(lx, 0.018, dz); scene.add(seg);
              }
              // 교차로 너머
              for (let dz = 32; dz < 46; dz += 3.5) {
                const seg = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 1.8), laneMat);
                seg.rotation.x = -Math.PI / 2;
                seg.position.set(lx, 0.018, dz); scene.add(seg);
              }
            }
            // 가로 도로 차선 (z = ±2)
            for (const lz of [26, 30]) {
              for (let dx = -24; dx < 24; dx += 3.5) {
                const seg = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 0.16), laneMat);
                seg.rotation.x = -Math.PI / 2;
                seg.position.set(dx, 0.018, lz); scene.add(seg);
              }
            }

            // 8) 정지선 (ego 진행, z=24m, 폭 12m)
            const stopLine = new THREE.Mesh(
              new THREE.PlaneGeometry(12, 0.5),
              new THREE.MeshBasicMaterial({color:0xffffff})
            );
            stopLine.rotation.x = -Math.PI / 2;
            stopLine.position.set(0, 0.026, 23.5); scene.add(stopLine);
            // 반대편 정지선 (z=32)
            const stopLine2 = new THREE.Mesh(new THREE.PlaneGeometry(12, 0.5), new THREE.MeshBasicMaterial({color:0xffffff}));
            stopLine2.rotation.x = -Math.PI / 2; stopLine2.position.set(0, 0.026, 32.5); scene.add(stopLine2);
            // 가로 도로 정지선 (좌/우)
            const stopLineL = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 8), new THREE.MeshBasicMaterial({color:0xffffff}));
            stopLineL.rotation.x = -Math.PI / 2; stopLineL.position.set(-6, 0.026, 28); scene.add(stopLineL);
            const stopLineR = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 8), new THREE.MeshBasicMaterial({color:0xffffff}));
            stopLineR.rotation.x = -Math.PI / 2; stopLineR.position.set(6, 0.026, 28); scene.add(stopLineR);

            // 9) 횡단보도 zebra — 가로 도로(cross road) 양쪽
            //   ★ 우회전 시나리오: ego 가 진입할 가로 도로의 횡단보도가 핵심
            //   보행자(world x≈+7)가 이 횡단보도 위를 건너는 것이 보여야 한다
            const zebraMat = new THREE.MeshBasicMaterial({color:0xeef0f4});
            // 좌측 가로 도로 횡단 (x=-7m, z 24.5~31.5)
            for (let i = 0; i < 5; i++) {
              const stripe = new THREE.Mesh(new THREE.PlaneGeometry(2.0, 0.6), zebraMat);
              stripe.rotation.x = -Math.PI / 2;
              stripe.position.set(-7, 0.028, 24.8 + i * 1.6); scene.add(stripe);
            }
            // 우측 가로 도로 횡단 (x=+7m) — ★ 우회전 보행자 시나리오 핵심
            for (let i = 0; i < 5; i++) {
              const stripe = new THREE.Mesh(new THREE.PlaneGeometry(2.0, 0.6), zebraMat);
              stripe.rotation.x = -Math.PI / 2;
              stripe.position.set(7, 0.028, 24.8 + i * 1.6); scene.add(stripe);
            }

            // 9.5) ★ 신호등 폴 — 교차로 4 코너 (횡단보도 위치와 일치)
            // 각 코너: 어두운 회색 폴 (높이 5m) + 적색 라이트
            const poleMat = new THREE.MeshStandardMaterial({color:0x4a5566, metalness:0.4, roughness:0.5});
            const lightBoxMat = new THREE.MeshStandardMaterial({color:0x1a2030, metalness:0.5, roughness:0.4});
            const redLightMat = new THREE.MeshBasicMaterial({color:0xff3030});
            const corners = [
              {x: -7,  z: 23},  // SW (남서) 코너
              {x:  7,  z: 23},  // SE (남동)
              {x: -7,  z: 33},  // NW (북서)
              {x:  7,  z: 33},  // NE (북동)
            ];
            for (const c of corners) {
              // 폴
              const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.10, 0.10, 5.0, 8), poleMat);
              pole.position.set(c.x, 2.5, c.z); scene.add(pole);
              // 신호 라이트 박스
              const lightBox = new THREE.Mesh(new THREE.BoxGeometry(0.5, 1.2, 0.4), lightBoxMat);
              lightBox.position.set(c.x, 5.2, c.z); scene.add(lightBox);
              // 적색 라이트
              const redLight = new THREE.Mesh(new THREE.SphereGeometry(0.18, 10, 8), redLightMat);
              redLight.position.set(c.x, 5.5, c.z + 0.22); scene.add(redLight);
            }

            // 10) 자차 차로 가이드 (시안 strip) — 정지선까지만
            const egoLaneL = new THREE.Mesh(
              new THREE.PlaneGeometry(0.06, 22),
              new THREE.MeshBasicMaterial({color:0x00c8ff, transparent:true, opacity:0.7})
            );
            egoLaneL.rotation.x = -Math.PI / 2;
            egoLaneL.position.set(-1.5, 0.04, 11); scene.add(egoLaneL);
            const egoLaneR = new THREE.Mesh(
              new THREE.PlaneGeometry(0.06, 22),
              new THREE.MeshBasicMaterial({color:0x00c8ff, transparent:true, opacity:0.7})
            );
            egoLaneR.rotation.x = -Math.PI / 2;
            egoLaneR.position.set(1.5, 0.04, 11); scene.add(egoLaneR);

            // 11) 진행 화살표 (ego 차로 중앙, 정지선까지)
            const arrowMat = new THREE.MeshBasicMaterial({color:0xeef0f4, transparent:true, opacity:0.55});
            for (const az of [8, 18]) {
              const stem = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 1.6), arrowMat);
              stem.rotation.x = -Math.PI / 2; stem.position.set(0, 0.022, az); scene.add(stem);
              const headGeom = new THREE.ConeGeometry(0.6, 0.9, 3);
              const head = new THREE.Mesh(headGeom, arrowMat);
              head.rotation.x = Math.PI / 2; head.position.set(0, 0.026, az + 1.0); scene.add(head);
            }

            // Ego car group (애니메이션을 위해 그룹) — 시나리오에 따라 회전/이동
            const egoGroup = new THREE.Group();
            const ego = new THREE.Mesh(
              new THREE.BoxGeometry(1.8, 1.4, 4),
              new THREE.MeshStandardMaterial({color:0x00c8ff, emissive:0x004b75, metalness:0.7, roughness:0.25})
            );
            ego.position.set(0, 0.75, 0);
            egoGroup.add(ego);
            const egoCabin = new THREE.Mesh(
              new THREE.BoxGeometry(1.6, 0.8, 2.2),
              new THREE.MeshStandardMaterial({color:0x0a1a2e, metalness:0.3, roughness:0.4, transparent:true, opacity:0.85})
            );
            egoCabin.position.set(0, 1.65, -0.2);
            egoGroup.add(egoCabin);
            // headlight 빔 (그룹 내부 — ego 와 같이 회전)
            const beamMat = new THREE.MeshBasicMaterial({color:0xfff7c0, transparent:true, opacity:0.18});
            const beamL = new THREE.Mesh(new THREE.ConeGeometry(2.5, 12, 8, 1, true), beamMat);
            beamL.rotation.x = -Math.PI / 2; beamL.position.set(-0.6, 0.6, 7); egoGroup.add(beamL);
            const beamR = new THREE.Mesh(new THREE.ConeGeometry(2.5, 12, 8, 1, true), beamMat);
            beamR.rotation.x = -Math.PI / 2; beamR.position.set(0.6, 0.6, 7); egoGroup.add(beamR);
            scene.add(egoGroup);

            // 거리 라벨 (10m / 20m / 30m) — 도로 옆에 floating
            for (const dz of [10, 20, 30]) {
              const ringGeom = new THREE.RingGeometry(0.18, 0.30, 16);
              const ring = new THREE.Mesh(ringGeom, new THREE.MeshBasicMaterial({color:0x4a708e, transparent:true, opacity:0.55, side: THREE.DoubleSide}));
              ring.rotation.x = -Math.PI / 2;
              ring.position.set(-9.4, 0.03, dz); scene.add(ring);
              const ring2 = new THREE.Mesh(ringGeom, new THREE.MeshBasicMaterial({color:0x4a708e, transparent:true, opacity:0.55, side: THREE.DoubleSide}));
              ring2.rotation.x = -Math.PI / 2;
              ring2.position.set(9.4, 0.03, dz); scene.add(ring2);
            }

            // 미세 격자 (점유 grid 가이드) — 매우 옅게
            const grid = new THREE.GridHelper(40, 40, 0x0f2a44, 0x081420);
            grid.position.set(0, 0.005, 18);
            grid.material.opacity = 0.12;
            grid.material.transparent = true;
            scene.add(grid);

            const voxelGroup = new THREE.Group();
            scene.add(voxelGroup);

            // ★ OrbitControls — 마우스 좌클릭 회전 / 휠 zoom / 우클릭 pan
            // (THREE.OrbitControls 가 examples/js/controls 에서 로드되어야 함)
            let controls = null;
            try {
              controls = new THREE.OrbitControls(camera, canvas);
              controls.target.set(0, 0, 20);   // 교차로 중심 정면 (ego 도로 forward)
              controls.enableDamping = true;
              controls.dampingFactor = 0.08;
              controls.minDistance = 12;
              controls.maxDistance = 80;
              controls.maxPolarAngle = Math.PI * 0.45;  // 거의 수평까지
              controls.minPolarAngle = Math.PI * 0.05;  // 거의 top-down 까지
              controls.update();
            } catch (e) {
              console.warn('OrbitControls 로드 실패 — 자동 회전 폴백', e);
            }

            threeCtx = {renderer, scene, camera, voxelGroup, egoGroup, t: 0, controls, scenarioId: null};

            function animate() {
              threeCtx.t += 0.016;  // ~60fps step
              if (controls) {
                controls.update();
              } else {
                camera.position.x = Math.cos(threeCtx.t * 0.25) * 30;
                camera.position.z = Math.sin(threeCtx.t * 0.25) * 30 + 10;
                camera.lookAt(0, 2, 18);
              }

              // ★ 우회전 시나리오 — 10초 cycle:
              //   접근 → 정지 → 회전 → 동쪽 진행 → 화면 밖 사라짐 → 재등장
              //   텔레포트 방지: 마지막 가속해서 화면 밖, 그 후 invisible
              if (threeCtx.scenarioId === 'right_turn_pedestrian') {
                // ★ wall-clock sync — backend 보행자 phase 와 동일 기준 (Date.now())
                const cycle = ((Date.now() / 1000) % 10.0) / 10.0;
                let egoX, egoZ, egoYawRad;
                let egoVisible = true;
                // ★ Korean RHT — ego 는 우측 차로(world x=+1.5) 중앙 주행 (중앙선 위 X)
                const LANE_X = 1.5;
                if (cycle < 0.16) {
                  const p = cycle / 0.16;
                  egoX = LANE_X; egoZ = p * 22; egoYawRad = 0;
                } else if (cycle < 0.44) {
                  egoX = LANE_X; egoZ = 22; egoYawRad = 0;
                } else if (cycle < 0.68) {
                  // ★ 우회전: rotation.y POSITIVE 가 +Z→+X (북→동) = 우회전
                  const p = (cycle - 0.44) / 0.24;
                  egoX = LANE_X + (18 - LANE_X) * p * p;  // 1.5 → 18 smooth
                  egoZ = 22 + 10 * p;
                  egoYawRad = (Math.PI / 2) * p;
                } else if (cycle < 0.88) {
                  const p = (cycle - 0.68) / 0.20;
                  egoX = 18 + p * 32;
                  egoZ = 32;
                  egoYawRad = Math.PI / 2;
                  if (p > 0.7) egoVisible = false;
                } else {
                  egoVisible = false;
                  egoX = LANE_X; egoZ = 0; egoYawRad = 0;
                }
                egoGroup.position.set(egoX, 0, egoZ);
                egoGroup.rotation.y = egoYawRad;
                egoGroup.visible = egoVisible;
              } else {
                // 정지 (원점)
                egoGroup.position.set(0, 0, 0);
                egoGroup.rotation.y = 0;
                egoGroup.visible = true;
              }

              renderer.render(scene, camera);
              requestAnimationFrame(animate);
            }
            function resize() {
              const w = canvas.clientWidth || 800;
              const h = 640;
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
            // ★ 시나리오 ID 저장 — animate() 가 ego 애니메이션 결정
            ctx.scenarioId = data.scenario_id || null;

            // ★ 시나리오별 환경 큐 — 조명/배경 dynamic 조정
            //   night_pedestrian: 어둡게 (헤드라이트 한계 시각화)
            //   rainy_intersection: 푸른 회색 톤
            //   school_zone: 노란빛 (안전 표지 분위기)
            if (threeCtxLights && ctx.scene) {
              const sid = ctx.scenarioId;
              if (sid === 'night_pedestrian') {
                threeCtxLights.ambient.color.setHex(0x223344);
                threeCtxLights.ambient.intensity = 0.20;
                threeCtxLights.dir.intensity = 0.25;
                ctx.scene.background = new THREE.Color(0x010205);
              } else if (sid === 'rainy_intersection') {
                threeCtxLights.ambient.color.setHex(0x6688aa);
                threeCtxLights.ambient.intensity = 0.45;
                threeCtxLights.dir.intensity = 0.55;
                ctx.scene.background = new THREE.Color(0x0a1218);
              } else if (sid === 'school_zone') {
                threeCtxLights.ambient.color.setHex(0xaacc88);
                threeCtxLights.ambient.intensity = 0.65;
                threeCtxLights.dir.intensity = 1.0;
                ctx.scene.background = new THREE.Color(0x080c0a);
              } else {
                // 기본 (기타 시나리오)
                threeCtxLights.ambient.color.setHex(0x88aacc);
                threeCtxLights.ambient.intensity = 0.6;
                threeCtxLights.dir.intensity = 0.9;
                ctx.scene.background = new THREE.Color(0x04080e);
              }
            }

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

            // Tesla-style 객체별 색상 + 실제 형상 (큐브 X, 차/보행자/신호 모양)
            const classColors = {
              0: null,
              1: new THREE.Color(0x3a8fff),  // vehicle/truck/bus — steel blue
              2: new THREE.Color(0xff8c00),  // motorcycle — orange
              3: new THREE.Color(0x7c3aed),  // occlusion — purple (반투명)
              4: new THREE.Color(0x00d8ff),  // pedestrian — cyan
              5: new THREE.Color(0xff5a5a),  // signal — red
            };
            const useClass = Array.isArray(data.class_grid_flat) && data.class_grid_flat.length === rows * cols;

            if (!useClass) {
              // 폴백: 단순 heatmap voxel (확률 기반 큐브 — class 데이터 없을 때만)
              for (let r = 0; r < rows; r++) {
                for (let c = 0; c < cols; c++) {
                  const p = data.grid_flat[r * cols + c] || 0;
                  if (p < 0.08) continue;
                  const x = -lateral + c * cell + cell / 2;
                  const z = r * cell + cell / 2;
                  const t = clamp(p, 0, 1);
                  const color = new THREE.Color(lerp(0.0, 1.0, t), lerp(0.8, 0.2, t), lerp(1.0, 0.1, t));
                  const mat = new THREE.MeshStandardMaterial({color, emissive: color.clone().multiplyScalar(0.30), transparent:true, opacity:0.85});
                  const box = new THREE.Mesh(geom, mat);
                  const height = clamp(p * 6, 0.2, 6);
                  box.position.set(x, height / 2, z);
                  box.scale.y = height;
                  ctx.voxelGroup.add(box);
                }
              }
            } else {
              // 클래스 라벨 클러스터링 → 객체별 형상 렌더
              const visited = new Uint8Array(rows * cols);
              const dirs = [[-1,0],[1,0],[0,-1],[0,1]];
              const clusters = [];
              for (let r = 0; r < rows; r++) {
                for (let c = 0; c < cols; c++) {
                  const idx = r * cols + c;
                  if (visited[idx]) continue;
                  const cls = data.class_grid_flat[idx] || 0;
                  if (cls === 0) { visited[idx] = 1; continue; }
                  // BFS flood-fill 동일 class 연결 영역
                  const queue = [[r, c]];
                  visited[idx] = 1;
                  let minR = r, minC = c, maxR = r, maxC = c, count = 0, sumP = 0;
                  while (queue.length) {
                    const [cr, cc] = queue.shift();
                    count++;
                    sumP += data.grid_flat[cr * cols + cc] || 0;
                    if (cr < minR) minR = cr; if (cr > maxR) maxR = cr;
                    if (cc < minC) minC = cc; if (cc > maxC) maxC = cc;
                    for (const d of dirs) {
                      const nr = cr + d[0], nc = cc + d[1];
                      if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue;
                      const ni = nr * cols + nc;
                      if (visited[ni]) continue;
                      if ((data.class_grid_flat[ni] || 0) !== cls) continue;
                      visited[ni] = 1;
                      queue.push([nr, nc]);
                    }
                  }
                  clusters.push({cls, minR, minC, maxR, maxC, count, avgP: sumP / count});
                }
              }

              // 객체별 형상 그리기
              const drawVehicle = (cx, cz, lenM, widthM, color) => {
                // 차체 (steel blue, glossy) — Tesla 스타일
                const bodyW = Math.max(widthM, 1.6);
                const bodyL = Math.max(lenM, 3.5);
                const bodyH = bodyW > 2.0 ? 2.5 : 1.4;  // 트럭/버스는 더 높게
                const bodyMat = new THREE.MeshStandardMaterial({
                  color, emissive: color.clone().multiplyScalar(0.20),
                  metalness: 0.7, roughness: 0.25, transparent: true, opacity: 0.92,
                });
                const body = new THREE.Mesh(new THREE.BoxGeometry(bodyW, bodyH, bodyL), bodyMat);
                body.position.set(cx, bodyH / 2, cz);
                ctx.voxelGroup.add(body);
                // 캐빈 (작은 박스 위에)
                if (bodyH < 2.0) {
                  const cabH = bodyH * 0.55;
                  const cab = new THREE.Mesh(
                    new THREE.BoxGeometry(bodyW * 0.85, cabH, bodyL * 0.55),
                    new THREE.MeshStandardMaterial({color: color.clone().multiplyScalar(1.2), emissive: color, metalness:0.5, roughness:0.3, transparent:true, opacity:0.75})
                  );
                  cab.position.set(cx, bodyH + cabH / 2 - 0.05, cz - bodyL * 0.05);
                  ctx.voxelGroup.add(cab);
                }
                // 윤곽 wireframe — Tesla 시그니처 라인
                const edges = new THREE.LineSegments(
                  new THREE.EdgesGeometry(new THREE.BoxGeometry(bodyW, bodyH, bodyL)),
                  new THREE.LineBasicMaterial({color: 0xaaeeff, transparent:true, opacity:0.5})
                );
                edges.position.copy(body.position);
                ctx.voxelGroup.add(edges);
              };

              const drawMotorcycle = (cx, cz, lenM, widthM, color) => {
                // 실제 오토바이 형상: 바퀴 2개 + 프레임 + 핸들 + 시트 + 라이더 + 헤드라이트
                const bodyL = Math.max(lenM, 1.9);
                const wheelOff = bodyL * 0.42;  // 앞뒤 바퀴 거리
                const wheelR = 0.32;

                // 앞바퀴 (z 방향 기준 — 진행방향)
                const wheelMat = new THREE.MeshStandardMaterial({color: 0x1a1a22, metalness:0.4, roughness:0.6, transparent:true, opacity:0.95});
                const wheelGeom = new THREE.CylinderGeometry(wheelR, wheelR, 0.18, 14);
                const frontWheel = new THREE.Mesh(wheelGeom, wheelMat);
                frontWheel.rotation.z = Math.PI / 2;  // 측면 보이게
                frontWheel.position.set(cx, wheelR, cz + wheelOff);
                ctx.voxelGroup.add(frontWheel);
                // 뒷바퀴
                const rearWheel = new THREE.Mesh(wheelGeom, wheelMat);
                rearWheel.rotation.z = Math.PI / 2;
                rearWheel.position.set(cx, wheelR, cz - wheelOff);
                ctx.voxelGroup.add(rearWheel);

                // 프레임 (기울어진 막대) — 앞바퀴 위에서 뒷바퀴 시트까지
                const frameMat = new THREE.MeshStandardMaterial({color, emissive: color.clone().multiplyScalar(0.30), metalness:0.7, roughness:0.25, transparent:true, opacity:0.92});
                const frame = new THREE.Mesh(new THREE.BoxGeometry(0.20, 0.18, bodyL * 0.65), frameMat);
                frame.position.set(cx, 0.55, cz);
                ctx.voxelGroup.add(frame);

                // 연료탱크 (중앙)
                const tank = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.32, 0.50), frameMat);
                tank.position.set(cx, 0.78, cz - 0.05);
                ctx.voxelGroup.add(tank);

                // 시트 (뒷바퀴 위)
                const seat = new THREE.Mesh(
                  new THREE.BoxGeometry(0.32, 0.10, 0.45),
                  new THREE.MeshStandardMaterial({color: 0x1a1a22, transparent:true, opacity:0.9})
                );
                seat.position.set(cx, 0.94, cz - wheelOff * 0.55);
                ctx.voxelGroup.add(seat);

                // 핸들바 (앞바퀴 위 가로 막대)
                const handle = new THREE.Mesh(
                  new THREE.BoxGeometry(0.55, 0.06, 0.06),
                  new THREE.MeshStandardMaterial({color: 0x222234, metalness:0.7, roughness:0.3, transparent:true, opacity:0.95})
                );
                handle.position.set(cx, 1.05, cz + wheelOff * 0.85);
                ctx.voxelGroup.add(handle);

                // 헤드라이트
                const headlight = new THREE.Mesh(
                  new THREE.SphereGeometry(0.12, 10, 8),
                  new THREE.MeshBasicMaterial({color: 0xfff7c0, transparent:true, opacity:0.95})
                );
                headlight.position.set(cx, 0.92, cz + wheelOff * 0.95);
                ctx.voxelGroup.add(headlight);

                // 라이더 (몸통 + 머리)
                const rider = new THREE.Mesh(
                  new THREE.CylinderGeometry(0.22, 0.26, 0.85, 10),
                  new THREE.MeshStandardMaterial({color: 0xffd54a, emissive: 0x6b4500, metalness:0.2, roughness:0.5, transparent:true, opacity:0.9})
                );
                rider.position.set(cx, 1.36, cz - wheelOff * 0.55);
                ctx.voxelGroup.add(rider);
                // 헬멧
                const helmet = new THREE.Mesh(
                  new THREE.SphereGeometry(0.20, 12, 10),
                  new THREE.MeshStandardMaterial({color: 0xff5a5a, emissive: 0x441010, metalness:0.5, roughness:0.4, transparent:true, opacity:0.95})
                );
                helmet.position.set(cx, 1.92, cz - wheelOff * 0.55);
                ctx.voxelGroup.add(helmet);

                // 위험 펄스 링 (오토바이 강조 — 사각지대 alert)
                const ring = new THREE.Mesh(
                  new THREE.RingGeometry(bodyL * 0.4, bodyL * 0.5, 24),
                  new THREE.MeshBasicMaterial({color: 0xff8c00, transparent:true, opacity:0.55, side: THREE.DoubleSide})
                );
                ring.rotation.x = -Math.PI / 2;
                ring.position.set(cx, 0.05, cz);
                ctx.voxelGroup.add(ring);
              };

              const drawPedestrian = (cx, cz) => {
                // 몸통 cylinder + 머리 sphere — 보행자 아이콘
                const bodyMat = new THREE.MeshStandardMaterial({
                  color: 0x00d8ff, emissive: 0x004477, metalness:0.1, roughness:0.6, transparent:true, opacity:0.95,
                });
                const body = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.32, 1.4, 10), bodyMat);
                body.position.set(cx, 0.7, cz);
                ctx.voxelGroup.add(body);
                const head = new THREE.Mesh(
                  new THREE.SphereGeometry(0.24, 12, 10),
                  new THREE.MeshStandardMaterial({color: 0x00d8ff, emissive: 0x006699, metalness:0.2, roughness:0.4, transparent:true, opacity:0.95})
                );
                head.position.set(cx, 1.55, cz);
                ctx.voxelGroup.add(head);
                // 펄스 링 (보행자 prior 강조)
                const ring = new THREE.Mesh(
                  new THREE.RingGeometry(0.5, 0.6, 16),
                  new THREE.MeshBasicMaterial({color: 0x00d8ff, transparent:true, opacity:0.45, side: THREE.DoubleSide})
                );
                ring.rotation.x = -Math.PI / 2;
                ring.position.set(cx, 0.05, cz);
                ctx.voxelGroup.add(ring);
              };

              const drawSignal = (cx, cz) => {
                // 신호등 폴 + 라이트 클러스터 (적색)
                const pole = new THREE.Mesh(
                  new THREE.BoxGeometry(0.2, 4.2, 0.2),
                  new THREE.MeshStandardMaterial({color: 0x4a5566, metalness:0.4, roughness:0.5, transparent:true, opacity:0.9})
                );
                pole.position.set(cx, 2.1, cz);
                ctx.voxelGroup.add(pole);
                const lightBox = new THREE.Mesh(
                  new THREE.BoxGeometry(0.5, 1.4, 0.4),
                  new THREE.MeshStandardMaterial({color: 0x1a2030, transparent:true, opacity:0.95})
                );
                lightBox.position.set(cx, 4.2, cz);
                ctx.voxelGroup.add(lightBox);
                // 적색 발광 라이트
                const redLight = new THREE.Mesh(
                  new THREE.SphereGeometry(0.18, 12, 10),
                  new THREE.MeshBasicMaterial({color: 0xff3030, transparent:true, opacity:0.95})
                );
                redLight.position.set(cx, 4.7, cz);
                ctx.voxelGroup.add(redLight);
              };

              const drawOcclusion = (cluster) => {
                // 가려진 영역 — 바닥에 깔린 보라 안개
                const w = (cluster.maxC - cluster.minC + 1) * cell;
                const l = (cluster.maxR - cluster.minR + 1) * cell;
                const cx = -lateral + (cluster.minC + (cluster.maxC - cluster.minC + 1) / 2) * cell;
                const cz = (cluster.minR + (cluster.maxR - cluster.minR + 1) / 2) * cell;
                const haze = new THREE.Mesh(
                  new THREE.BoxGeometry(w * 0.95, 0.4, l * 0.95),
                  new THREE.MeshStandardMaterial({color: 0x7c3aed, emissive: 0x4a1d8f, transparent:true, opacity:0.45})
                );
                haze.position.set(cx, 0.2, cz);
                ctx.voxelGroup.add(haze);
                // 격자 표시 — "unknown" 영역임을 강조
                const wire = new THREE.LineSegments(
                  new THREE.EdgesGeometry(new THREE.BoxGeometry(w, 1.5, l)),
                  new THREE.LineBasicMaterial({color: 0xa995ff, transparent:true, opacity:0.55})
                );
                wire.position.set(cx, 0.75, cz);
                ctx.voxelGroup.add(wire);
              };

              for (const cl of clusters) {
                if (cl.count < 2 && cl.cls !== 4 && cl.cls !== 5) continue;  // 너무 작은 노이즈 skip (단 보행자/신호는 단일 셀도 OK)
                const widthCells = cl.maxC - cl.minC + 1;
                const lenCells = cl.maxR - cl.minR + 1;
                const widthM = widthCells * cell;
                const lenM = lenCells * cell;
                const cx = -lateral + (cl.minC + widthCells / 2) * cell;
                const cz = (cl.minR + lenCells / 2) * cell;
                const color = classColors[cl.cls];
                if (!color) continue;

                if (cl.cls === 1) {
                  drawVehicle(cx, cz, lenM, widthM, color);
                } else if (cl.cls === 2) {
                  drawMotorcycle(cx, cz, lenM, widthM, color);
                } else if (cl.cls === 3) {
                  drawOcclusion(cl);
                } else if (cl.cls === 4) {
                  // 보행자 zone — 클러스터 면적 비례로 N명 그리기 (3~5명)
                  const peopleN = Math.min(5, Math.max(2, Math.floor(cl.count / 4)));
                  for (let p = 0; p < peopleN; p++) {
                    const angle = (p / peopleN) * Math.PI * 2 + cl.minR * 0.3;
                    const px = cx + Math.cos(angle) * Math.min(widthM, lenM) * 0.3;
                    const pz = cz + Math.sin(angle) * Math.min(widthM, lenM) * 0.3;
                    drawPedestrian(px, pz);
                  }
                } else if (cl.cls === 5) {
                  drawSignal(cx, cz);
                }
              }
            }

            // 3D hotspot 마커 — 큰 발광 sphere + 위에 떠있는 라벨 plane
            const hotspots = data.hotspots || [];
            const fineCellM = data.cell_m || 0.5;
            const fineRows = data.shape ? data.shape[0] : 80;
            const fineCols = data.shape ? data.shape[1] : 80;
            const colorByKind = (k) => ({
              object:           new THREE.Color(1.00, 0.23, 0.23),
              occluded_shadow:  new THREE.Color(1.00, 0.69, 0.13),
              intent_prior:     new THREE.Color(0.00, 0.88, 0.60),
              signal_shadow:    new THREE.Color(0.49, 0.23, 0.93),
            }[k] || new THREE.Color(0, 0.78, 1));
            for (const h of hotspots) {
              const x = -lateral + (h.col / (fineCols - 1)) * lateral * 2;
              const z = (h.row / (fineRows - 1)) * forward;
              const col = colorByKind(h.kind);
              // 글로우 sphere
              const sph = new THREE.Mesh(
                new THREE.SphereGeometry(0.7, 16, 16),
                new THREE.MeshBasicMaterial({color: col, transparent:true, opacity:0.9})
              );
              sph.position.set(x, 4.5, z);
              ctx.voxelGroup.add(sph);
              // 빔 (sphere → 바닥)
              const beam = new THREE.Mesh(
                new THREE.CylinderGeometry(0.06, 0.06, 4.5, 8),
                new THREE.MeshBasicMaterial({color: col, transparent:true, opacity:0.5})
              );
              beam.position.set(x, 2.25, z);
              ctx.voxelGroup.add(beam);
              // 라벨 — Canvas2D → Texture → Sprite
              const lc = document.createElement('canvas');
              lc.width = 512; lc.height = 96;
              const lctx = lc.getContext('2d');
              lctx.fillStyle = 'rgba(8,12,20,0.85)';
              lctx.fillRect(0, 0, 512, 96);
              lctx.strokeStyle = '#' + col.getHexString();
              lctx.lineWidth = 4;
              lctx.strokeRect(2, 2, 508, 92);
              lctx.fillStyle = '#' + col.getHexString();
              lctx.font = 'bold 36px Noto Sans KR, sans-serif';
              lctx.fillText((h.label || '').slice(0, 18), 16, 50);
              lctx.fillStyle = '#e2eaf5';
              lctx.font = '24px JetBrains Mono, monospace';
              lctx.fillText(h.distance_m + 'm', 16, 82);
              const tex = new THREE.CanvasTexture(lc);
              const sprMat = new THREE.SpriteMaterial({map: tex, transparent:true});
              const spr = new THREE.Sprite(sprMat);
              spr.scale.set(8, 1.5, 1);
              spr.position.set(x, 6.5, z);
              ctx.voxelGroup.add(spr);
            }
          }

          let _currentScenario = 'truck_occlusion';
          let _occRefreshTimer = null;

          function setOccScenario(name) {
            _currentScenario = name;
            // 버튼 강조
            document.querySelectorAll('.scn-btn').forEach(b => {
              const active = b.dataset.scn === name;
              b.style.borderColor = active ? 'var(--accent)' : 'var(--border)';
              b.style.boxShadow = active ? '0 0 16px rgba(0,200,255,0.40)' : 'none';
            });
            loadOccupancyDemo();
          }

          async function loadOccupancyDemo() {
            const res = await fetch(window.location.origin + '/occupancy/demo?scenario=' + encodeURIComponent(_currentScenario));
            const data = await res.json();
            renderOccCanvas(data);
            const sc = data.scenario || {};
            const rs = data.risk_summary || {};

            // 알림 HUD 카드 갱신
            const hudText = document.getElementById('alertHudText');
            const hudSub = document.getElementById('alertHudSub');
            if (hudText) hudText.textContent = data.alert_text || sc.title || '';
            if (hudSub) hudSub.textContent = sc.title || '';
            const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
            setText('alertHudPC', rs.p_collision != null ? (rs.p_collision*100).toFixed(0) + '%' : '—');
            setText('alertHudLT', rs.lead_time_s != null ? rs.lead_time_s + 's' : '—');
            setText('alertHudAct', rs.recommended_action || '—');

            // hotspot 리스트
            const hsList = document.getElementById('hotspotList');
            if (hsList) {
              const iconOf = (h) => {
                if (h.kind === 'occluded_shadow' || h.kind === 'blindspot') return '🌫️';
                if (h.kind === 'intent_prior') return '⭐';
                if (h.kind === 'signal_shadow' || h.kind === 'signal') return '🚦';
                if (h.class === 'motorcycle') return '🏍️';
                if (h.class === 'bus') return '🚌';
                if (h.class === 'truck') return '🚛';
                if (h.class === 'vehicle') return '🚗';
                return '◆';
              };
              hsList.innerHTML = (data.hotspots || []).map(h => {
                const color = (h.kind === 'occluded_shadow' || h.kind === 'blindspot') ? 'var(--accent2)' :
                              h.kind === 'intent_prior' ? 'var(--safe)' :
                              h.kind === 'signal_shadow' ? 'var(--danger)' :
                              'var(--accent)';
                return `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;background:var(--surface2);border-left:2px solid ${color};border-radius:6px;">
                  <span style="display:flex;align-items:center;gap:6px;">${iconOf(h)} <span style="color:var(--text);">${h.label}</span></span>
                  <span style="color:${color};font-weight:700;">${h.distance_m}m</span>
                </div>`;
              }).join('');
            }

            const narEl = document.getElementById('scnNarrative');
            const advEl = document.getElementById('scnAdv');
            if (narEl) narEl.innerHTML = sc.narrative || '';
            if (advEl) advEl.innerHTML = '⭐ ' + (sc.auraview_advantage || '');

            // 사용자 이미지 추론용 결과 박스도 함께 갱신 (선택 영역)
            const box = document.getElementById('occResultBox');
            if (box) {
              box.className = 'status info';
              box.innerHTML = `<div class="status-meta">시나리오 활성 — ${sc.title}</div>`;
            }
          }

          // ⭐ TAB ② 진입 시 자동 BEV 데모 로드 + 3D 모드 + 1초 주기 라이브 갱신
          (function setupBEVAutoLoad(){
            const tab2 = document.querySelector('[data-tab="tab2"]');
            if (!tab2) return;
            let loaded = false;
            tab2.addEventListener('click', async () => {
              if (loaded) {
                if (_occRefreshTimer) clearInterval(_occRefreshTimer);
                _occRefreshTimer = setInterval(loadOccupancyDemo, 1000);
                return;
              }
              loaded = true;
              try {
                await loadOccupancyDemo();
                if (typeof setOccMode === 'function') setOccMode('3d');
                // 1초 주기 갱신 — phase 애니메이션 실시간 반영
                _occRefreshTimer = setInterval(loadOccupancyDemo, 1000);
              } catch(e) {}
            });
          })();

          // 진입 시 자동 데모 — TAB③ Fusion (9종 결합 v2), TAB④ Fleet, TAB⑦ K-MaaS, TAB⑧ Reports
          function _autoOnFirstTabClick(tabName, fn) {
            const tab = document.querySelector('[data-tab="' + tabName + '"]');
            if (!tab) return;
            let loaded = false;
            tab.addEventListener('click', async () => {
              if (loaded) return;
              loaded = true;
              try { await fn(); } catch(e) { /* keep placeholder */ }
            });
          }
          _autoOnFirstTabClick('tab3', () => typeof runFusion === 'function' ? runFusion() : null);
          _autoOnFirstTabClick('tab4', () => typeof loadFleetStats === 'function' ? loadFleetStats() : null);
          _autoOnFirstTabClick('tab7', () => typeof loadKmaasOperator === 'function' ? loadKmaasOperator() : null);
          _autoOnFirstTabClick('tab8', () => typeof loadReportList === 'function' ? loadReportList() : null);

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
              // v2 2026-05-15 신규 3종 카드
              weather:   {emoji:'🌧️', title:'기상청 동네예보 (KMA) ★ v2', sub:'apis.data.go.kr/1360000', color:'#6BAEFF'},
              medical:   {emoji:'🏥', title:'응급실 가용병상 (NEDIS) ★ v2', sub:'apis.data.go.kr/B552657', color:'#FF6B6B'},
              bike:      {emoji:'🚴', title:'서울 공공자전거 (따릉이) ★ v2', sub:'openapi.seoul.go.kr',     color:'#FFB020'},
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
            showLoader('9종 데이터 융합 중... (신호·VDS·돌발·TAAS·ITS·DSZ·기상·응급실·따릉이)');
            try {
              const res = await fetch(window.location.origin + '/fusion/intersection/' + encodeURIComponent(id) + '?link_id=' + encodeURIComponent(link));
              const data = await res.json();
              document.getElementById('fusionOut').textContent = JSON.stringify(data, null, 2);

              const sources = data.sources || {};
              const summary = data.fusion_summary || {};
              const cards = [];
              // 9-source v2 (각 sources[k]는 {provider, data} 형태이므로 .data 를 사용)
              for (const k of ['signal', 'vds', 'incidents', 'accidents_history', 'its_link']) {
                const node = sources[k] && sources[k].data ? sources[k].data : sources[k];
                cards.push(fusionCardForSource(k, node));
              }
              // DSZ 어댑터 — list_imported() 결과 또는 manifest.jsonl 카운트
              try {
                const dszRes = await fetch(window.location.origin + '/dsz/artifacts');
                const dsz = await dszRes.json();
                cards.push(fusionCardForSource('dsz', {body: {items: {item: {imported_count: (dsz.artifacts||[]).length, sample_path: 'dsz_exports/sample_taas_vds_join_2024.json'}}}}));
              } catch(e) { cards.push(fusionCardForSource('dsz', null)); }
              // v2 신규 3종 (사용 데이터: derived 필드를 카드에 노출)
              for (const k of ['weather', 'medical', 'bike']) {
                const node = sources[k] && sources[k].data ? sources[k].data : null;
                cards.push(fusionCardForSource(k, node));
              }

              // fusion_summary v2 신호 배너 (카드 위에)
              const v2HtmlParts = [];
              if (summary.sources_fused) v2HtmlParts.push(`<span style="color:var(--safe);font-weight:900;">${summary.sources_fused}src</span>`);
              if (summary.weather_raining)   v2HtmlParts.push(`<span style="color:#6BAEFF;">🌧️ 우천 +${(100*(summary.wet_road_risk_boost||0)).toFixed(0)}%</span>`);
              if ((summary.nearest_ER_load||0) >= 0.6) v2HtmlParts.push(`<span style="color:#FF6B6B;">🏥 ER ${(100*summary.nearest_ER_load).toFixed(0)}% ×${(summary.severity_multiplier||1).toFixed(2)}</span>`);
              if ((summary.bike_lane_risk_boost||0) > 0.05) v2HtmlParts.push(`<span style="color:#FFB020;">🚴 자전거 +${(100*summary.bike_lane_risk_boost).toFixed(0)}%</span>`);
              if (summary.fusion_risk_score != null) v2HtmlParts.push(`<span style="color:var(--danger);">융합위험 ${summary.fusion_risk_score} (${summary.risk_level})</span>`);

              const banner = `<div style="grid-column:1/-1;padding:12px 16px;background:linear-gradient(135deg,rgba(0,224,154,0.10),rgba(124,58,237,0.06));border:1px solid rgba(0,224,154,0.30);border-radius:10px;display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-family:'JetBrains Mono',monospace;font-size:12px;">
                <span style="font-weight:900;letter-spacing:2px;color:var(--accent2);">FUSION v2 (9-src):</span>
                ${v2HtmlParts.join('<span style="color:var(--muted);">·</span>')}
              </div>`;
              document.getElementById('fusionCards').innerHTML = banner + cards.join('');
              toast(`9종 융합 완료 (${id})`, 'success');
            } catch(e) {
              toast('융합 실패', 'error');
            } finally {
              hideLoader();
            }
          }

          /* ── PWA QR + APK QR ── */
          (function drawPwaQR(){
            try {
              const url = window.location.origin + '/pwa';
              document.getElementById('pwaLink').href = url;
              document.getElementById('pwaLink').textContent = url;
              const qr = qrcode(0, 'M');
              qr.addData(url);
              qr.make();
              document.getElementById('pwaQr').innerHTML = qr.createImgTag(5, 10);
            } catch(e) {}
          })();
          (function drawApkQR(){
            try {
              const apkUrl = 'https://github.com/leelang7/AuraView/releases/latest/download/auraview_fleet.apk';
              const qr = qrcode(0, 'M');
              qr.addData(apkUrl);
              qr.make();
              const el = document.getElementById('apkQr');
              if (el) el.innerHTML = qr.createImgTag(5, 10);
            } catch(e) {}
          })();

          /* ── FLEET ── */
          async function loadFleetStats() {
            const res = await fetch(window.location.origin + '/fleet/stats');
            const data = await res.json();
            document.getElementById('fleetOut').textContent = JSON.stringify(data, null, 2);
            // flywheel 다이어그램 라이브 카운터 갱신
            const u = document.getElementById('flowUploadCount');
            const dv = document.getElementById('flowDeviceCount');
            if (u) u.textContent = (data.total ?? 0) + '건';
            if (dv) dv.textContent = (data.unique_devices ?? 0) + ' 단말';
            try {
              const hz = await fetch(window.location.origin + '/healthz/details').then(r=>r.json());
              const auc = hz.trained_model_metric?.auc;
              const fa = document.getElementById('flowAuc');
              if (fa && auc) fa.textContent = auc.toFixed(4);
            } catch(e) {}
            // 갤러리는 인증된 경우에만 함께 갱신
            if (getAdminToken()) loadFleetGallery();
          }

          /* ── FLEET GALLERY · ADMIN AUTH + 다중선택 + 일괄삭제 ── */
          let _selectedFleet = new Set();

          function getAdminToken() { return localStorage.getItem('av_admin_token') || ''; }
          function setAdminToken(t) { localStorage.setItem('av_admin_token', t); }
          function clearAdminToken() { localStorage.removeItem('av_admin_token'); }

          async function adminLogin() {
            const t = prompt('관리자 토큰을 입력하세요:');
            if (!t) return;
            try {
              const res = await fetch(window.location.origin + '/fleet/auth', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({token: t.trim()}),
              });
              if (!res.ok) {
                alert('인증 실패: 토큰이 올바르지 않습니다.');
                return;
              }
              setAdminToken(t.trim());
              applyAdminUI();
              loadFleetGallery();
            } catch(e) {
              alert('인증 실패: ' + e.message);
            }
          }

          function adminLogout() {
            clearAdminToken();
            _selectedFleet.clear();
            applyAdminUI();
          }

          function applyAdminUI() {
            const locked = document.getElementById('fleetLocked');
            const galWrap = document.getElementById('fleetGalleryWrap');
            const has = !!getAdminToken();
            if (locked) locked.style.display = has ? 'none' : 'block';
            if (galWrap) galWrap.style.display = has ? 'block' : 'none';
          }

          function authHeaders() {
            const t = getAdminToken();
            return t ? {'X-Admin-Token': t} : {};
          }

          async function loadFleetGallery() {
            const wrap = document.getElementById('fleetGallery');
            const stats = document.getElementById('fleetGalleryStats');
            if (!wrap) return;
            const tk = getAdminToken();
            if (!tk) { applyAdminUI(); return; }
            try {
              const res = await fetch(window.location.origin + '/fleet/list?limit=500', {headers: authHeaders()});
              if (res.status === 401) { clearAdminToken(); applyAdminUI(); alert('세션 만료. 다시 로그인하세요.'); return; }
              const data = await res.json();
              _selectedFleet.clear();
              updateSelCount();
              if (!Array.isArray(data) || data.length === 0) {
                wrap.innerHTML = '<div class="placeholder" style="grid-column:1/-1;">아직 업로드된 이미지가 없습니다.</div>';
                if (stats) stats.textContent = '0 건';
                return;
              }
              if (stats) stats.textContent = data.length + ' 건 · ' + new Set(data.map(d => d.pseudo_device)).size + ' 단말';
              wrap.innerHTML = '';
              data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'fleet-card';
                card.dataset.path = item.path;
                card.style.cssText = 'background:var(--surface2);border:2px solid var(--border);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;cursor:pointer;transition:border-color 0.15s,box-shadow 0.15s;';
                const exists = item.exists !== false;
                const reasonColor = item.reason === 'crosswalk_blocked' ? 'var(--danger)' :
                                    item.reason === 'high_entropy' ? 'var(--warn)' : 'var(--accent)';
                const ts = (item.ts || '').replace('T', ' ').slice(0, 19);
                const imgSrc = `/fleet/image/${item.path}?token=${encodeURIComponent(tk)}`;
                card.innerHTML = `
                  <div style="aspect-ratio:1;background:#000;display:flex;align-items:center;justify-content:center;position:relative;">
                    ${exists
                      ? `<img src="${imgSrc}" style="width:100%;height:100%;object-fit:cover;" loading="lazy"
                              onerror="this.parentElement.innerHTML='<div style=&quot;color:var(--muted);font-size:10px;&quot;>로드 실패</div>';"/>`
                      : '<div style="color:var(--muted);font-size:10px;">파일 없음</div>'}
                    <div style="position:absolute;top:4px;left:4px;background:${reasonColor};color:#000;padding:2px 6px;border-radius:4px;font-size:9px;font-weight:700;font-family:JetBrains Mono,monospace;">
                      ${item.reason || '?'}
                    </div>
                    <div style="position:absolute;top:4px;right:4px;background:rgba(0,0,0,0.7);color:#fff;padding:2px 5px;border-radius:4px;font-size:9px;font-family:JetBrains Mono,monospace;">
                      ε ${(item.entropy ?? 0).toFixed(2)}
                    </div>
                    <div class="sel-mark" style="position:absolute;bottom:4px;right:4px;width:24px;height:24px;border-radius:50%;background:rgba(0,0,0,0.6);border:2px solid #fff;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:14px;opacity:0.7;">○</div>
                  </div>
                  <div style="padding:6px 8px;font-size:10px;font-family:JetBrains Mono,monospace;color:var(--muted);">
                    <div style="color:var(--text);font-weight:700;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${item.pseudo_device || '-'}</div>
                    <div style="margin-top:2px;">${ts}</div>
                    <div>${item.intersection_id ? '🚦 ' + item.intersection_id : '📍 ' + (item.lat ?? '-') + ',' + (item.lon ?? '-')}</div>
                    <div style="margin-top:4px;display:flex;gap:4px;" onclick="event.stopPropagation();">
                      <button onclick="window.open('${imgSrc}','_blank')" style="flex:1;background:rgba(0,200,255,0.15);border:1px solid var(--accent);color:var(--accent);padding:3px;border-radius:4px;font-size:9px;cursor:pointer;font-family:inherit;">원본</button>
                      <button onclick="deleteFleetImage('${item.path}')" style="flex:1;background:rgba(255,90,90,0.12);border:1px solid var(--danger);color:var(--danger);padding:3px;border-radius:4px;font-size:9px;cursor:pointer;font-family:inherit;">삭제</button>
                    </div>
                  </div>
                `;
                card.onclick = () => toggleSelect(item.path, card);
                wrap.appendChild(card);
              });
            } catch (e) {
              wrap.innerHTML = '<div class="placeholder" style="grid-column:1/-1;color:var(--danger);">갤러리 로드 실패: ' + e.message + '</div>';
            }
          }

          function toggleSelect(path, card) {
            if (_selectedFleet.has(path)) { _selectedFleet.delete(path); }
            else { _selectedFleet.add(path); }
            paintSelection();
            updateSelCount();
          }

          function paintSelection() {
            document.querySelectorAll('.fleet-card').forEach(card => {
              const selected = _selectedFleet.has(card.dataset.path);
              card.style.borderColor = selected ? 'var(--accent)' : 'var(--border)';
              card.style.boxShadow = selected ? '0 0 16px rgba(0,200,255,0.45)' : 'none';
              const mark = card.querySelector('.sel-mark');
              if (mark) {
                mark.textContent = selected ? '✓' : '○';
                mark.style.background = selected ? 'var(--accent)' : 'rgba(0,0,0,0.6)';
                mark.style.color = selected ? '#000' : '#fff';
                mark.style.opacity = selected ? '1' : '0.7';
              }
            });
          }

          function updateSelCount() {
            const c = document.getElementById('selCount');
            const btn = document.getElementById('bulkDelBtn');
            if (c) c.textContent = _selectedFleet.size + '건 선택';
            if (btn) {
              btn.disabled = _selectedFleet.size === 0;
              btn.style.opacity = _selectedFleet.size === 0 ? '0.5' : '1';
            }
          }

          function selectAll() {
            document.querySelectorAll('.fleet-card').forEach(card => _selectedFleet.add(card.dataset.path));
            paintSelection(); updateSelCount();
          }
          function selectNone() { _selectedFleet.clear(); paintSelection(); updateSelCount(); }
          function invertSelection() {
            document.querySelectorAll('.fleet-card').forEach(card => {
              const p = card.dataset.path;
              if (_selectedFleet.has(p)) _selectedFleet.delete(p); else _selectedFleet.add(p);
            });
            paintSelection(); updateSelCount();
          }

          async function bulkDelete() {
            if (_selectedFleet.size === 0) return;
            if (!confirm(_selectedFleet.size + '건의 이미지를 삭제하시겠습니까? 되돌릴 수 없습니다.')) return;
            try {
              const res = await fetch(window.location.origin + '/fleet/delete-batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', ...authHeaders()},
                body: JSON.stringify({filenames: Array.from(_selectedFleet)}),
              });
              if (res.status === 401) { clearAdminToken(); applyAdminUI(); alert('세션 만료. 다시 로그인하세요.'); return; }
              const j = await res.json();
              alert(j.total + '건 삭제 완료' + (j.missing && j.missing.length ? ' · ' + j.missing.length + '건 실패' : ''));
              loadFleetGallery();
              loadFleetStats();
            } catch(e) {
              alert('삭제 실패: ' + e.message);
            }
          }

          async function deleteFleetImage(filename) {
            if (!confirm('이 이미지를 삭제하시겠습니까?\\n\\n' + filename)) return;
            try {
              const res = await fetch(window.location.origin + '/fleet/image/' + encodeURIComponent(filename), {method:'DELETE', headers: authHeaders()});
              if (res.status === 401) { clearAdminToken(); applyAdminUI(); alert('세션 만료. 다시 로그인하세요.'); return; }
              const j = await res.json();
              if (j.status === 'ok') {
                loadFleetGallery();
                loadFleetStats();
              } else {
                alert('삭제 실패: ' + JSON.stringify(j));
              }
            } catch(e) {
              alert('삭제 실패: ' + e.message);
            }
          }

          // 페이지 진입 시 인증 상태에 따라 잠금 / 본문 토글
          document.addEventListener('DOMContentLoaded', applyAdminUI);

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
                'count=' + data.count + '\\n\\n' +
                (data.messages || []).map(m =>
                  `${m.device_id || '?'}  hdg=${m.heading_deg}°  spd=${m.speed_kmh}km/h  decel=${m.decel_g||0}\\n  detections=${(m.detections||[]).length}  occ=${m.occluded_mass||0}`
                ).join('\\n\\n');
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

          /* ── SHOWREEL HERO (페이지 첫 로드 시 즉시 + TAB ⑥ 진입 시 재로드) ── */
          (function setupShowreelHero(){
            let loaded = false;
            async function loadHero() {
              if (loaded) return;
              loaded = true;
              try {
                const res = await fetch(window.location.origin + '/showreel/latest');
                if (!res.ok) throw new Error('no showreel');
                const data = await res.json();
                if (!data.video_url) throw new Error('no video_url');
                const hero = document.getElementById('showreelHero');
                if (hero) hero.innerHTML = `
                  <video controls autoplay muted loop playsinline style="width:100%;height:100%;object-fit:contain;background:#000;border-radius:12px;">
                    <source src="${data.video_url}" type="video/mp4"/>
                  </video>`;
                const meta = document.getElementById('showreelMeta');
                if (meta) meta.innerHTML =
                  `${data.name || ''} · ${(data.size_kb||0)} KB · ${(data.age_hours ?? '?')}시간 전 생성 · 음향 포함`;
              } catch(e) {
                const hero = document.getElementById('showreelHero');
                if (hero) hero.innerHTML =
                  `<div class="placeholder"><div class="placeholder-icon">⚠️</div>합본 영상이 아직 없습니다. 아래 "⭐ 합본 시연 영상" 버튼으로 생성하세요.</div>`;
              }
            }
            // 페이지 로드 직후 즉시 시도 (TAB 클릭 안 해도 영상 로드)
            loadHero();
            const tab6 = document.querySelector('[data-tab="tab6"]');
            if (tab6) tab6.addEventListener('click', loadHero);
          })();

          /* ── SHOWREEL build (async + poll) ── */
          async function buildShowreel() {
            showLoader('합본 영상 생성 중 (1~2분 소요)...');
            try {
              const enq = await fetch(window.location.origin + '/showreel/build?limit=3', {method:'POST'});
              if (!enq.ok) throw new Error(await enq.text());
              const job = await enq.json();
              if (!job.job_id) throw new Error('no job_id');
              toast('빌드 큐잉됨 · 진행률 폴링 중', 'info');
              // 최대 3분 폴링 (5초 간격)
              let result = null;
              for (let i = 0; i < 36; i++) {
                await new Promise(r => setTimeout(r, 5000));
                const r2 = await fetch(window.location.origin + '/showreel/jobs/' + job.job_id);
                if (!r2.ok) continue;
                const j = await r2.json();
                if (j.status === 'done') { result = j.result; break; }
                if (j.status === 'error' || j.status === 'rejected') throw new Error(j.error || j.status);
              }
              if (!result) throw new Error('timeout');
              const wrap = document.getElementById('scnVideoWrap');
              if (wrap) {
                wrap.innerHTML = `
                  <video controls autoplay muted loop style="width:100%;height:100%;object-fit:contain;background:#000;border-radius:12px;">
                    <source src="${result.video_url}?t=${Date.now()}" type="video/mp4"/>
                  </video>`;
              }
              // 상단 hero 도 갱신
              const hero = document.getElementById('showreelHero');
              if (hero) {
                hero.innerHTML = `
                  <video controls autoplay muted loop playsinline style="width:100%;height:100%;object-fit:contain;background:#000;border-radius:12px;">
                    <source src="${result.video_url}?t=${Date.now()}" type="video/mp4"/>
                  </video>`;
              }
              const box = document.getElementById('scnStatus');
              if (box) {
                box.className = 'status info';
                box.innerHTML = `
                  <div class="status-title">SHOWREEL READY</div>
                  <div class="status-main">평균 선행 경고 ${result.average_lead_time_s}초</div>
                  <div class="status-meta">
                    포함 시나리오 &nbsp;${result.scenarios.length}<br>
                    프레임 수 &nbsp;${result.frame_count}<br>
                    파일 &nbsp;${result.video_url}
                  </div>`;
              }
              toast('합본 영상 생성 완료', 'success');
            } catch(e) {
              toast('합본 영상 생성 실패: ' + (e.message || ''), 'error');
            } finally { hideLoader(); }
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
            // 비어있으면 자동 생성
            if (items.length === 0) {
              try {
                await fetch(window.location.origin + '/reports/generate?top=10', {method:'POST'});
                const r2 = await fetch(window.location.origin + '/reports/list').then(r => r.json());
                return _renderReportList(r2.items || []);
              } catch(e) {}
            }
            _renderReportList(items);
          }

          function _renderReportList(items) {
            if (items.length === 0) {
              document.getElementById('reportOut').innerHTML =
                '<div class="placeholder" style="margin-top:14px;">아직 생성된 리포트가 없습니다. "Top 20 리포트 생성" 버튼을 눌러주세요.</div>';
              return;
            }
            const latest = items[0];
            const listHtml = items.map(i => `
              <div class="rank-item" style="margin-top:8px;cursor:pointer;" onclick="document.getElementById('reportPreview').src='${i.html_url}';">
                <div class="rank-head">
                  <div class="rank-title">📄 ${i.name}</div>
                  <span class="badge b-g">${i.size_kb} KB</span>
                </div>
                <div class="rank-body">${i.created_at} · <a style="color:var(--accent)" target="_blank" href="${i.html_url}" onclick="event.stopPropagation();">HTML</a> · <a style="color:var(--accent)" target="_blank" href="${i.json_url}" onclick="event.stopPropagation();">JSON</a></div>
              </div>`).join('');
            document.getElementById('reportOut').innerHTML = `
              <div class="dashboard-grid" style="margin-top:14px;">
                <div class="left-col">
                  <div class="card">
                    <div class="card-tag">RECENT REPORTS · ${items.length}건</div>
                    <div class="section-label">// 클릭하면 우측에 미리보기</div>
                    ${listHtml}
                  </div>
                </div>
                <div class="right-col">
                  <div class="card">
                    <div class="card-tag">LATEST REPORT PREVIEW</div>
                    <div class="section-label">// ${latest.name}</div>
                    <iframe id="reportPreview" src="${latest.html_url}" style="width:100%;height:520px;margin-top:10px;border:1px solid var(--border);border-radius:12px;background:#fff;"></iframe>
                  </div>
                </div>
              </div>`;
          }

          /* ── METRIC LIVE LOAD (TAB ⑤ 진입 시) ── */
          (function setupMetricLive(){
            const tab5 = document.querySelector('[data-tab="tab5"]');
            if (!tab5) return;
            let loaded = false;
            const fmtPct = v => (typeof v === 'number') ? (v*100).toFixed(1) + '%' : '—';
            const tile = (label, value, color) => `
              <div style="padding:12px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;text-align:center;">
                <div style="color:var(--muted);font-size:9.5px;letter-spacing:1.8px;font-family:'JetBrains Mono',monospace;">${label}</div>
                <div style="margin-top:6px;font-size:22px;font-weight:900;color:${color||'var(--text)'};">${value}</div>
              </div>`;
            tab5.addEventListener('click', async () => {
              if (loaded) return;
              loaded = true;
              try {
                const res = await fetch(window.location.origin + '/healthz/details');
                const data = await res.json();
                const m = data.trained_model_metric && Object.keys(data.trained_model_metric).length
                          ? data.trained_model_metric : (data.model_metric || {});
                const isTrained = !!(data.trained_model_metric && Object.keys(data.trained_model_metric).length);
                const backend = (data.features && data.features.risk_model_backend) || '—';
                const grid = document.getElementById('metricGrid');
                grid.innerHTML = [
                  tile('AUC',          m.auc != null ? m.auc.toFixed(4) : '—', isTrained ? 'var(--safe)' : 'var(--accent)'),
                  tile('F1 @ 0.5',     m['f1@0.5'] != null ? m['f1@0.5'].toFixed(4) : '—', 'var(--safe)'),
                  tile('Precision',    m['precision@0.5'] != null ? m['precision@0.5'].toFixed(4) : '—'),
                  tile('Recall',       m['recall@0.5'] != null ? m['recall@0.5'].toFixed(4) : '—'),
                  tile('Backend',      backend === 'trained' ? '⭐ trained' : backend, backend === 'trained' ? 'var(--safe)' : 'var(--warn)'),
                  tile('Params',       m.params != null ? m.params.toLocaleString() : (m.samples != null ? m.samples.toLocaleString() : '—')),
                  tile('Tests',        data.tests || '—', 'var(--safe)'),
                  tile('Routes',       (data.routes && data.routes.count) || '—'),
                ].join('');
                const sep = m.scenario_separation || {};
                if (Object.keys(sep).length) {
                  document.getElementById('metricSep').innerHTML =
                    '시나리오 분리도 (pos avg − neg avg): ' +
                    Object.entries(sep).map(([k, v]) =>
                      `<span style="color:var(--accent);">${k}</span> ${v.separation > 0 ? '+' : ''}${v.separation}`
                    ).join(' · ');
                }
              } catch(e) {
                document.getElementById('metricGrid').innerHTML =
                  '<div class="placeholder" style="grid-column:1/-1;min-height:60px;">/healthz/details 응답 실패</div>';
              }

              // KPI vs 목표 + Early Detection + Scenario chart + 벤치마크 + Tesla 비교
              try {
                const sm = await fetch(window.location.origin + '/summary.json').then(r=>r.json());
                renderKpiTargets(sm);
                renderScenarioChart(sm);
              } catch(e) {
                console.error('summary.json fetch failed', e);
              }
              try {
                const bm = await fetch(window.location.origin + '/benchmark/all').then(r=>r.json());
                renderBenchmark(bm);
              } catch(e) {}
              try {
                const tv = await fetch(window.location.origin + '/positioning/tesla-vs-auraview').then(r=>r.json());
                renderTeslaCompare(tv);
              } catch(e) {}
              // 시뮬레이터 초기화
              setupImpactSimulator();
            });

            // 인터랙티브 임팩트 시뮬레이터
            function setupImpactSimulator() {
              const slider = document.getElementById('simCovSlider');
              const leadInput = document.getElementById('simLeadInput');
              if (!slider || !leadInput) return;
              if (slider.dataset.bound) return;
              slider.dataset.bound = '1';

              let _simT = null;
              const debounce = (fn, ms) => () => { clearTimeout(_simT); _simT = setTimeout(fn, ms); };

              async function runSim() {
                const cov = (parseFloat(slider.value) / 100).toFixed(2);
                const lead = parseFloat(leadInput.value || '3.38');
                document.getElementById('simCovText').textContent = parseFloat(slider.value) + '%';
                try {
                  const r = await fetch(window.location.origin + '/impact?coverage=' + cov + '&lead=' + lead).then(r => r.json());
                  const p = r.projected_prevented || {};
                  const inputs = r.inputs || {};
                  const result = document.getElementById('simResult');
                  if (!result) return;
                  result.innerHTML = `
                    <div style="padding:14px;background:var(--surface2);border-left:3px solid var(--safe);border-radius:8px;">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);">사고 예방</div>
                      <div style="margin-top:4px;font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--safe);">${(p.prevented_accidents||0).toLocaleString()}</div>
                      <div style="font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;">건/년</div>
                    </div>
                    <div style="padding:14px;background:var(--surface2);border-left:3px solid var(--danger);border-radius:8px;">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);">사망 감소</div>
                      <div style="margin-top:4px;font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--danger);">${(p.prevented_deaths||0).toLocaleString()}</div>
                      <div style="font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;">명/년</div>
                    </div>
                    <div style="padding:14px;background:var(--surface2);border-left:3px solid var(--warn);border-radius:8px;">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);">부상 감소</div>
                      <div style="margin-top:4px;font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--warn);">${(p.prevented_injured||0).toLocaleString()}</div>
                      <div style="font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;">명/년</div>
                    </div>
                    <div style="padding:14px;background:var(--surface2);border-left:3px solid var(--accent2);border-radius:8px;">
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);">회피율</div>
                      <div style="margin-top:4px;font-family:'Black Han Sans',sans-serif;font-size:24px;color:var(--accent2);">${((r.preventability||0)*100).toFixed(1)}%</div>
                      <div style="font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;">lead × 0.25</div>
                    </div>
                  `;
                } catch(e) {}
              }

              slider.addEventListener('input', debounce(runSim, 200));
              leadInput.addEventListener('input', debounce(runSim, 300));
              runSim();
            }

            function renderBenchmark(bm) {
              const grid = document.getElementById('benchGrid');
              if (!grid) return;
              const rt = bm.risk_transformer || {};
              const v2v = bm.v2v_merge || {};
              const tile = (label, val, sub, color) => `
                <div style="padding:12px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;text-align:center;">
                  <div style="color:var(--muted);font-size:9.5px;letter-spacing:1.8px;font-family:'JetBrains Mono',monospace;">${label}</div>
                  <div style="margin-top:6px;font-size:20px;font-weight:900;color:${color||'var(--text)'};font-family:'Black Han Sans',sans-serif;">${val}</div>
                  <div style="margin-top:2px;font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;">${sub||''}</div>
                </div>`;
              grid.innerHTML = [
                tile('⚡ Risk Tx p99', rt.p99_ms != null ? rt.p99_ms.toFixed(2) + 'ms' : '—', 'mean ' + (rt.mean_ms != null ? rt.mean_ms.toFixed(2) + 'ms' : '—'), 'var(--accent2)'),
                tile('⚡ Risk Tx mean', rt.mean_ms != null ? rt.mean_ms.toFixed(2) + 'ms' : '—', 'n=' + (rt.n||100), 'var(--safe)'),
                tile('⚡ V2V merge p99', v2v.p99_ms != null ? v2v.p99_ms.toFixed(2) + 'ms' : '—', 'mean ' + (v2v.mean_ms != null ? v2v.mean_ms.toFixed(2) + 'ms' : '—'), 'var(--accent)'),
                tile('샘플 p_collision', rt.sample_p_collision != null ? rt.sample_p_collision.toFixed(3) : '—', 'backend ' + (rt.backend||'-'), 'var(--warn)'),
              ].join('');
            }

            function renderTeslaCompare(tv) {
              const wrap = document.getElementById('teslaCompare');
              if (!wrap || !tv.rows) return;
              wrap.innerHTML = tv.rows.map((r, i) => `
                <div style="display:grid;grid-template-columns:140px 1fr 1fr;gap:10px;padding:12px;background:var(--surface2);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:8px;">
                  <div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;color:var(--muted);">#${i+1}</div>
                    <div style="font-family:'Black Han Sans',sans-serif;font-size:14px;color:var(--accent);margin-top:2px;line-height:1.2;">${r.category}</div>
                  </div>
                  <div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;color:var(--muted);">TESLA</div>
                    <div style="margin-top:2px;font-size:11.5px;color:var(--text);line-height:1.4;">${r.tesla}</div>
                  </div>
                  <div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;color:var(--safe);">AURAVIEW</div>
                    <div style="margin-top:2px;font-size:11.5px;color:var(--text);line-height:1.4;">${r.auraview}</div>
                    <div style="margin-top:4px;font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;">→ ${r.endpoint}</div>
                  </div>
                </div>
              `).join('');
            }

            // KPI vs 목표 시각화
            function renderKpiTargets(sm) {
              const m = sm.model_trained || sm.model_baseline || {};
              const targets = {
                auc:       {value: m.auc, target: 0.85, label: 'AUC',         desc: '판별 정확도'},
                f1:        {value: m.f1_at_0_5, target: 0.82, label: 'F1 Score',   desc: '정밀도·재현율 조화평균'},
                precision: {value: m.precision_at_0_5, target: 0.85, label: 'Precision', desc: '오경고 억제'},
                recall:    {value: m.recall_at_0_5, target: 0.80, label: 'Recall',    desc: '실제 위험 포착'},
              };
              const grid = document.getElementById('kpiTargetGrid');
              if (!grid) return;
              grid.innerHTML = '';
              for (const [k, v] of Object.entries(targets)) {
                if (v.value == null) continue;
                const pct = Math.min(100, (v.value / 1.0) * 100);
                const targetPct = (v.target / 1.0) * 100;
                const meets = v.value >= v.target;
                const ratio = ((v.value / v.target) * 100).toFixed(1);
                const color = meets ? 'var(--safe)' : 'var(--warn)';
                const div = document.createElement('div');
                div.style.cssText = 'padding:14px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;border-left:3px solid ' + color + ';';
                div.innerHTML = `
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;">${v.label.toUpperCase()}</div>
                      <div style="margin-top:4px;font-size:10px;color:var(--muted);">${v.desc}</div>
                    </div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;padding:3px 6px;background:${meets?'rgba(0,224,154,0.15)':'rgba(255,176,32,0.15)'};color:${color};border-radius:4px;font-weight:700;">
                      ${meets ? '✓ 달성' : '진행'}
                    </div>
                  </div>
                  <div style="margin-top:10px;display:flex;align-items:baseline;gap:8px;">
                    <span style="font-family:'Black Han Sans',sans-serif;font-size:28px;color:${color};">${v.value.toFixed(3)}</span>
                    <span style="font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;">/ 목표 ${v.target.toFixed(2)}</span>
                  </div>
                  <div style="margin-top:8px;height:6px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;position:relative;">
                    <div style="width:${pct}%;height:100%;background:${color};"></div>
                    <div style="position:absolute;left:${targetPct}%;top:-2px;bottom:-2px;width:2px;background:var(--warn);"></div>
                  </div>
                  <div style="margin-top:6px;font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;text-align:right;">
                    목표 대비 ${ratio}%
                  </div>
                `;
                grid.appendChild(div);
              }

              // Early Detection
              const lead = m.avg_lead_time_s;
              const earlyTarget = 2.0;
              if (lead != null) {
                document.getElementById('earlyDetText').textContent = lead.toFixed(2) + ' 초';
                const ratio = Math.min(100, (lead / 5.0) * 100);
                document.getElementById('earlyDetBar').style.width = ratio + '%';
                const target = document.getElementById('earlyDetTarget');
                if (target) target.textContent = lead >= earlyTarget ? ('✓ ' + ((lead - earlyTarget)).toFixed(1) + 's 초과 달성') : ('진행 중');
              }
            }

            // 시나리오별 분리도 차트 (mixed/rush_hour/night/rainy)
            function renderScenarioChart(sm) {
              const sep = (sm.model_baseline && sm.model_baseline.scenario_separation) || {};
              const c = document.getElementById('scenarioChart');
              if (!c || Object.keys(sep).length === 0) return;
              const ctx = c.getContext('2d');
              const dpr = window.devicePixelRatio || 1;
              const W = c.clientWidth, H = 120;
              c.width = W * dpr; c.height = H * dpr;
              ctx.scale(dpr, dpr);
              ctx.clearRect(0, 0, W, H);

              const labels = ['mixed', 'rush_hour', 'night', 'rainy'];
              const labelKo = {mixed:'혼합', rush_hour:'출퇴근', night:'야간', rainy:'우천'};
              const padX = 10, padTop = 10, padBot = 22;
              const innerW = W - padX * 2;
              const innerH = H - padTop - padBot;

              // 그리드
              ctx.strokeStyle = 'rgba(255,255,255,0.06)';
              for (let i = 0; i <= 4; i++) {
                const y = padTop + (innerH * i) / 4;
                ctx.beginPath(); ctx.moveTo(padX, y); ctx.lineTo(W - padX, y); ctx.stroke();
              }

              const groupW = innerW / labels.length;
              const barW = (groupW - 16) / 2;
              labels.forEach((lab, i) => {
                const v = sep[lab];
                if (!v) return;
                const xBase = padX + groupW * i + 8;
                // pos_avg (시안) / neg_avg (회색)
                const posH = (v.pos_avg || 0) * innerH;
                const negH = (v.neg_avg || 0) * innerH;
                ctx.fillStyle = 'rgba(0,200,255,0.85)';
                ctx.fillRect(xBase, padTop + innerH - posH, barW, posH);
                ctx.fillStyle = 'rgba(124,58,237,0.55)';
                ctx.fillRect(xBase + barW + 2, padTop + innerH - negH, barW, negH);

                // 분리도 텍스트
                ctx.fillStyle = 'rgba(0,224,154,1)';
                ctx.font = "bold 11px 'JetBrains Mono', monospace";
                ctx.fillText('+' + (v.separation || 0).toFixed(2), xBase, padTop - 1);

                // 라벨
                ctx.fillStyle = 'rgba(255,255,255,0.5)';
                ctx.font = "10px 'Noto Sans KR', sans-serif";
                ctx.fillText(labelKo[lab] || lab, xBase, H - 6);
              });
              // 레전드
              const legend = document.getElementById('scenarioLegend');
              if (legend) {
                legend.innerHTML = `
                  <span><span style="display:inline-block;width:10px;height:10px;background:rgba(0,200,255,0.85);margin-right:4px;"></span>위험 평균 (pos)</span>
                  <span><span style="display:inline-block;width:10px;height:10px;background:rgba(124,58,237,0.55);margin-right:4px;"></span>안전 평균 (neg)</span>
                  <span style="color:var(--safe);">분리도 = pos − neg (높을수록 ↑)</span>
                `;
              }
            }
          })();

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

          // TAB ① 자동 수집 통계 — 30초 주기
          async function refreshDashStats() {
            try {
              const [fl, sc, rep] = await Promise.all([
                fetch(window.location.origin + '/fleet/stats').then(r=>r.json()).catch(()=>({})),
                fetch(window.location.origin + '/scenario/list').then(r=>r.json()).catch(()=>({items:[]})),
                fetch(window.location.origin + '/reports/list').then(r=>r.json()).catch(()=>({items:[]})),
              ]);
              const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
              set('dashUploads', (fl.total ?? 0).toLocaleString());
              set('dashDevices', fl.unique_devices ?? 0);
              set('dashScenarios', (sc.items||[]).length);
              set('dashReports', (rep.items||[]).length);
            } catch(e) {}
          }
          setTimeout(refreshDashStats, 600);
          setInterval(refreshDashStats, 30000);

          // ⭐ 임팩트 + 데이터 freshness (TAB ⑤ 에서 표시) — 30초 주기로 갱신
          async function refreshImpactAndFreshness() {
            try {
              // /fusion/intersection/10 호출해서 freshness 강제 갱신
              fetch(window.location.origin + '/fusion/intersection/10').catch(()=>{});

              const [im, sc, fr] = await Promise.all([
                fetch(window.location.origin + '/impact').then(r=>r.json()).catch(()=>null),
                fetch(window.location.origin + '/impact/scenarios').then(r=>r.json()).catch(()=>null),
                fetch(window.location.origin + '/fusion/sources').then(r=>r.json()).catch(()=>null),
              ]);

              const heroEl = document.getElementById('impactHero');
              const subEl  = document.getElementById('impactSub');
              const scnEl  = document.getElementById('impactScn');
              if (heroEl && im) {
                heroEl.innerHTML = '<span style="color:var(--safe);">' + im.projected_prevented.headline + '</span>';
                subEl.textContent = 'lead time ' + im.inputs.avg_lead_time_s.toFixed(2) + 's · 회피율 ' + (im.preventability*100).toFixed(1) + '% · 도시교차로 도입 ' + (im.inputs.coverage_urban_intersections*100).toFixed(0) + '% 가정';
              }
              if (scnEl && sc) {
                scnEl.innerHTML = sc.scenarios.map(function(s){
                  return '<div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(0,200,255,0.04);">' +
                    '<div style="font-family:\\'JetBrains Mono\\',monospace;font-size:10px;letter-spacing:2px;color:var(--accent);margin-bottom:4px;">' + s.label.toUpperCase() + '</div>' +
                    '<div style="font-family:\\'Black Han Sans\\',sans-serif;font-size:18px;">' + s.prevented_accidents.toLocaleString() + '건</div>' +
                    '<div style="margin-top:2px;color:var(--muted);font-size:10px;">사망 ' + s.prevented_deaths.toLocaleString() + ' · 부상 ' + s.prevented_injured.toLocaleString() + '</div>' +
                    '</div>';
                }).join('');
              }

              // 위험 교차로 Top-10
              try {
                const ti = await fetch(window.location.origin + '/impact/top-intersections').then(r=>r.json());
                if (ti && ti.intersections) {
                  document.getElementById('topInxHeadline').textContent = ti.headline;
                  document.getElementById('topInxList').innerHTML = ti.intersections.slice(0, 10).map(function(x){
                    return '<div style="padding:10px 12px;border-left:3px solid var(--danger);background:rgba(255,59,59,0.04);border-radius:8px;">' +
                      '<div style="font-family:\\'JetBrains Mono\\',monospace;font-size:10px;color:var(--muted);">#' + x.rank + ' · ' + x.district + '</div>' +
                      '<div style="font-weight:700;color:var(--accent);margin-top:2px;">' + x.name + '</div>' +
                      '<div style="font-size:11px;color:var(--muted);margin-top:2px;">' + x.category + '</div>' +
                      '<div style="margin-top:6px;font-size:11px;">연 KIS <span style="color:var(--danger);font-weight:700;">' + x.annual_kis_baseline + '</span> → 예방 <span style="color:var(--safe);font-weight:700;">' + x.prevented_kis_yearly + '</span></div>' +
                      '</div>';
                  }).join('');
                }
              } catch(e) {}

              const fEl = document.getElementById('freshGrid');
              if (fEl && fr) {
                const modeColor = function(m) { return ({live:'var(--safe)', stub:'var(--warn)', error:'var(--danger)'}[m]) || 'var(--muted)'; };
                fEl.innerHTML = (fr.sources||[]).map(function(s){
                  return '<div style="padding:10px 12px;border-left:3px solid ' + modeColor(s.mode) + ';background:rgba(0,200,255,0.03);border-radius:8px;">' +
                    '<div style="font-family:\\'JetBrains Mono\\',monospace;font-size:10px;letter-spacing:2px;color:var(--muted);">' + s.id.toUpperCase() + '</div>' +
                    '<div style="font-weight:700;color:' + modeColor(s.mode) + ';margin-top:2px;">' + (s.mode||'?').toUpperCase() + '</div>' +
                    '<div style="font-size:10px;color:var(--muted);margin-top:2px;">' + (s.age_s != null ? s.age_s.toFixed(1) + 's ago' : '미호출') + '</div>' +
                    '</div>';
                }).join('');
              }
            } catch(e) {}
          }

          loadIntersections();
          refreshAll();
          refreshScorecard();
          refreshImpactAndFreshness();
          setInterval(refreshScorecard, 15000);
          setInterval(refreshImpactAndFreshness, 30000);

          // ─── TAB 10 : 공공데이터 라이브 — 3초 폴링 ───
          async function pdRefreshLive() {
            const summaryEl = document.getElementById('pdLiveSummary');
            const listEl = document.getElementById('pdSourceList');
            if (!summaryEl || !listEl) return;
            try {
              const r = await fetch('/fusion/sources');
              const j = await r.json();
              const sources = j.sources || [];
              let live = 0, stub = 0, err = 0, never = 0;
              for (const s of sources) {
                if (s.mode === 'live') live++;
                else if (s.mode === 'stub') stub++;
                else if (s.mode === 'error') err++;
                else never++;
              }
              const colorBadge = (mode) => {
                const map = {
                  'live':  ['LIVE',  '#00e09a', 'rgba(0,224,154,0.16)'],
                  'stub':  ['STUB',  '#ffb020', 'rgba(255,176,32,0.16)'],
                  'error': ['ERROR', '#ff3b3b', 'rgba(255,59,59,0.16)'],
                  'cached':['CACHE', '#00c8ff', 'rgba(0,200,255,0.16)'],
                };
                const [label, fg, bg] = map[mode] || ['NEVER', '#7a8794', 'rgba(120,135,148,0.16)'];
                return `<span style="display:inline-block;padding:2px 8px;border-radius:6px;background:${bg};color:${fg};font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;letter-spacing:1.2px;">${label}</span>`;
              };
              summaryEl.innerHTML = `
                <div style="padding:14px;background:rgba(0,224,154,0.10);border:1px solid rgba(0,224,154,0.30);border-radius:10px;text-align:center;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;color:var(--safe);">LIVE</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:32px;color:var(--safe);">${live}</div>
                </div>
                <div style="padding:14px;background:rgba(255,176,32,0.10);border:1px solid rgba(255,176,32,0.30);border-radius:10px;text-align:center;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;color:var(--warn);">STUB</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:32px;color:var(--warn);">${stub}</div>
                </div>
                <div style="padding:14px;background:rgba(255,59,59,0.08);border:1px solid rgba(255,59,59,0.25);border-radius:10px;text-align:center;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;color:var(--danger);">ERROR</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:32px;color:var(--danger);">${err}</div>
                </div>
                <div style="padding:14px;background:rgba(120,135,148,0.10);border:1px solid var(--border);border-radius:10px;text-align:center;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;color:var(--muted);">NOT YET</div>
                  <div style="font-family:'Black Han Sans',sans-serif;font-size:32px;color:var(--muted);">${never}</div>
                </div>
              `;
              listEl.innerHTML = sources.map(s => {
                const age = (s.age_s == null) ? '—' : `${s.age_s}s ago`;
                const last = s.last_fetched_at || '미호출';
                return `
                  <div style="padding:14px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                      <div style="font-weight:600;font-size:13px;">${s.name}</div>
                      ${colorBadge(s.mode)}
                    </div>
                    <div style="margin-top:6px;font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--muted);">
                      <div>id: <span style="color:var(--text);">${s.id}</span></div>
                      <div>origin: <span style="color:var(--accent);">${s.origin}</span></div>
                      <div>last: <span style="color:var(--text);">${last}</span> <span style="color:var(--muted);">(${age})</span></div>
                    </div>
                  </div>
                `;
              }).join('');
            } catch(e) {
              listEl.innerHTML = `<div class="placeholder" style="color:var(--danger);">로드 실패: ${e.message}</div>`;
            }
          }
          async function pdRefreshMetrics() {
            const box = document.getElementById('pdMetricsBox');
            if (!box) return;
            try {
              const r = await fetch('/metrics/competition');
              const m = await r.json();
              const mp = m.model_performance || {};
              const pf = m.public_data_fusion || {};
              const ie = m.impact_estimate || {};
              const headline = ie.headline_pilot_5pct || {};
              box.innerHTML = `
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;">
                  <div>
                    <div style="color:var(--accent);letter-spacing:1.5px;font-size:9px;">MODEL</div>
                    <div style="color:var(--text);">AUC: <strong>${mp.auc ?? '—'}</strong></div>
                    <div style="color:var(--text);">F1: <strong>${mp.f1 ?? '—'}</strong></div>
                    <div style="color:var(--text);">p99 추론: <strong>${mp.p99_inference_ms ?? '—'} ms</strong></div>
                    <div>backend: ${mp.backend ?? '—'}</div>
                  </div>
                  <div>
                    <div style="color:var(--safe);letter-spacing:1.5px;font-size:9px;">IMPACT (Pilot 5%)</div>
                    <div style="color:var(--text);">사고 예방: <strong>${(headline.prevented_incidents_yr ?? 0).toLocaleString()}</strong> 건/년</div>
                    <div style="color:var(--text);">사망 예방: <strong>${headline.prevented_deaths_yr ?? '—'}</strong> 명/년</div>
                    <div style="color:var(--text);">부상 예방: <strong>${(headline.prevented_injuries_yr ?? 0).toLocaleString()}</strong> 명/년</div>
                    <div>출처: ${ie.source ?? 'TAAS'}</div>
                  </div>
                  <div>
                    <div style="color:var(--warn);letter-spacing:1.5px;font-size:9px;">PUBLIC DATA</div>
                    <div style="color:var(--text);">총 ${pf.sources_total ?? 6}종 · live <strong style="color:var(--safe);">${pf.sources_live ?? 0}</strong> / stub <strong style="color:var(--warn);">${pf.sources_stub ?? 0}</strong> / error <strong style="color:var(--danger);">${pf.sources_error ?? 0}</strong></div>
                    <div>fallback: ${(m.verification || {}).fallback_mode ? 'on' : 'off'}</div>
                  </div>
                  <div>
                    <div style="color:var(--accent);letter-spacing:1.5px;font-size:9px;">VERIFICATION</div>
                    <div style="color:var(--text);">${(m.verification || {}).tests || '—'}</div>
                    <div>${(m.verification || {}).ci || '—'}</div>
                    <div>버전 ${m.version ?? '—'}</div>
                  </div>
                </div>
              `;
            } catch(e) {
              box.innerHTML = `<div style="color:var(--danger);">/metrics/competition 호출 실패: ${e.message}</div>`;
            }
          }
          pdRefreshLive(); pdRefreshMetrics();
          setInterval(pdRefreshLive, 3000);
          setInterval(pdRefreshMetrics, 30000);
        </script>
    </body>
    </html>
    """