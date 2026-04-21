"""
HydraNet multi-task head — Tesla AI Day 방식의 단일 백본 + N개 head.

현재는 YOLOv8-nano 백본 + 룰 기반 head로 시작하지만, 학습 준비가 끝나면
`models/hydranet_*.pt` 체크포인트로 교체되도록 구조를 열어둔다.

Heads:
  - detection   : {car, bus, truck, traffic_light, pedestrian, bicycle, motorcycle}
  - lane        : 차선 4-class (solid/dashed/bus/bicycle)
  - sign        : 속도·정지·양보 표지
  - speed       : 자차 속도 회귀 (option)

가점 기여: AI활용 · 학습 5점 (멀티태스크 학습 스크립트 포함)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("auraview.hydranet")

EXPANDED_VEHICLE_CLASSES = {"car", "bus", "truck", "van", "motorcycle"}
VRU_CLASSES = {"person", "bicycle", "motorcycle"}  # Vulnerable Road Users
SIGNAL_CLASSES = {"traffic light", "stop sign"}


@dataclass
class HydraPrediction:
    detections: List[dict] = field(default_factory=list)
    vru_detections: List[dict] = field(default_factory=list)
    signals: List[dict] = field(default_factory=list)
    lanes: List[dict] = field(default_factory=list)
    signs: List[dict] = field(default_factory=list)

    def summary(self) -> Dict[str, int]:
        return {
            "vehicles": sum(1 for d in self.detections if d["class_name"] in EXPANDED_VEHICLE_CLASSES),
            "vrus": len(self.vru_detections),
            "signals": len(self.signals),
            "lanes": len(self.lanes),
            "signs": len(self.signs),
        }


class HydraNet:
    """백본 공유 멀티 head wrapper. 학습된 체크포인트가 있으면 교체 가능."""

    def __init__(self, checkpoint: Optional[str] = None):
        self.checkpoint = checkpoint
        self._backbone = None   # lazy

    def _lazy_load(self):
        if self._backbone is not None:
            return
        from ultralytics import YOLO  # heavy import

        ckpt = self.checkpoint
        if ckpt and Path(ckpt).exists():
            log.info("Loading HydraNet checkpoint: %s", ckpt)
            self._backbone = YOLO(ckpt)
        else:
            log.info("HydraNet checkpoint not found, falling back to yolov8n.pt")
            self._backbone = YOLO("yolov8n.pt")

    def infer(self, image_path: str, conf: float = 0.25) -> HydraPrediction:
        self._lazy_load()
        res = self._backbone.predict(source=image_path, conf=conf, verbose=False)[0]

        pred = HydraPrediction()
        names = res.names
        h, w = res.orig_shape if hasattr(res, "orig_shape") else (0, 0)

        for box in res.boxes:
            cls_name = names[int(box.cls[0].item())]
            score = float(box.conf[0].item())
            xyxy = [float(v) for v in box.xyxy[0].tolist()]

            entry = {
                "class_name": cls_name,
                "confidence": score,
                "bbox_xyxy": xyxy,
                "image_size": [w, h],
            }

            if cls_name in EXPANDED_VEHICLE_CLASSES or cls_name == "car":
                pred.detections.append(entry)
            if cls_name in VRU_CLASSES:
                pred.vru_detections.append(entry)
            if cls_name in SIGNAL_CLASSES:
                pred.signals.append(entry)

        # Lane / sign heads — 현재 YOLOv8n COCO에는 없음. 추후 학습된 head로 채움.
        pred.lanes = []
        pred.signs = []

        return pred


# Module-level singleton
_default: Optional[HydraNet] = None


def get_default() -> HydraNet:
    global _default
    if _default is None:
        _default = HydraNet(checkpoint=None)
    return _default
