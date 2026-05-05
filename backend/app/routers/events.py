from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BlindSignalEvent
from ..schemas import EventCreate
from ..services.public_api import fetch_signal_info

import csv
import io
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.post("/")
def create_event(data: EventCreate, db: Session = Depends(get_db)):
    signal_data = fetch_signal_info(data.intersection_id)

    body = signal_data.get("body", {})
    items = body.get("items", {})
    item_list = items.get("item", [])

    if isinstance(item_list, dict):
        item_list = [item_list]

    if not item_list:
        raise HTTPException(status_code=404, detail="No signal data found for this intersection_id")

    sig = item_list[0]

    signal_state = sig.get("stPdsgSttsNm", "")
    signal_time = sig.get("stPdsgRmndCs", 0)

    event = BlindSignalEvent(
        intersection_id=data.intersection_id,
        user_lat=data.user_lat,
        user_lon=data.user_lon,
        heading=data.heading,
        obstacle_type=data.obstacle_type,
        signal_visible=data.signal_visible,
        event_duration=data.event_duration,
        signal_state=signal_state,
        signal_remain_time=float(signal_time or 0)
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "message": "event saved",
        "event_id": event.id,
        "intersection_id": data.intersection_id,
        "signal_state": signal_state,
        "signal_remain_time": float(signal_time or 0)
    }


@router.get("/")
def list_events(db: Session = Depends(get_db)):
    events = db.query(BlindSignalEvent).order_by(BlindSignalEvent.id.desc()).all()

    result = []
    for ev in events:
        image_url = None
        if ev.image_path:
            filename = ev.image_path.split("/")[-1]
            image_url = "/uploads/" + filename

        result.append({
            "id": ev.id,
            "intersection_id": ev.intersection_id,
            "user_lat": ev.user_lat,
            "user_lon": ev.user_lon,
            "heading": ev.heading,
            "obstacle_type": ev.obstacle_type,
            "signal_visible": ev.signal_visible,
            "event_duration": ev.event_duration,
            "signal_state": ev.signal_state,
            "signal_remain_time": ev.signal_remain_time,
            "image_path": ev.image_path,
            "image_url": image_url,
            "created_at": ev.created_at.isoformat() if ev.created_at else None
        })

    return result


@router.get("/map-data")
def map_data(db: Session = Depends(get_db)):
    events = db.query(BlindSignalEvent).order_by(BlindSignalEvent.id.desc()).all()

    grouped = {}

    for ev in events:
        if ev.intersection_id not in grouped:
            grouped[ev.intersection_id] = {
                "intersection_id": ev.intersection_id,
                "event_count": 0,
                "durations": [],
                "signal_state": ev.signal_state or "",
                "obstacle_type": ev.obstacle_type or "",
                "last_lat": ev.user_lat,
                "last_lon": ev.user_lon,
            }

        grouped[ev.intersection_id]["event_count"] += 1
        grouped[ev.intersection_id]["durations"].append(ev.event_duration or 0)

        if ev.user_lat is not None and ev.user_lon is not None:
            grouped[ev.intersection_id]["last_lat"] = ev.user_lat
            grouped[ev.intersection_id]["last_lon"] = ev.user_lon

    result = []

    from ..services.scoring import calculate_risk

    for _, item in grouped.items():
        avg_duration = sum(item["durations"]) / len(item["durations"]) if item["durations"] else 0

        risk_score = calculate_risk(
            event_duration=avg_duration,
            obstacle_type=item["obstacle_type"],
            signal_state=item["signal_state"],
            count=item["event_count"]
        )

        result.append({
            "intersection_id": item["intersection_id"],
            "event_count": item["event_count"],
            "avg_duration": round(avg_duration, 2),
            "signal_state": item["signal_state"],
            "risk_score": risk_score,
            "last_lat": item["last_lat"],
            "last_lon": item["last_lon"],
        })

    result.sort(key=lambda x: x["risk_score"], reverse=True)
    return result


# ─────────────────────────────────────────────────────────────
# DEMO SEED — 데모 시연용 서울 교차로 다양화 데이터 일괄 시드
# ─────────────────────────────────────────────────────────────
DEMO_INTERSECTIONS = [
    # (id, name, lat, lon, count, avg_dur, signal_state, obstacle)
    ("1007", "한양대역 교차로",       37.5547, 127.1295, 19, 3.5, "stop-And-Remain", "truck"),
    ("2024", "강남역 사거리",         37.4979, 127.0276, 14, 4.2, "stop-And-Remain", "bus"),
    ("3015", "광화문 사거리",         37.5723, 126.9769, 11, 2.9, "stop-And-Remain", "truck"),
    ("4011", "잠실역 환승센터",       37.5133, 127.1000,  9, 3.8, "stop-And-Remain", "bus"),
    ("5006", "신촌 로터리",           37.5556, 126.9367,  7, 2.5, "stop-And-Remain", "truck"),
    ("6022", "사당역 사거리",         37.4766, 126.9816,  6, 3.1, "stop-And-Remain", "truck"),
    ("7045", "왕십리역 광장",         37.5611, 127.0376,  5, 2.8, "stop-And-Remain", "bus"),
    ("8033", "건대입구 로데오",       37.5403, 127.0700,  4, 3.3, "stop-And-Remain", "truck"),
]


