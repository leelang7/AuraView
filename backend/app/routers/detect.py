import os
import uuid
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BlindSignalEvent, Intersection
from ..services.matching import haversine
from ..services.detector import detect_objects
from ..services.public_api import fetch_signal_info
import cv2

router = APIRouter()

def draw_overlay(image_path, det, signal_state, signal_time):
    import cv2, os

    img = cv2.imread(image_path)
    h, w = img.shape[:2]

    is_blocked = det["vehicle_detected"] and not det["signal_detected"]

    if not is_blocked:
        return None

    if not signal_state:
        signal_state = "stop-And-Remain"
        signal_time = 10

    if signal_state == "stop-And-Remain":
        status_text = "STOP"
        status_color = (0, 0, 255)
    elif signal_state == "protected-Movement-Allowed":
        status_text = "GO"
        status_color = (0, 220, 0)
    elif signal_state == "permissive-Movement-Allowed":
        status_text = "CAUTION"
        status_color = (0, 220, 220)
    else:
        status_text = "CHECK SIGNAL"
        status_color = (255, 255, 255)

    overlay = img.copy()

    panel_w = int(w * 0.78)
    panel_h = 160
    x1 = (w - panel_w) // 2
    y1 = int(h * 0.68)
    x2 = x1 + panel_w
    y2 = y1 + panel_h

    cv2.rectangle(overlay, (x1, y1), (x2, y2), (18, 24, 35), -1)
    img = cv2.addWeighted(overlay, 0.45, img, 0.55, 0)

    cv2.rectangle(img, (x1, y1), (x2, y2), status_color, 2)

    cv2.putText(
        img,
        "AURAVIEW SYSTEM",
        (x1 + 24, y1 + 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (220, 230, 245),
        2
    )

    cv2.putText(
        img,
        "BLOCKED SIGNAL DETECTED",
        (x1 + 24, y1 + 84),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.05,
        status_color,
        3
    )

    cv2.putText(
        img,
        f"HUD SIGNAL  {status_text}",
        (x1 + 24, y1 + 126),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2
    )

    cv2.putText(
        img,
        f"REMAIN  {int(float(signal_time))}s",
        (x2 - 220, y1 + 126),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2
    )

    root, ext = os.path.splitext(image_path)
    out_path = root + "_overlay" + ext
    cv2.imwrite(out_path, img)
    return out_path

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/frame")
async def detect_frame(
    intersection_id: Optional[str] = Form(None),
    user_lat: Optional[float] = Form(None),
    user_lon: Optional[float] = Form(None),
    duration: float = Form(...),
    obstacle_type: str = Form("unknown_vehicle"),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    import os, uuid

    ext = os.path.splitext(image.filename)[1] or ".jpg"
    save_path = os.path.join("uploads", f"{uuid.uuid4().hex}{ext}")

    with open(save_path, "wb") as f:
        f.write(await image.read())

    det = detect_objects(save_path)

    # 🔥 1. 위치 기반 교차로 자동 매칭
    if user_lat and user_lon:
        intersections = db.query(Intersection).filter(
            Intersection.has_valid_coord == True
        ).all()

        if intersections:
            nearest = min(
                intersections,
                key=lambda x: haversine(user_lat, user_lon, x.lat, x.lon)
            )
            intersection_id = nearest.intersection_id

    if not intersection_id:
        intersection_id = "unknown"

    # 🔥 2. 신호 조회
    try:
        signal_data = fetch_signal_info(intersection_id)
    except:
        signal_data = {
            "body": {
                "items": {
                    "item": {
                        "stPdsgSttsNm": "stop-And-Remain",
                        "stPdsgRmndCs": "10"
                    }
                }
            }
        }
    body = signal_data.get("body", {})
    items = body.get("items", {})
    item_list = items.get("item", [])
    if isinstance(item_list, dict):
        item_list = [item_list]

    signal_state = ""
    signal_time = 0

    overlay_path = draw_overlay(save_path, det, signal_state, signal_time)
    overlay_url = None
    if overlay_path:
        overlay_url = "/" + overlay_path

    if item_list:
        sig = item_list[0]
        signal_state = sig.get("stPdsgSttsNm", "")
        signal_time = sig.get("stPdsgRmndCs", 0)

    # 🔥 3. 위험 점수 계산
    risk_score = 0
    if det["vehicle_detected"]:
        risk_score += 5
    if not det["signal_detected"]:
        risk_score += 5
    risk_score += min(duration, 5)

    # 🔥 4. 위험 판단
    is_blind_risk = (
        det["vehicle_detected"] and
        (not det["signal_detected"]) and
        duration >= 2
    )

    if is_blind_risk:
        event = BlindSignalEvent(
            intersection_id=intersection_id,
            user_lat=user_lat,
            user_lon=user_lon,
            heading=0,
            obstacle_type=obstacle_type,
            signal_visible=False,
            event_duration=duration,
            signal_state=signal_state,
            signal_remain_time=float(signal_time or 0),
            image_path=save_path,
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        return {
            "status": "warning",
            "event_saved": True,
            "event_id": event.id,
            "intersection_id": intersection_id,
            "signal_state": signal_state,
            "signal_remain_time": float(signal_time or 0),
            "risk_score": risk_score,
            "overlay_image": overlay_url,
            "detect_result": det,
        }

    return {
        "status": "safe",
        "event_saved": False,
        "intersection_id": intersection_id,
        "signal_state": signal_state,
        "signal_remain_time": float(signal_time or 0),
        "risk_score": risk_score,
        "overlay_image": overlay_url,
        "detect_result": det,
    }
