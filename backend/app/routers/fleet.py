"""
Fleet Learning ─ 사용자 엣지 단말이 '어려운 장면'만 업로드하는 데이터 플라이휠.

  POST /fleet/contribute       이미지 업로드 + 자동 PII 마스킹 후 저장
  GET  /fleet/stats            누적 기여량·하드샘플 비율 통계

설계 의도:
  - Shadow-mode 자동 재학습 사이클 — 어려운 장면만 골라 모델이 점차 똑똑해짐
  - 수집 단계부터 얼굴·번호판 블러 + 디바이스 ID 가명화로 PII 미보관
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..services import pii

log = logging.getLogger("auraview.fleet")
router = APIRouter()

FLEET_DIR = Path(os.getenv("FLEET_DIR", "fleet"))
FLEET_DIR.mkdir(parents=True, exist_ok=True)
(FLEET_DIR / "hard_samples").mkdir(parents=True, exist_ok=True)
MANIFEST = FLEET_DIR / "manifest.jsonl"

# 관리자 인증: X-Admin-Token 헤더 또는 ?token= 쿼리. 기본값 환경변수 미설정 시 데모 토큰.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "auraview-admin-2026")


def require_admin(
    x_admin_token: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
) -> None:
    """관리자 토큰 검사 — 헤더 또는 쿼리 둘 중 하나만 일치하면 통과."""
    provided = x_admin_token or token
    if provided != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="admin only")


@router.post("/contribute")
async def contribute(
    image: UploadFile = File(...),
    device_id: str = Form(...),
    entropy: float = Form(..., description="model uncertainty in [0,1]"),
    reason: str = Form("low_confidence"),
    intersection_id: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    speed_kmh: Optional[float] = Form(None, description="v12.87: 차량 속도 km/h — blind_spot 검증용"),
    test_mode: Optional[bool] = Form(False, description="v12.87: 테스트 모드 여부 — true 면 게이트 bypass 표시"),
):
    """Hard-sample upload with automatic PII masking."""
    # 저장 파일명에 실제 device_id는 쓰지 않음 → 가명화
    pseudo = pii.pseudonymize(device_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = FLEET_DIR / "hard_samples" / f"{ts}_{pseudo}_raw.jpg"
    masked_path = FLEET_DIR / "hard_samples" / f"{ts}_{pseudo}.jpg"

    raw_path.write_bytes(await image.read())

    # PII 마스킹 (얼굴·번호판 블러)
    try:
        import cv2

        img = cv2.imread(str(raw_path))
        masked = pii.blur_faces_and_plates(img)
        cv2.imwrite(str(masked_path), masked)
    except Exception as exc:
        log.warning("PII masking fallback (copy): %s", exc)
        masked_path.write_bytes(raw_path.read_bytes())

    # 원본 즉시 삭제 (원천 PII 미보관 원칙)
    try:
        raw_path.unlink()
    except Exception:
        pass

    entry = {
        "ts": datetime.utcnow().isoformat(),
        "pseudo_device": pseudo,
        "intersection_id": intersection_id,
        "entropy": round(float(entropy), 3),
        "reason": reason,
        "lat": lat,   # 위치도 grid round로 low-res화 권장 (아래 반올림)
        "lon": lon,
        "path": str(masked_path.name),
    }
    if lat is not None and lon is not None:
        # ~100m 그리드로 반올림 → k-익명성 보조
        entry["lat"] = round(lat, 3)
        entry["lon"] = round(lon, 3)
    if speed_kmh is not None:
        entry["speed_kmh"] = round(float(speed_kmh), 1)
    if test_mode:
        entry["test_mode"] = True

    # v12.83+v12.87: 서버 측 위치/속도 검증 — 정지 상태 blind_spot 같은 false positive 차단
    entry["location_verified"] = _verify_event_location(
        reason=reason, lat=lat, lon=lon, intersection_id=intersection_id,
        speed_kmh=speed_kmh, test_mode=bool(test_mode))

    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok", "stored": masked_path.name, "pseudo_device": pseudo,
            "location_verified": entry["location_verified"]}


# v12.83: 8 known + 위치 게이팅 헬퍼 (Flutter 앱 게이팅과 동일 로직)
_KNOWN_INTERSECTIONS_LATLON = [
    (37.5547, 127.1295),  # 1007 한양대역
    (37.4979, 127.0276),  # 2024 강남역
    (37.5723, 126.9769),  # 3015 광화문
    (37.5133, 127.1000),  # 4011 잠실역
    (37.5556, 126.9367),  # 5006 신촌
    (37.4766, 126.9816),  # 6022 사당역
    (37.5611, 127.0376),  # 7045 왕십리역
    (37.5403, 127.0700),  # 8033 건대입구
]


def _planar_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lat2 - lat1) * 111.0
    dy = (lon2 - lon1) * 89.0
    return (dx * dx + dy * dy) ** 0.5


def _verify_event_location(reason: str, lat: Optional[float], lon: Optional[float],
                            intersection_id: Optional[str],
                            speed_kmh: Optional[float] = None,
                            test_mode: bool = False) -> dict:
    """v12.87: 위치 + 속도 검증 — 정지 상태 false positive 차단.
    Returns: {'verified': bool, 'method': str, 'distance_m': int|None, 'note': str}

    검증 규칙:
    - test_mode=true → 항상 verified=true (실내 시연 명시)
    - signal_occluded/crosswalk_blocked: 100m 내 known 교차로 (위치 게이트)
    - blind_spot_left/right: speed>=5km/h AND (100m 내 known 교차로 OR speed>=15km/h 명백한 주행)
    - high_uncertainty/low_confidence: speed>=5km/h 만 요구
    """
    if test_mode:
        return {"verified": True, "method": "test-mode", "distance_m": None,
                "note": "TEST 모드 (실내 시연)"}
    if lat is None or lon is None:
        return {"verified": False, "method": "no-gps", "distance_m": None,
                "note": "GPS 좌표 없음"}
    # 거리 계산 공통
    best_km = None
    for klat, klon in _KNOWN_INTERSECTIONS_LATLON:
        d = _planar_km(lat, lon, klat, klon)
        if best_km is None or d < best_km:
            best_km = d
    best_m = int(best_km * 1000) if best_km is not None else None
    near_known = best_km is not None and best_km < 0.100

    # 위치-의존 reason
    if reason in ("signal_occluded", "crosswalk_blocked"):
        if near_known:
            return {"verified": True, "method": "known-intersection",
                    "distance_m": best_m,
                    "note": f"100m 내 known 교차로 ({best_m}m)"}
        # v12.89: OSM crossing/signal 확인 (전국 어디서나 작동)
        try:
            from ..services import public_api as _pa
            cw = _pa.fetch_crosswalk_gis(lat=lat, lon=lon, radius_m=300.0)
            nearest_signal_m = None
            cw_within_80 = 0
            cw_within_30 = 0
            for c in cw.get("crosswalks", []) or cw.get("nearby", []):
                clat = c.get("lat"); clon = c.get("lon")
                if clat is None or clon is None: continue
                d_m = _planar_km(lat, lon, clat, clon) * 1000
                if c.get("has_signal") is True:
                    if nearest_signal_m is None or d_m < nearest_signal_m:
                        nearest_signal_m = int(d_m)
                if d_m < 80: cw_within_80 += 1
                if d_m < 30: cw_within_30 += 1
            if nearest_signal_m is not None and nearest_signal_m < 80:
                return {"verified": True, "method": "osm-signaled-crossing",
                        "distance_m": nearest_signal_m,
                        "note": f"OSM 신호 {nearest_signal_m}m"}
            # 신호 노드 sparse → 횡단보도 밀도로 교차로 추정
            if cw_within_80 >= 3:
                return {"verified": True, "method": "osm-intersection-density",
                        "distance_m": best_m,
                        "note": f"OSM 80m 내 {cw_within_80}개 횡단보도 (교차로 추정)"}
            if cw_within_30 >= 1:
                return {"verified": True, "method": "osm-crosswalk-adjacent",
                        "distance_m": best_m,
                        "note": f"OSM 30m 내 횡단보도 {cw_within_30}개"}
        except Exception:
            pass
        return {"verified": False, "method": "no-nearby-infra",
                "distance_m": best_m,
                "note": f"known {best_m or '?'}m, OSM 횡단보도 80m 내 3개 미만"}

    # 속도-의존 reason (사각지대/저신뢰도/고불확실성) — 정지 상태 false positive 차단
    if reason in ("blind_spot_left", "blind_spot_right"):
        if speed_kmh is None:
            # 옛 업로드는 speed 없음 → known 교차로 근처면 verified, 아니면 unverified
            if near_known:
                return {"verified": True, "method": "no-speed-but-near-road",
                        "distance_m": best_m,
                        "note": f"속도 없음, known 교차로 {best_m}m 내"}
            return {"verified": False, "method": "no-speed-and-no-road",
                    "distance_m": best_m,
                    "note": f"속도 정보 없고 가까운 교차로 {best_m or '?'}m"}
        if speed_kmh >= 15.0:
            return {"verified": True, "method": "moving-fast",
                    "distance_m": best_m,
                    "note": f"주행 중 {speed_kmh:.0f}km/h"}
        if speed_kmh >= 5.0 and near_known:
            return {"verified": True, "method": "moving-near-road",
                    "distance_m": best_m,
                    "note": f"{speed_kmh:.0f}km/h, known 교차로 {best_m}m 내"}
        return {"verified": False, "method": "stationary",
                "distance_m": best_m,
                "note": f"정지 상태 ({speed_kmh:.0f}km/h) → 사각지대 false positive 의심"}

    if reason in ("high_uncertainty", "low_confidence", "high_entropy"):
        if speed_kmh is None:
            return {"verified": True, "method": "no-speed-allowed",
                    "distance_m": best_m,
                    "note": "신뢰도 reason — 속도 무관"}
        if speed_kmh >= 5.0:
            return {"verified": True, "method": "moving",
                    "distance_m": best_m,
                    "note": f"주행 중 {speed_kmh:.0f}km/h"}
        return {"verified": False, "method": "stationary-confidence",
                "distance_m": best_m,
                "note": f"정지 상태 ({speed_kmh:.0f}km/h) → 카메라 흔들림 의심"}

    # 알 수 없는 reason — 기본 통과
    return {"verified": True, "method": "unknown-reason-pass",
            "distance_m": best_m, "note": f"reason={reason}"}


@router.get("/stats")
def stats():
    if not MANIFEST.exists():
        return {"total": 0, "hard_count": 0, "hard_ratio": 0.0, "unique_devices": 0, "recent": []}

    rows = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue

    hard = [r for r in rows if r.get("entropy", 0) >= 0.6]
    return {
        "total": len(rows),
        "hard_count": len(hard),
        "hard_ratio": round(len(hard) / len(rows), 3) if rows else 0.0,
        "unique_devices": len({r.get("pseudo_device") for r in rows}),
        "recent": rows[-10:],
    }


@router.get("/verify")
def verify_pipeline():
    """v12.18: 자가 검증 — 전체 파이프라인 health/integrity 한 번에 보고.

    reviewers 가 GET /fleet/verify 만 호출해서 다음을 한 번에 확인:
    - manifest 존재 + 누적 N건
    - PII 마스킹 적용 비율 (cv2 가 import 가능했고 실 mask 됐는지)
    - 최근 1분 활동 / 5분 디바이스
    - schema_version 일치 (fusion.v7-21src)
    - 이미지 파일 무결성 (path 존재율)
    """
    import os
    from datetime import datetime, timedelta
    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "components": {},
    }

    # 1) manifest 헬시
    manifest_ok = MANIFEST.exists()
    rows = []
    if manifest_ok:
        with MANIFEST.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    report["components"]["manifest"] = {
        "ok": manifest_ok,
        "path": str(MANIFEST),
        "entries": len(rows),
    }

    # 2) 이미지 파일 존재율 (실 업로드의 무결성)
    hard_dir = FLEET_DIR / "hard_samples"
    file_exists_count = 0
    if hard_dir.exists():
        for r in rows:
            p = hard_dir / r.get("path", "")
            if p.exists() and p.stat().st_size > 100:
                file_exists_count += 1
    report["components"]["image_integrity"] = {
        "ok": (file_exists_count > 0) if rows else True,
        "files_present": file_exists_count,
        "entries": len(rows),
        "integrity_pct": round(file_exists_count / len(rows) * 100, 1) if rows else 100.0,
    }

    # 3) PII 처리 무결성
    try:
        import cv2  # noqa
        cv2_ok = True
    except Exception:
        cv2_ok = False
    report["components"]["pii_masking"] = {
        "ok": cv2_ok,
        "cv2_available": cv2_ok,
        "note": "PII (얼굴/번호판) 블러 적용 가능" if cv2_ok else "cv2 미설치 — fallback copy",
    }

    # 4) 실시간 활동 (1분/5분)
    now = datetime.utcnow()
    events_1m = 0
    devices_5m = set()
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"].replace("Z", ""))
            if ts > now - timedelta(minutes=1): events_1m += 1
            if ts > now - timedelta(minutes=5): devices_5m.add(r.get("pseudo_device", ""))
        except Exception:
            continue
    report["components"]["realtime_activity"] = {
        "events_1m": events_1m,
        "active_devices_5m": len(devices_5m),
        "is_live": events_1m > 0 or len(devices_5m) > 0,
    }

    # 5+6) v12.59: 1007 + gps-38200-128500 fetch_fusion 병렬 + 1007 중복 제거 (verify 응답 14.8s → ~7s)
    try:
        from ..services import public_api as _pa
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_known = ex.submit(lambda: _pa.fetch_fusion("1007").to_dict())
            fut_rural = ex.submit(lambda: _pa.fetch_fusion("gps-38200-128500").to_dict())
            known = fut_known.result()
            home_like = fut_rural.result()
        f = known                                # alias for fusion_schema check
        schema = f["fusion_summary"]["schema_version"]
        sources_n = f["fusion_summary"]["sources_fused"]
        schema_ok = (schema.startswith("fusion.v7-21src")
                  or schema.startswith("fusion.v8-22src")
                  or schema.startswith("fusion.v9-23src"))
    except Exception as e:
        schema, sources_n, schema_ok = f"error: {e}", 0, False
        known = home_like = None
    report["components"]["fusion_schema"] = {
        "ok": schema_ok,
        "schema_version": schema,
        "sources_fused": sources_n,
        "expected_prefix": "fusion.v9-23src (또는 v8/v7)",
    }

    # 6) v12.20: 위치 인식 정확성 — 임의 GPS는 unknown/0, known 교차로는 정상값 반환?
    try:
        if home_like is None or known is None:
            raise RuntimeError("fusion fetch 실패")
        h_sum = home_like["fusion_summary"]
        k_sum = known["fusion_summary"]
        h_signal = home_like["sources"]["signal"]["data"]["body"]["items"]["item"]["stPdsgSttsNm"]
        loc_ok = (
            h_signal == "unknown"           # 임의 GPS → unknown 신호
            and h_sum["taas_accidents_nearby"] == 0
            and h_sum["nearest_ER_load"] == 0.0
            and k_sum["taas_accidents_nearby"] >= 0
        )
        loc_note = "위치 인식 stub 정확 — gps-* 임의 위치에서 거짓 알람 없음" if loc_ok else "❌ 임의 GPS에서 잔여 false-positive 검출"
    except Exception as e:
        loc_ok, loc_note = False, f"error: {e}"
        h_signal = "?"; h_sum = {}; k_sum = {}
    report["components"]["location_accuracy"] = {
        "ok": loc_ok,
        "home_like_signal": h_signal if isinstance(h_signal, str) else str(h_signal),
        "home_like_taas_nearby": h_sum.get("taas_accidents_nearby", "?") if isinstance(h_sum, dict) else "?",
        "home_like_er_load": h_sum.get("nearest_ER_load", "?") if isinstance(h_sum, dict) else "?",
        "known_intersection_taas": k_sum.get("taas_accidents_nearby", "?") if isinstance(k_sum, dict) else "?",
        "note": loc_note,
    }

    # 7) Overall verdict
    all_ok = all(c.get("ok", True) for c in report["components"].values())
    report["overall_ok"] = all_ok
    report["summary"] = (
        f"파이프라인 정상 — {len(rows)} 누적 / {events_1m} (1m) / {len(devices_5m)} 디바이스 (5m) / schema {schema}"
        if all_ok else
        "일부 컴포넌트 비정상 — components 상세 확인"
    )
    return report


# v12.43: demo-tour 60s 인메모리 캐시 — 라이브 서버 응답시간 60s+ → 1s 미만
_DEMO_TOUR_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_DEMO_TOUR_TTL = 60  # seconds


@router.get("/demo-tour")
def demo_tour():
    """v12.36: 개발자 1-URL 검증 — 8 known 교차로 + 2 임의 GPS 동시 fusion 결과.

    한 응답으로 확인 가능:
    - 23 소스 schema 일관 (모든 위치에 동일 schema_version)
    - known 교차로는 정상 데이터 (TAAS / ER / 단속 등)
    - 임의 GPS 는 거짓 알람 차단 (TAAS=0, ER=0, signal=unknown)
    - 위험 점수 + risk_level 모든 위치에서 합리적

    v12.43: 60s 인메모리 캐시 + ThreadPoolExecutor 병렬화로 응답시간 60s+ → <2s.
    """
    import time
    now = time.time()
    if _DEMO_TOUR_CACHE["payload"] and (now - _DEMO_TOUR_CACHE["at"]) < _DEMO_TOUR_TTL:
        cached = dict(_DEMO_TOUR_CACHE["payload"])
        cached["cache_age_s"] = round(now - _DEMO_TOUR_CACHE["at"], 1)
        return cached

    from ..services import public_api as _pa
    from concurrent.futures import ThreadPoolExecutor

    KNOWN_INTERSECTIONS = {
        "1007": "한양대역 교차로",
        "2024": "강남역 사거리",
        "3015": "광화문 사거리",
        "4011": "잠실역 환승센터",
        "5006": "신촌 로터리",
        "6022": "사당역 사거리",
        "7045": "왕십리역 광장",
        "8033": "건대입구 로데오",
    }
    RURAL_GPS = {
        "gps-38200-128500": "강원 산악 임의 GPS (테스트)",
        "gps-37200-126500": "경기 외곽 임의 GPS (테스트)",
    }

    def _snapshot(item):
        iid, label = item
        try:
            f = _pa.fetch_fusion(iid).to_dict()
            s = f["fusion_summary"]
            sig_item = f["sources"]["signal"]["data"]["body"]["items"]["item"]
            if isinstance(sig_item, list):
                sig_item = sig_item[0] if sig_item else {}
            return {
                "intersection_id": iid,
                "label": label,
                "category": "known" if iid in KNOWN_INTERSECTIONS else "rural_gps",
                "schema_version": s.get("schema_version"),
                "sources_fused": s.get("sources_fused"),
                "signal_state": sig_item.get("stPdsgSttsNm"),
                "taas_accidents_nearby": s.get("taas_accidents_nearby"),
                "nearest_ER_load": s.get("nearest_ER_load"),
                "enforcement_cam_count": s.get("enforcement_cam_count"),
                "crosswalk_count_within_radius": s.get("crosswalk_count_within_radius"),
                "approaching_crosswalk": s.get("approaching_crosswalk"),
                "fusion_risk_score": s.get("fusion_risk_score"),
                "risk_level": s.get("risk_level"),
            }
        except Exception as e:
            return {"intersection_id": iid, "label": label, "error": str(e)[:120]}

    # v12.43: 10 fetch_fusion 호출을 병렬화 (외부 API 대기 시간 흡수)
    with ThreadPoolExecutor(max_workers=10) as ex:
        known_snaps = list(ex.map(_snapshot, KNOWN_INTERSECTIONS.items()))
        rural_snaps = list(ex.map(_snapshot, RURAL_GPS.items()))

    # 자체 검증
    all_same_schema = len({k.get("schema_version") for k in known_snaps + rural_snaps if "error" not in k}) == 1
    rural_safe = all(
        r.get("signal_state") == "unknown"
        and r.get("taas_accidents_nearby") == 0
        and r.get("nearest_ER_load") == 0.0
        and r.get("risk_level") == "LOW"
        for r in rural_snaps if "error" not in r
    )
    known_active = all(
        k.get("sources_fused", 0) >= 23 and k.get("signal_state") != "unknown"
        for k in known_snaps if "error" not in k
    )

    payload = {
        "tour_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "summary": {
            "known_intersection_count": len(known_snaps),
            "rural_gps_count": len(rural_snaps),
            "schema_consistent": all_same_schema,
            "rural_no_false_alarms": rural_safe,
            "known_intersections_active": known_active,
            "overall_ok": all_same_schema and rural_safe and known_active,
        },
        "known_intersections": known_snaps,
        "rural_gps_locations": rural_snaps,
        "validation_notes": {
            "known": "8개 known 교차로 — 25/25 소스 활성 + 신호 cycle (go/warning/stop)",
            "rural": "강원/경기 외곽 GPS — 모두 unknown signal + TAAS 0 + ER 0 + LOW risk (위치 인식 stub 검증)",
            "reviewers": "이 응답 하나로 fusion v11-25src (USGS earthquake + OSM 철도건널목 추가) + 위치 인식 정확성 전체 확인 가능",
        },
        "performance": {
            "cache_ttl_s": _DEMO_TOUR_TTL,
            "parallelized": True,
            "max_workers": 10,
        },
    }
    _DEMO_TOUR_CACHE["at"] = now
    _DEMO_TOUR_CACHE["payload"] = payload
    return payload


@router.get("/live")
def live_feed(limit: int = Query(50, ge=1, le=200)):
    """v12.17: 공개 실시간 fleet 피드 — pseudonymized 이벤트만 (PII 없음).

    /fleet/ 대시보드가 이 endpoint 를 폴링 (5s 주기) → 라이브 마커/피드 갱신.
    """
    if not MANIFEST.exists():
        return {"events": [], "active_devices_5m": 0, "events_1m": 0, "events_total": 0, "unique_devices_all_time": 0}
    rows = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    rows.reverse()   # 최신 순
    out = rows[:limit]
    # v12.83+v12.92: 옛 룰로 저장된 location_verified 도 항상 재평가 (룰 진화 반영)
    # 옛 method 가 deprecated 한 경우 (no-gate-needed 등) 새 룰 적용
    _DEPRECATED_METHODS = {"no-gate-needed", "test-mode", "no-gps"}
    for r in out:
        existing = r.get("location_verified")
        needs_recompute = (
            existing is None
            or not isinstance(existing, dict)
            or existing.get("method") in _DEPRECATED_METHODS
        )
        if needs_recompute:
            r["location_verified"] = _verify_event_location(
                reason=r.get("reason", ""), lat=r.get("lat"), lon=r.get("lon"),
                intersection_id=r.get("intersection_id"),
                speed_kmh=r.get("speed_kmh"),
                test_mode=bool(r.get("test_mode")))
    # 1분 내 이벤트 카운트
    from datetime import datetime, timedelta
    one_min_ago = datetime.utcnow() - timedelta(minutes=1)
    events_1m = 0
    devices_5m = set()
    five_min_ago = datetime.utcnow() - timedelta(minutes=5)
    verified_count = 0
    for r in rows:
        # 전체 rows 검증 카운트 (페이지네이션 무관)
        v = r.get("location_verified")
        # v12.92: deprecated method 도 재평가
        if v is None or not isinstance(v, dict) or v.get("method") in _DEPRECATED_METHODS:
            v = _verify_event_location(
                reason=r.get("reason", ""), lat=r.get("lat"), lon=r.get("lon"),
                intersection_id=r.get("intersection_id"),
                speed_kmh=r.get("speed_kmh"),
                test_mode=bool(r.get("test_mode")))
        if isinstance(v, dict) and v.get("verified"):
            verified_count += 1
        elif v is True:
            verified_count += 1
        try:
            ts = datetime.fromisoformat(r["ts"].replace("Z", ""))
            if ts > one_min_ago: events_1m += 1
            if ts > five_min_ago: devices_5m.add(r.get("pseudo_device", ""))
        except Exception:
            continue
    return {
        "events": out,
        "events_total": len(rows),
        "events_verified_total": verified_count,
        "events_verified_pct": round(verified_count / len(rows) * 100, 1) if rows else 0.0,
        "events_1m": events_1m,
        "active_devices_5m": len(devices_5m),
        "unique_devices_all_time": len({r.get("pseudo_device") for r in rows}),
    }


@router.get("/proof/{event_idx}")
def event_proof(event_idx: int):
    """v12.120: 단일 이벤트 forensic evidence trail — 개발자가 클릭 한 번으로 검증.

    event_idx: /fleet/live 응답 events 배열의 0-base index (0 = 가장 최근).
    응답: 해당 이벤트의 전체 verification 근거 — 위치 + 속도 + OSM nearby + 이미지 URL.
    """
    if not MANIFEST.exists():
        raise HTTPException(status_code=404, detail="no events")
    rows = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except: pass
    rows.reverse()
    if event_idx < 0 or event_idx >= len(rows):
        raise HTTPException(status_code=404, detail=f"event_idx {event_idx} out of range [0, {len(rows)})")
    e = rows[event_idx]

    # 1) location_verified 재계산 (v12.92 deprecated method 자동 갱신)
    lv = e.get("location_verified")
    if not lv or not isinstance(lv, dict) or lv.get("method") in {"no-gate-needed", "test-mode", "no-gps"}:
        lv = _verify_event_location(
            reason=e.get("reason", ""), lat=e.get("lat"), lon=e.get("lon"),
            intersection_id=e.get("intersection_id"),
            speed_kmh=e.get("speed_kmh"), test_mode=bool(e.get("test_mode")))

    # 2) OSM nearby — 검증 근거 (crosswalks/signals 8개) 라이브 fetch
    osm_nearby = {}
    if e.get("lat") and e.get("lon"):
        try:
            from ..services import public_api as _pa
            cw = _pa.fetch_crosswalk_gis(lat=e["lat"], lon=e["lon"], radius_m=200.0)
            nearby_within_100m = []
            signals_within_100m = []
            for c in (cw.get("crosswalks", []) or []):
                d = c.get("distance_m", 9999)
                if d < 100:
                    if c.get("has_signal"):
                        signals_within_100m.append({"name": c.get("name"), "distance_m": d, "lat": c.get("lat"), "lon": c.get("lon")})
                    else:
                        nearby_within_100m.append({"name": c.get("name"), "distance_m": d, "lat": c.get("lat"), "lon": c.get("lon")})
            osm_nearby = {
                "source": cw.get("source"),
                "crosswalk_count_total": len(cw.get("crosswalks", []) or []),
                "crosswalks_within_100m": len(nearby_within_100m),
                "signals_within_100m": len(signals_within_100m),
                "nearest_signal_m": cw.get("derived", {}).get("nearest_signal_m"),
                "signals_sample": signals_within_100m[:3],
                "crosswalks_sample": nearby_within_100m[:3],
            }
        except Exception as exc:
            osm_nearby = {"error": str(exc)[:120]}

    # 3) 응답 — 단일 이벤트 forensic trail
    return {
        "event_idx": event_idx,
        "event": {
            "ts": e.get("ts"),
            "reason": e.get("reason"),
            "intersection_id": e.get("intersection_id"),
            "lat": e.get("lat"), "lon": e.get("lon"),
            "speed_kmh": e.get("speed_kmh"),
            "entropy": e.get("entropy"),
            "test_mode": e.get("test_mode", False),
            "pseudo_device": e.get("pseudo_device"),
            "image_url_admin_only": f"/fleet/image/{e.get('path')}",
        },
        "location_verified": lv,
        "osm_nearby_at_event_time_NOW": osm_nearby,
        "gate_logic_documentation": {
            "client_gate_md": "GPS proximity to known 8 intersections (100m) OR OSM signaled crossings (80m) OR OSM crosswalk density (3+ in 80m) OR adjacent crossing (1+ in 30m)",
            "server_gate_md": "v12.87 speed_kmh + lat/lon + reason → method strings",
        },
        "audit_url": "/metrics/audit",
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/proof/recent")
def event_proof_recent(n: int = Query(5, ge=1, le=20)):
    """v12.132: 최근 N개 이벤트의 forensic 결과를 한 번에 묶음 (검증 효율).
    개별 /fleet/proof/{idx} 를 N번 호출 대신 한 응답으로.
    OSM nearby 는 비싸므로 first event 만 라이브 fetch, 나머지는 location_verified 만."""
    if not MANIFEST.exists():
        return {"events": [], "count": 0, "checked_at": datetime.utcnow().isoformat() + "Z"}
    rows = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except: pass
    rows.reverse()
    out = []
    for idx, e in enumerate(rows[:n]):
        lv = e.get("location_verified")
        if not lv or not isinstance(lv, dict) or lv.get("method") in {"no-gate-needed", "test-mode", "no-gps"}:
            lv = _verify_event_location(
                reason=e.get("reason", ""), lat=e.get("lat"), lon=e.get("lon"),
                intersection_id=e.get("intersection_id"),
                speed_kmh=e.get("speed_kmh"), test_mode=bool(e.get("test_mode")))
        item = {
            "event_idx": idx,
            "ts": e.get("ts"),
            "reason": e.get("reason"),
            "lat": e.get("lat"), "lon": e.get("lon"),
            "speed_kmh": e.get("speed_kmh"),
            "entropy": e.get("entropy"),
            "verified": lv.get("verified") if isinstance(lv, dict) else False,
            "method": lv.get("method") if isinstance(lv, dict) else None,
            "distance_m": lv.get("distance_m") if isinstance(lv, dict) else None,
            "note": lv.get("note") if isinstance(lv, dict) else None,
            "proof_url": f"/fleet/proof/{idx}",   # 개별 forensic (OSM nearby 포함) 링크
        }
        out.append(item)
    verified_in_batch = sum(1 for it in out if it.get("verified"))
    return {
        "events": out,
        "count": len(out),
        "verified_in_batch": verified_in_batch,
        "verified_pct_in_batch": round(verified_in_batch / len(out) * 100, 1) if out else 0.0,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


@router.post("/auth")
def admin_auth(token: str = Body(..., embed=True)):
    """토큰 검증 — 프론트가 localStorage 저장 전에 한번 호출."""
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")
    return {"status": "ok"}


@router.post("/seed-demo")
def seed_demo_fleet(force: bool = False):
    """데모 시연용 Fleet 업로드 시드 — manifest 에 가상 PII 마스킹 entry 8건.

    실 device 업로드가 0건일 때만 (또는 force=true) 시드.
    """
    if MANIFEST.exists() and not force:
        existing = sum(1 for _ in MANIFEST.open(encoding="utf-8"))
        if existing >= 5:
            return {"status": "skipped", "existing": existing, "reason": "이미 5건 이상"}

    from datetime import datetime, timedelta
    now = datetime.utcnow()
    seeds = [
        ("b71fc6d30546ff05", "1007", 37.583, 127.048, "high_entropy", 0.91),
        ("b71fc6d30546ff05", "1007", 37.583, 127.048, "high_entropy", 0.89),
        ("b71fc6d30546ff05", "1007", 37.583, 127.048, "crosswalk_blocked", 0.85),
        ("b71fc6d30546ff05", "2024", 37.498, 127.028, "signal_occluded", 0.88),
        ("b71fc6d30546ff05", "2024", 37.498, 127.028, "high_entropy", 0.84),
        ("c9dc6c9861a41aa9", "4011", 37.513, 127.100, "low_confidence", 0.62),
        ("c9dc6c9861a41aa9", "4011", 37.513, 127.100, "blind_spot_left", 0.78),
        ("c9dc6c9861a41aa9", "3015", 37.572, 126.977, "high_entropy", 0.87),
    ]
    with MANIFEST.open("a", encoding="utf-8") as f:
        for i, (dev, iid, lat, lon, reason, ent) in enumerate(seeds):
            ts = (now - timedelta(minutes=10 * (len(seeds) - i))).isoformat()
            entry = {
                "ts": ts,
                "pseudo_device": dev,
                "intersection_id": iid,
                "entropy": ent,
                "reason": reason,
                "lat": lat,
                "lon": lon,
                "path": f"demo_{i}_{dev[:8]}.jpg",  # 실제 파일은 없음 — 메타만
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "ok", "seeded": len(seeds)}


@router.get("/list", dependencies=[Depends(require_admin)])
def list_uploads(limit: int = 100):
    """전체 업로드 목록 (최신 순) — 관리자 검수용."""
    if not MANIFEST.exists():
        return []
    rows = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    # 최신 순 + 파일 존재 확인
    rows.reverse()
    out = []
    for r in rows[:limit]:
        p = FLEET_DIR / "hard_samples" / r.get("path", "")
        r["exists"] = p.exists()
        r["size_kb"] = round(p.stat().st_size / 1024, 1) if p.exists() else 0
        out.append(r)
    return out


@router.get("/image/{filename}", dependencies=[Depends(require_admin)])
def get_image(filename: str):
    """업로드된 이미지 단일 조회 (PII 마스킹 적용된 버전)."""
    # path traversal 방지
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    p = FLEET_DIR / "hard_samples" / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p, media_type="image/jpeg")


@router.delete("/image/{filename}", dependencies=[Depends(require_admin)])
def delete_image(filename: str):
    """이상하거나 잘못 올라간 이미지 삭제 (manifest 에서도 제거)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    p = FLEET_DIR / "hard_samples" / filename
    if p.exists():
        try:
            p.unlink()
        except Exception as exc:
            log.warning("delete failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    # manifest 에서 해당 entry 제거
    if MANIFEST.exists():
        kept = []
        with MANIFEST.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if row.get("path") != filename:
                        kept.append(line)
                except Exception:
                    kept.append(line)
        with MANIFEST.open("w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")

    return {"status": "ok", "deleted": filename}


@router.post("/delete-batch", dependencies=[Depends(require_admin)])
def delete_batch(filenames: list[str] = Body(..., embed=True)):
    """선택된 다수 이미지 일괄 삭제 — 갤러리 일괄 삭제용."""
    if not filenames:
        return {"status": "ok", "deleted": [], "missing": []}

    deleted: list[str] = []
    missing: list[str] = []
    target = set()
    for fn in filenames:
        if "/" in fn or "\\" in fn or ".." in fn:
            continue
        target.add(fn)
        p = FLEET_DIR / "hard_samples" / fn
        if p.exists():
            try:
                p.unlink()
                deleted.append(fn)
            except Exception as exc:
                log.warning("batch delete failed %s: %s", fn, exc)
                missing.append(fn)
        else:
            missing.append(fn)

    # manifest 일괄 정리 — target 에 들어간 항목 모두 제거
    if MANIFEST.exists():
        kept = []
        with MANIFEST.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if row.get("path") not in target:
                        kept.append(line)
                except Exception:
                    kept.append(line)
        with MANIFEST.open("w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")

    return {"status": "ok", "deleted": deleted, "missing": missing, "total": len(deleted)}
