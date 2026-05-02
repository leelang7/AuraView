"""
YOLOv8 detector wrapper — ultralytics 가 없을 때도 import 안 깨지도록 lazy 로드.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

log = logging.getLogger("auraview.detector")

VEHICLE_CLASSES = {"car", "bus", "truck"}
SIGNAL_CLASSES = {"traffic light"}

_vehicle_model = None
_signal_model = None


def _lazy_load():
    """ultralytics 가 깔려있을 때만 모델 적재. 미설치 환경에서는 ImportError 를 던짐."""
    global _vehicle_model, _signal_model
    if _vehicle_model is not None:
        return
    from ultralytics import YOLO  # heavy import
    _vehicle_model = YOLO("yolov8n.pt")
    _signal_model = _vehicle_model  # 같은 백본 공유 — 메모리 절감


def detect_objects(image_path: str, conf: float = 0.25) -> Dict[str, Any]:
    """이미지 1장에서 차량 / 신호등 검출. ultralytics 미설치 시 빈 결과 반환."""
    try:
        _lazy_load()
    except Exception as exc:
        log.warning("YOLO unavailable, returning empty detection: %s", exc)
        return {
            "vehicle_detected": False,
            "signal_detected": False,
            "vehicles": [],
            "signals": [],
            "_warning": "ultralytics not installed",
        }

    v_res = _vehicle_model.predict(source=image_path, conf=conf, verbose=False)[0]
    s_res = _signal_model.predict(source=image_path, conf=conf, verbose=False)[0]

    vehicles = []
    signals = []

    for box in v_res.boxes:
        cls_name = v_res.names[int(box.cls[0].item())]
        score = float(box.conf[0].item())
        if cls_name in VEHICLE_CLASSES:
            vehicles.append({"class_name": cls_name, "confidence": score})

    for box in s_res.boxes:
        cls_name = s_res.names[int(box.cls[0].item())]
        score = float(box.conf[0].item())
        if cls_name in SIGNAL_CLASSES:
            signals.append({"class_name": cls_name, "confidence": score})

    return {
        "vehicle_detected": len(vehicles) > 0,
        "signal_detected": len(signals) > 0,
        "vehicles": vehicles,
        "signals": signals,
    }
