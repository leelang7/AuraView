import os
import re
import cv2
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BlindSignalEvent, Intersection
from ..services.detector import detect_objects
from ..services.public_api import fetch_signal_info
from ..services.matching import haversine

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def safe_name(name: str) -> str:
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"[^0-9a-zA-Z가-힣_-]+", "_", stem).strip("_")
    return stem[:50] or "file"


def draw_overlay(image_path, det, signal_state, signal_time):
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

    hud_top = int(h * 0.72)
    hud_bottom = int(h * 0.90)

    overlay = img.copy()
    cv2.rectangle(overlay, (0, hud_top), (w, hud_bottom), (0, 0, 0), -1)
    img = cv2.addWeighted(overlay, 0.45, img, 0.55, 0)

    cv2.putText(
        img,
        f"AURAVIEW  |  SIGNAL: {status_text}",
        (36, hud_top + 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.18,
        status_color,
        3
    )

    cv2.putText(
        img,
        f"REMAIN {int(float(signal_time))}s",
        (36, hud_top + 88),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2
    )

    root, ext = os.path.splitext(image_path)
    out_path = root + "_overlay" + ext
    cv2.imwrite(out_path, img)
    return out_path


def process_video(video_path, base_name: str, sample_rate: int = 10):
    cap = cv2.VideoCapture(video_path)
    results = []

    frame_idx = 0
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_rate == 0:
            frame_name = f"{ts}_{base_name}_frame_{frame_idx:04d}.jpg"
            frame_path = os.path.join(UPLOAD_DIR, frame_name)
            cv2.imwrite(frame_path, frame)

            det = detect_objects(frame_path)

            results.append({
                "frame_path": frame_path,
                "det": det
            })

        frame_idx += 1

    cap.release()
    return results


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
    ext = os.path.splitext(image.filename)[1] or ".jpg"
    base = safe_name(image.filename or "image")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_name = f"{ts}_{base}{ext}"
    save_path = os.path.join(UPLOAD_DIR, save_name)

    with open(save_path, "wb") as f:
        f.write(await image.read())

    det = detect_objects(save_path)

    if user_lat is not None and user_lon is not None:
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

    signal_data = fetch_signal_info(intersection_id)
    body = signal_data.get("body", {})
    items = body.get("items", {})
    item_list = items.get("item", [])
    if isinstance(item_list, dict):
        item_list = [item_list]

    signal_state = "stop-And-Remain"
    signal_time = 10

    if item_list:
        sig = item_list[0]
        signal_state = sig.get("stPdsgSttsNm", signal_state)
        signal_time = sig.get("stPdsgRmndCs", signal_time)

    risk_score = 0
    if det["vehicle_detected"]:
        risk_score += 5
    if not det["signal_detected"]:
        risk_score += 5
    risk_score += min(duration, 5)

    is_blind_risk = (
        det["vehicle_detected"] and
        (not det["signal_detected"]) and
        duration >= 2
    )

    overlay_path = draw_overlay(save_path, det, signal_state, signal_time)
    overlay_url = None
    if overlay_path:
        overlay_url = "/" + overlay_path.replace("\\", "/")

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


@router.post("/video")
async def detect_video(
    video: UploadFile = File(...),
):
    ext = os.path.splitext(video.filename)[1] or ".mp4"
    base = safe_name(video.filename or "video")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_name = f"{ts}_{base}{ext}"
    video_path = os.path.join(UPLOAD_DIR, video_name)

    with open(video_path, "wb") as f:
        f.write(await video.read())

    frames = process_video(video_path, base_name=base, sample_rate=10)

    highlights = []

    for item in frames:
        frame_path = item["frame_path"]
        det = item["det"]

        is_blocked = det["vehicle_detected"] and not det["signal_detected"]

        if is_blocked:
            overlay_path = draw_overlay(
                frame_path,
                det,
                "stop-And-Remain",
                10
            )

            if overlay_path:
                highlights.append({
                    "frame": "/" + frame_path.replace("\\", "/"),
                    "overlay": "/" + overlay_path.replace("\\", "/"),
                    "det": det
                })

    total_frames = len(frames)
    risk_frames = len(highlights)
    risk_ratio = round((risk_frames / total_frames) * 100, 1) if total_frames else 0

    return {
        "total_frames": total_frames,
        "risk_frames": risk_frames,
        "risk_ratio": risk_ratio,
        "highlights": highlights[:3]
    }