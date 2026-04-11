from pydantic import BaseModel
from typing import Optional


class EventCreate(BaseModel):
    intersection_id: str
    user_lat: Optional[float] = None
    user_lon: Optional[float] = None
    heading: Optional[float] = None
    obstacle_type: Optional[str] = None
    signal_visible: bool = False
    event_duration: float = 0.0


class IntersectionOut(BaseModel):
    intersection_id: str
    name: str
    municipality_code: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    has_valid_coord: bool

    class Config:
        from_attributes = True