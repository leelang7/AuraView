from ultralytics import YOLO

vehicle_model = YOLO("yolov8n.pt")
signal_model = YOLO("yolov8n.pt")

VEHICLE_CLASSES = {"car", "bus", "truck"}
SIGNAL_CLASSES = {"traffic light"}


def detect_objects(image_path: str, conf: float = 0.25):
    v_res = vehicle_model.predict(source=image_path, conf=conf, verbose=False)[0]
    s_res = signal_model.predict(source=image_path, conf=conf, verbose=False)[0]

    vehicles = []
    signals = []

    for box in v_res.boxes:
        cls_id = int(box.cls[0].item())
        cls_name = v_res.names[cls_id]
        score = float(box.conf[0].item())
        if cls_name in VEHICLE_CLASSES:
            vehicles.append({
                "class_name": cls_name,
                "confidence": score
            })

    for box in s_res.boxes:
        cls_id = int(box.cls[0].item())
        cls_name = s_res.names[cls_id]
        score = float(box.conf[0].item())
        if cls_name in SIGNAL_CLASSES:
            signals.append({
                "class_name": cls_name,
                "confidence": score
            })

    return {
        "vehicle_detected": len(vehicles) > 0,
        "signal_detected": len(signals) > 0,
        "vehicles": vehicles,
        "signals": signals
    }