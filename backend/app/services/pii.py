"""
가명정보 결합 유틸 ─ 국토교통 데이터안심구역 표준에 맞춘 결합 파이프라인.

구현:
  - 차량번호판·사람 얼굴 블러 (OpenCV, Haar/LBP 기반 경량)
  - 식별자 가명화: HMAC-SHA256(salt, id) 의 앞 16자리 hex
  - k-익명성 검증: 동일 (시군구 × 시간 bucket × 사고유형) 레코드 수가 k 미만이면 제외
  - TAAS × VDS 결합 시 결합키(시군구 + 일자 bucket)만 사용, 원천 PII 미보관

모든 결합 파이프라인은 국토교통 데이터안심구역(`dsz.ex.co.kr`) 반입 전제로 작성됨.
반출 시 요약 통계·추세·분포만 허용. 개별 레코드는 반출 금지.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, Iterable, List, Optional


HMAC_SECRET = os.getenv("FLEET_HMAC_SECRET", "").encode("utf-8") or b"auraview-dev-salt"
K_ANON_THRESHOLD = int(os.getenv("K_ANON_THRESHOLD", "5"))


def pseudonymize(raw_id: str) -> str:
    """차량·사용자 식별자를 HMAC-SHA256 앞 16자리로 비가역 가명화."""
    if not raw_id:
        return ""
    mac = hmac.new(HMAC_SECRET, raw_id.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:16]


def bucket_timestamp(iso_ts: str, bucket_min: int = 30) -> str:
    """시간 bucket 생성 (기본 30분). k-익명성의 quasi-identifier로 사용."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return "unknown"
    minute = (dt.minute // bucket_min) * bucket_min
    return dt.strftime(f"%Y-%m-%dT%H:{minute:02d}")


def k_anonymize(records: Iterable[Dict[str, Any]],
                 quasi_identifiers: List[str],
                 k: int = K_ANON_THRESHOLD) -> List[Dict[str, Any]]:
    """준식별자 조합 기준 k 미만 그룹 제거."""
    counts: Dict[tuple, int] = {}
    buffered = list(records)
    for r in buffered:
        key = tuple(r.get(q) for q in quasi_identifiers)
        counts[key] = counts.get(key, 0) + 1
    return [r for r in buffered if counts[tuple(r.get(q) for q in quasi_identifiers)] >= k]


def blur_faces_and_plates(image_bgr):
    """
    OpenCV Haar로 얼굴·번호판 블러 (간이). 고도화는 YOLOv8 LPD 모델로 교체 가능.
    """
    import cv2  # lazy
    out = image_bgr.copy()
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)

    for cascade_name in ("haarcascade_frontalface_default.xml",
                         "haarcascade_russian_plate_number.xml"):
        path = cv2.data.haarcascades + cascade_name
        if not os.path.exists(path):
            continue
        cascade = cv2.CascadeClassifier(path)
        for (x, y, w, h) in cascade.detectMultiScale(gray, 1.1, 4):
            roi = out[y:y+h, x:x+w]
            if roi.size == 0:
                continue
            out[y:y+h, x:x+w] = cv2.GaussianBlur(roi, (35, 35), 0)

    return out


def join_taas_vds(taas_records: List[Dict[str, Any]],
                   vds_records: List[Dict[str, Any]],
                   join_keys: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    가명결합의 전형 예시. 결합키는 비식별 quasi-identifier만 사용.

    결합키: [시군구코드, 일자 bucket (YYYY-MM-DD-HH), 도로링크 구간]
    """
    join_keys = join_keys or ["district_code", "date_hour", "link_id"]
    vds_index: Dict[tuple, List[Dict[str, Any]]] = {}
    for v in vds_records:
        key = tuple(v.get(k) for k in join_keys)
        vds_index.setdefault(key, []).append(v)

    joined: List[Dict[str, Any]] = []
    for a in taas_records:
        key = tuple(a.get(k) for k in join_keys)
        for v in vds_index.get(key, []):
            joined.append({
                **{k: a.get(k) for k in join_keys},
                "accident_severity": a.get("severity"),
                "victim_type": a.get("victimType"),
                "traffic_speed": v.get("speed"),
                "traffic_volume": v.get("volume"),
                "occupancy": v.get("occupancy"),
                # 원천 PII(사건 ID, 차량 번호 등)는 포함하지 않음
            })

    return k_anonymize(joined, join_keys, K_ANON_THRESHOLD)