@router.post("/seed-demo")
def seed_demo(db: Session = Depends(get_db), force: bool = False):
    """데모 시연용 서울 교차로 8개 이벤트 일괄 시드.

    이미 실데이터가 5건 이상 있으면 skip (force=true 로 강제).
    """
    # 교차로 다양성 기준 — 5개 이상 unique intersection 있으면 skip
    existing_iids = {row[0] for row in db.query(BlindSignalEvent.intersection_id).distinct().all()}
    if len(existing_iids) >= 5 and not force:
        return {"status": "skipped", "existing_intersections": len(existing_iids), "reason": "이미 5개 이상 교차로 존재"}

    created = []
    for iid, name, lat, lon, count, dur, sig, obs in DEMO_INTERSECTIONS:
        # 동일 intersection_id 가 이미 있으면 skip
        if db.query(BlindSignalEvent).filter(BlindSignalEvent.intersection_id == iid).first():
            continue
        # count 회 만큼 이벤트 시드 (각각 약간씩 duration 변동)
        for k in range(count):
            jitter = 0.7 + (k % 5) * 0.15
            ev = BlindSignalEvent(
                intersection_id=iid,
                user_lat=lat,
                user_lon=lon,
                event_duration=round(dur * jitter, 2),
                obstacle_type=obs,
                signal_state=sig,
                signal_remain_time=None,
                image_path=None,
            )
            db.add(ev)
        created.append({"id": iid, "name": name, "events": count})
    db.commit()
    return {"status": "ok", "created": created, "intersections": len(created), "now_total": db.query(BlindSignalEvent).count()}


# 교차로명 매핑 — 프론트가 표시용으로 가져감
@router.get("/intersection-names")
def intersection_names():
    return {iid: name for (iid, name, *_rest) in DEMO_INTERSECTIONS}


@router.post("/auto-detect")
def auto_detect_event(data: dict, db: Session = Depends(get_db)):
    """
    입력 예시:
    {
        "intersection_id": "1007",
        "user_lat": 37.55,
        "user_lon": 127.12,
        "vehicle_detected": true,
        "signal_detected": false,
        "duration": 3.2,
        "obstacle_type": "truck"
    }
    """

    if not data.get("vehicle_detected"):
        return {"message": "no vehicle -> skip"}

    if data.get("signal_detected"):
        return {"message": "signal visible -> skip"}

    if data.get("duration", 0) < 2:
        return {"message": "too short -> skip"}

    # 신호 조회
    signal_data = fetch_signal_info(data["intersection_id"])

    body = signal_data.get("body", {})
    items = body.get("items", {})
    item_list = items.get("item", [])

    if isinstance(item_list, dict):
        item_list = [item_list]

    signal_state = ""
    signal_time = 0

    if item_list:
        sig = item_list[0]
        signal_state = sig.get("stPdsgSttsNm", "")
        signal_time = sig.get("stPdsgRmndCs", 0)

    event = BlindSignalEvent(
        intersection_id=data["intersection_id"],
        user_lat=data.get("user_lat"),
        user_lon=data.get("user_lon"),
        heading=0,
        obstacle_type=data.get("obstacle_type", "unknown_vehicle"),
        signal_visible=False,
        event_duration=data.get("duration", 0),
        signal_state=signal_state,
        signal_remain_time=float(signal_time or 0)
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "message": "auto event saved",
        "event_id": event.id,
        "signal_state": signal_state
    }

@router.get("/export/csv")
def export_events_csv(db: Session = Depends(get_db)):
    events = db.query(BlindSignalEvent).order_by(BlindSignalEvent.id.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "id", "intersection_id", "user_lat", "user_lon", "heading",
        "obstacle_type", "signal_visible", "event_duration",
        "signal_state", "signal_remain_time", "image_path", "created_at"
    ])

    for ev in events:
        writer.writerow([
            ev.id,
            ev.intersection_id,
            ev.user_lat,
            ev.user_lon,
            ev.heading,
            ev.obstacle_type,
            ev.signal_visible,
            ev.event_duration,
            ev.signal_state,
            ev.signal_remain_time,
            ev.image_path,
            ev.created_at.isoformat() if ev.created_at else None
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=blind_signal_events.csv"}
    )