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