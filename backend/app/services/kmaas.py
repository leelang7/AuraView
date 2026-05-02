"""
K-MaaS (Korea Mobility-as-a-Service) 어댑터.

핵심 가설:
  - AuraView 가 전방 교차로의 충돌·보행자 위험을 감지하면
  - 운전자 대신 **K-MaaS 대중교통 대안 경로**를 즉시 제안
  - 또는 **상습 위험 교차로**를 K-MaaS 노선 운영팀에 데이터로 환원

K-MaaS API 는 인증·발급 절차가 있어 시연용 fallback 응답 함께 제공.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("auraview.kmaas")

KMAAS_BASE_URL = os.getenv("KMAAS_BASE_URL", "https://kmaas.kotsa.or.kr/openapi")
KMAAS_KEY = os.getenv("KMAAS_KEY", "")
ALLOW_FALLBACK = os.getenv("ALLOW_FALLBACK", "1") == "1"
DEFAULT_TIMEOUT = float(os.getenv("PUBLIC_API_TIMEOUT", "3.0"))


@dataclass
class TransitLeg:
    mode: str           # bus / metro / taxi / walk / bike
    name: str           # 노선명·역명
    duration_min: int
    distance_km: float
    fare_won: int = 0
    co2_saved_g: int = 0


@dataclass
class TransitAlternative:
    label: str
    total_min: int
    total_fare: int
    total_co2_saved: int    # 자가용 대비 g
    legs: List[TransitLeg]
    risk_avoidance_score: float = 0.0   # 0~1, 높을수록 우회 가치 큼

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "total_min": self.total_min,
            "total_fare": self.total_fare,
            "total_co2_saved_g": self.total_co2_saved,
            "risk_avoidance_score": round(self.risk_avoidance_score, 3),
            "legs": [leg.__dict__ for leg in self.legs],
        }


# ──────────────────────────────────────────────────────────────────────
# Fallback samples
# ──────────────────────────────────────────────────────────────────────

_DEMO_ALTS = [
    TransitAlternative(
        label="🚇 지하철 + 도보",
        total_min=18,
        total_fare=1450,
        total_co2_saved=820,
        risk_avoidance_score=0.92,
        legs=[
            TransitLeg(mode="walk", name="현 위치 → 동대문역", duration_min=4, distance_km=0.3),
            TransitLeg(mode="metro", name="1호선 동대문 → 종각", duration_min=8, distance_km=2.4, fare_won=1450, co2_saved_g=720),
            TransitLeg(mode="walk", name="종각역 → 목적지", duration_min=6, distance_km=0.5),
        ],
    ),
    TransitAlternative(
        label="🚌 광역버스",
        total_min=24,
        total_fare=2800,
        total_co2_saved=580,
        risk_avoidance_score=0.78,
        legs=[
            TransitLeg(mode="walk", name="현 위치 → 종로4가 정류장", duration_min=3, distance_km=0.2),
            TransitLeg(mode="bus", name="간선 270 종로4가 → 광화문", duration_min=15, distance_km=3.1, fare_won=2800, co2_saved_g=580),
            TransitLeg(mode="walk", name="광화문 정류장 → 목적지", duration_min=6, distance_km=0.4),
        ],
    ),
    TransitAlternative(
        label="🚲 따릉이 + 도보",
        total_min=15,
        total_fare=1000,
        total_co2_saved=940,
        risk_avoidance_score=0.85,
        legs=[
            TransitLeg(mode="walk", name="현 위치 → 따릉이 대여소", duration_min=2, distance_km=0.15),
            TransitLeg(mode="bike", name="따릉이 동대문 → 종로 라인", duration_min=10, distance_km=2.6, fare_won=1000, co2_saved_g=940),
            TransitLeg(mode="walk", name="반납소 → 목적지", duration_min=3, distance_km=0.2),
        ],
    ),
]


def fetch_alternatives(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    risk_score: float = 0.0,
) -> List[TransitAlternative]:
    """위험 교차로를 우회하는 K-MaaS 대중교통 대안 조회."""
    url = f"{KMAAS_BASE_URL}/multimodal/route"
    params = {
        "serviceKey": KMAAS_KEY,
        "originLat": origin_lat, "originLon": origin_lon,
        "destLat": dest_lat, "destLon": dest_lon,
        "_type": "json",
    }
    try:
        res = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        res.raise_for_status()
        data = res.json()
        # 실 K-MaaS 응답 파싱은 정식 발급 후 채울 자리 (TODO)
        items = data.get("routes") or data.get("body", {}).get("items") or []
        alts: List[TransitAlternative] = []
        for it in items[:3]:
            alts.append(TransitAlternative(
                label=it.get("label") or it.get("modeText", "K-MaaS 추천"),
                total_min=int(it.get("totalMin", 0)),
                total_fare=int(it.get("totalFare", 0)),
                total_co2_saved=int(it.get("co2Saved", 0)),
                risk_avoidance_score=min(1.0, risk_score),
                legs=[],
            ))
        if alts:
            return alts
    except Exception as exc:
        log.warning("K-MaaS API failed: %s", exc)

    if ALLOW_FALLBACK:
        # 위험도가 클수록 risk_avoidance_score 가산
        return [
            TransitAlternative(
                label=a.label, total_min=a.total_min, total_fare=a.total_fare,
                total_co2_saved=a.total_co2_saved,
                risk_avoidance_score=min(1.0, a.risk_avoidance_score + risk_score * 0.05),
                legs=a.legs,
            )
            for a in _DEMO_ALTS
        ]
    return []


def aggregate_for_transit_planner(top_hazards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    상습 위험 교차로 데이터를 K-MaaS 노선 운영팀에 환원하는 요약 빌더.
    심사 메시지: "AuraView 가 시민에게는 안전 경로, 운영자에겐 노선 개선 데이터를 동시에 제공"
    """
    by_district: Dict[str, int] = {}
    suggestions: List[Dict[str, Any]] = []

    for h in top_hazards:
        code = (h.get("district_code") or h.get("intersection_id", "")[:5] or "unknown")
        by_district[code] = by_district.get(code, 0) + 1

        score = float(h.get("risk_score", 0))
        if score >= 8:
            suggestions.append({
                "intersection_id": h.get("intersection_id"),
                "lat": h.get("last_lat"),
                "lon": h.get("last_lon"),
                "risk_score": score,
                "operator_action": _propose_action(score, h.get("event_count", 0)),
            })

    return {
        "transit_operator_summary": {
            "high_risk_intersection_count": sum(1 for h in top_hazards if h.get("risk_score", 0) >= 8),
            "districts": sorted(by_district.items(), key=lambda kv: -kv[1])[:10],
            "actionable_suggestions": suggestions[:20],
        },
        "rider_summary": {
            "broadcast_message": (
                "AuraView 데이터 기반 — 다음 교차로 위험도 8 이상 구간을 우회하는 "
                "대중교통 대안 경로가 K-MaaS 앱에 자동 추천됩니다."
            ),
        },
    }


def _propose_action(risk: float, count: int) -> str:
    if risk >= 12 and count >= 5:
        return "버스 노선 우회 검토 + 보행 신호 연장 권고"
    if risk >= 10:
        return "보행 신호 연장 + 정류장 위치 재검토"
    return "현장 점검 권고"
