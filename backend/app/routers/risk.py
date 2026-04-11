from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import BlindSignalEvent
from ..services.scoring import calculate_risk

router = APIRouter()


@router.get("/")
def risk_summary(db: Session = Depends(get_db)):
    grouped = (
        db.query(
            BlindSignalEvent.intersection_id,
            func.count(BlindSignalEvent.id).label("count"),
            func.avg(BlindSignalEvent.event_duration).label("avg_duration")
        )
        .group_by(BlindSignalEvent.intersection_id)
        .all()
    )

    result = []

    for row in grouped:
        sample_event = (
            db.query(BlindSignalEvent)
            .filter(BlindSignalEvent.intersection_id == row.intersection_id)
            .order_by(BlindSignalEvent.id.desc())
            .first()
        )

        signal_state = sample_event.signal_state if sample_event else ""
        obstacle_type = sample_event.obstacle_type if sample_event else ""

        score = calculate_risk(
            event_duration=row.avg_duration or 0,
            obstacle_type=obstacle_type,
            signal_state=signal_state,
            count=row.count
        )

        result.append({
            "intersection_id": row.intersection_id,
            "event_count": row.count,
            "avg_duration": round(row.avg_duration or 0, 2),
            "signal_state": signal_state,
            "risk_score": score
        })

    result.sort(key=lambda x: x["risk_score"], reverse=True)
    return result