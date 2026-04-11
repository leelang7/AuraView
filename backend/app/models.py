from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
from .database import Base


class Intersection(Base):
    __tablename__ = "intersections"

    id = Column(Integer, primary_key=True, index=True)
    intersection_id = Column(String, unique=True, index=True)
    name = Column(String)
    municipality_code = Column(String)

    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    has_valid_coord = Column(Boolean, default=False)


class BlindSignalEvent(Base):
    __tablename__ = "blind_signal_events"
    image_path = Column(String, nullable=True)

    id = Column(Integer, primary_key=True, index=True)
    intersection_id = Column(String, index=True)

    user_lat = Column(Float, nullable=True)
    user_lon = Column(Float, nullable=True)
    heading = Column(Float, nullable=True)

    obstacle_type = Column(String, nullable=True)
    signal_visible = Column(Boolean, default=False)
    event_duration = Column(Float, default=0.0)

    signal_state = Column(String, nullable=True)
    signal_remain_time = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)