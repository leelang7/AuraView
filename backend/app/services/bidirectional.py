"""
Bidirectional Lane Fusion — 상행/하행 차량 정보로 사각지대 메우기.

핵심 직관:
  - 마주오는 차들 (oncoming) 이 갑자기 감속 / 정지 / 방향 전환
       → 그쪽에 사고 / 보행자 / 장애물 가능성 ↑↑
  - 같은 방향 (앞차들) 의 흐름이 일관되게 느림
       → 정상 정체 (위험 신호 약함)
  - VDS 의 상행/하행 평균 속도 차 분석 → 비정상 패턴 감지

이 서비스는 두 가지 데이터 소스를 융합:
  1. AuraView V2V peer broadcasts (실시간 협업 데이터)
  2. 한국도로공사 VDS 상행/하행 속도 (services/public_api.fetch_vds_traffic)
"""

from __future__ import annotations

import logging
import math
import statistics as st
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("auraview.bidirectional")


@dataclass
class BidirAnalysis:
    oncoming_count: int = 0
    oncoming_avg_speed_kmh: float = 0.0
    oncoming_decel_share: float = 0.0      # 감속 중인 비율
    same_dir_count: int = 0
    same_dir_avg_speed_kmh: float = 0.0
    speed_asymmetry: float = 0.0           # |상행 - 하행| / max
    hazard_probability: float = 0.0        # 0~1
    recommended_speed_kmh: Optional[float] = None
    insight: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "oncoming_count": self.oncoming_count,
            "oncoming_avg_speed_kmh": round(self.oncoming_avg_speed_kmh, 1),
            "oncoming_decel_share": round(self.oncoming_decel_share, 3),
            "same_dir_count": self.same_dir_count,
            "same_dir_avg_speed_kmh": round(self.same_dir_avg_speed_kmh, 1),
            "speed_asymmetry": round(self.speed_asymmetry, 3),
            "hazard_probability": round(self.hazard_probability, 3),
            "recommended_speed_kmh": (
                None if self.recommended_speed_kmh is None
                else round(self.recommended_speed_kmh, 1)
            ),
            "insight": self.insight,
        }


def _bearing_diff_deg(a: float, b: float) -> float:
    return abs((a - b + 540) % 360 - 180)


def analyze(peers: List[Dict[str, Any]],
            ego_heading_deg: Optional[float],
            vds_records: Optional[List[Dict[str, Any]]] = None) -> BidirAnalysis:
    """
    peers : V2V 풀에서 받은 다른 차량 메시지
    ego_heading_deg : 자차 진행 방향 (없으면 모든 peer 를 same_dir 로 분류)
    vds_records : services/public_api.fetch_vds_traffic 의 list 항목들
    """
    res = BidirAnalysis()
    oncoming, same = [], []

    for p in peers:
        h = p.get("heading_deg")
        if h is None or ego_heading_deg is None:
            same.append(p); continue
        if _bearing_diff_deg(float(h), ego_heading_deg) > 130:
            oncoming.append(p)
        else:
            same.append(p)

    if oncoming:
        speeds = [float(p.get("speed_kmh", 0)) for p in oncoming if "speed_kmh" in p]
        res.oncoming_count = len(oncoming)
        res.oncoming_avg_speed_kmh = (sum(speeds) / len(speeds)) if speeds else 0.0
        decels = sum(1 for p in oncoming if float(p.get("decel_g", 0)) >= 0.25)
        res.oncoming_decel_share = decels / len(oncoming)

    if same:
        s_speeds = [float(p.get("speed_kmh", 0)) for p in same if "speed_kmh" in p]
        res.same_dir_count = len(same)
        res.same_dir_avg_speed_kmh = (sum(s_speeds) / len(s_speeds)) if s_speeds else 0.0

    # VDS 상행/하행 비대칭 — 외부 데이터로 보강
    vds_asym = 0.0
    if vds_records:
        try:
            ups = [float(v.get("speed", 0)) for v in vds_records if "up" in str(v.get("dir", "")).lower() or v.get("upDown") in ("U", "0", 0)]
            downs = [float(v.get("speed", 0)) for v in vds_records if "down" in str(v.get("dir", "")).lower() or v.get("upDown") in ("D", "1", 1)]
            if not ups and not downs and len(vds_records) >= 2:
                # dir 정보 없을 때 임시 분리
                speeds = [float(v.get("speed", 0)) for v in vds_records]
                ups, downs = speeds[: len(speeds) // 2], speeds[len(speeds) // 2 :]
            if ups and downs:
                u_avg = st.mean(ups); d_avg = st.mean(downs)
                vds_asym = abs(u_avg - d_avg) / max(1.0, max(u_avg, d_avg))
        except Exception as exc:
            log.debug("VDS asymmetry calc failed: %s", exc)
    res.speed_asymmetry = vds_asym

    # ── Hazard probability heuristic ─────────────────────────
    p_haz = 0.0
    insights: List[str] = []

    if res.oncoming_decel_share >= 0.5 and res.oncoming_count >= 2:
        p_haz += 0.55
        insights.append(f"마주오는 차 {res.oncoming_count}대 중 {int(res.oncoming_decel_share*100)}% 가 급감속 — 전방에 즉각적 위험 가능성")
    elif res.oncoming_decel_share >= 0.25:
        p_haz += 0.25
        insights.append("마주오는 차 일부 감속")

    if res.same_dir_count >= 2 and res.same_dir_avg_speed_kmh < 15:
        p_haz += 0.18
        insights.append(f"앞차들 평균 {res.same_dir_avg_speed_kmh:.1f}km/h — 정체 또는 사고 추정")

    if vds_asym > 0.4:
        p_haz += 0.20
        insights.append(f"상행/하행 속도 차 {int(vds_asym*100)}% — 비대칭 흐름")

    res.hazard_probability = min(0.97, p_haz)

    # 권장 속도 (있는 데이터 기반 단순 룰)
    if res.hazard_probability >= 0.4:
        if res.same_dir_avg_speed_kmh > 0:
            res.recommended_speed_kmh = max(10.0, res.same_dir_avg_speed_kmh * 0.7)
        else:
            res.recommended_speed_kmh = max(15.0, (res.oncoming_avg_speed_kmh or 30) * 0.5)

    res.insight = " · ".join(insights) if insights else "정상 흐름"
    return res
