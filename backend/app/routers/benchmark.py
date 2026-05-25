"""
Latency benchmark — Risk Transformer 추론·6종 융합 호출 등 핵심 경로 실측.

  GET /benchmark/risk?n=200       Risk Transformer predict() 평균 latency
  GET /benchmark/v2v-merge?n=50   V2V merge_into_occupancy() 평균 latency
  GET /benchmark/all              요약본 한 번에

검증 시 'AUC 0.94' 만큼이나 'P95 추론 지연 N ms' 도 객관 수치로 노출.
"""

from __future__ import annotations

import os
import statistics as st
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Query

router = APIRouter()


def _bench(fn, n: int) -> Dict[str, float]:
    """fn() 을 n 회 실행, ms 분포 통계 반환."""
    samples: List[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "n": n,
        "mean_ms": round(st.mean(samples), 2),
        "median_ms": round(samples[len(samples) // 2], 2),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 2),
        "p99_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.99))], 2),
        "min_ms": round(samples[0], 2),
        "max_ms": round(samples[-1], 2),
    }


@router.get("/risk")
def bench_risk(n: int = Query(200, ge=10, le=2000)):
    """Risk Transformer predict() — trained / linear-fallback 자동 분기."""
    from ..services import risk_transformer as rt

    sample = rt.RiskInput(
        duration=4.0, vehicle_cnt=3, vru_cnt=1,
        vds_speed=20.0, vds_volume=2400, occluded_mass=200.0,
        taas_nearby=2, signal_state="stop-And-Remain",
        incident_flag=True, obstacle_type="truck",
    )

    backend = rt.warm_up()
    # Warmup 5회
    for _ in range(5):
        rt.predict(sample)

    stats = _bench(lambda: rt.predict(sample), n)
    stats["backend"] = backend
    stats["sample_p_collision"] = round(rt.predict(sample).p_collision, 4)
    return stats


@router.get("/v2v-merge")
def bench_v2v(n: int = Query(50, ge=10, le=500)):
    """V2V merge_into_occupancy — peer 3대 게시 후 격자 머지 latency."""
    import numpy as np

    from ..services import v2v as v2v_service

    iid = "ut-bench"
    v2v_service._POOL[iid] = []
    # peer 3대 시드 (마주오는 2 + 같은방향 1)
    for i, msg in enumerate([
        {"intersection_id": iid, "lat": 37.5601, "lon": 127.0411, "heading_deg": 90,
         "speed_kmh": 6, "decel_g": 0.4,
         "detections": [{"class": "person", "conf": 0.9, "rel_lat": 0, "rel_lon": 0, "width_m": 0.6}]},
        {"intersection_id": iid, "lat": 37.5602, "lon": 127.0412, "heading_deg": 92,
         "speed_kmh": 4, "decel_g": 0.5,
         "detections": [{"class": "person", "conf": 0.8, "rel_lat": 0, "rel_lon": 0, "width_m": 0.6}]},
        {"intersection_id": iid, "lat": 37.5599, "lon": 127.0409, "heading_deg": 270,
         "speed_kmh": 22, "detections": []},
    ]):
        v2v_service.publish(msg)

    def fn():
        grid = np.zeros((80, 80), dtype=np.float32)
        v2v_service.merge_into_occupancy(
            grid, ego_lat=37.5601, ego_lon=127.0410, ego_heading=270,
            intersection_id=iid, cell_m=0.5, forward_m=40.0, lateral_m=20.0,
        )

    # Warmup
    for _ in range(3): fn()
    return _bench(fn, n)


@router.get("/all")
def bench_all():
    """요약 한 번에 — 발표 슬라이드용."""
    return {
        "risk_transformer": bench_risk(n=100),
        "v2v_merge": bench_v2v(n=30),
        "note": "Warmup 후 측정 · CPU 단일 코어 기준 · 수치는 호스트 사양 영향 큼",
    }
