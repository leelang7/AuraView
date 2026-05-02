"""
Hazard report endpoints.

  POST /reports/generate?top=20    (현재 누적 데이터로 Top-N 리포트 생성)
  GET  /reports/list                최근 생성물 목록
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..routers.events import map_data as _map_data_route
from ..services import hazard_report

router = APIRouter()


@router.post("/generate")
def generate(top: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    rows = _map_data_route(db=db)
    if not rows:
        # 데이터가 비었을 때도 시연 가능하도록 가짜 baseline 추가
        rows = _seed_demo_rows()
    return hazard_report.generate(rows, top=top)


@router.get("/list")
def list_recent():
    return {"items": hazard_report.list_recent()}


def _seed_demo_rows():
    """이벤트 DB 가 비었을 때 시연용 합성 위험 데이터."""
    return [
        {"intersection_id": "1007", "risk_score": 13.4, "event_count": 11, "avg_duration": 4.8,
         "signal_state": "stop-And-Remain", "last_lat": 37.5601, "last_lon": 127.0410},
        {"intersection_id": "2031", "risk_score": 11.7, "event_count": 9, "avg_duration": 3.6,
         "signal_state": "stop-And-Remain", "last_lat": 37.5045, "last_lon": 127.0490},
        {"intersection_id": "5544", "risk_score": 10.2, "event_count": 7, "avg_duration": 4.1,
         "signal_state": "permissive-Movement-Allowed", "last_lat": 37.5111, "last_lon": 126.9821},
        {"intersection_id": "8821", "risk_score": 9.8, "event_count": 6, "avg_duration": 3.2,
         "signal_state": "stop-And-Remain", "last_lat": 37.5521, "last_lon": 126.9388},
        {"intersection_id": "1199", "risk_score": 9.1, "event_count": 5, "avg_duration": 3.0,
         "signal_state": "protected-Movement-Allowed", "last_lat": 37.5661, "last_lon": 126.9784},
        {"intersection_id": "3404", "risk_score": 8.6, "event_count": 5, "avg_duration": 2.7,
         "signal_state": "stop-And-Remain", "last_lat": 37.5811, "last_lon": 127.0124},
        {"intersection_id": "7790", "risk_score": 8.0, "event_count": 4, "avg_duration": 2.5,
         "signal_state": "permissive-Movement-Allowed", "last_lat": 37.4921, "last_lon": 127.0331},
        {"intersection_id": "0218", "risk_score": 7.5, "event_count": 4, "avg_duration": 2.4,
         "signal_state": "stop-And-Remain", "last_lat": 37.5301, "last_lon": 126.9990},
        {"intersection_id": "4502", "risk_score": 6.9, "event_count": 3, "avg_duration": 2.1,
         "signal_state": "protected-Movement-Allowed", "last_lat": 37.5191, "last_lon": 127.0431},
        {"intersection_id": "6611", "risk_score": 6.5, "event_count": 3, "avg_duration": 2.0,
         "signal_state": "stop-And-Remain", "last_lat": 37.5841, "last_lon": 127.0561},
    ]
