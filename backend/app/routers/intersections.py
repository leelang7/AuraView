from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Intersection
from ..schemas import IntersectionOut
from ..services.matching import haversine
from ..services.public_api import fetch_intersections

router = APIRouter()


def pick_first(item, keys, default=""):
    for key in keys:
        value = item.get(key)
        if value not in [None, ""]:
            return value
    return default


@router.post("/sync")
def sync_intersections(db: Session = Depends(get_db)):
    data = fetch_intersections()

    body = data.get("body", {})
    items = body.get("items", {})
    item_list = items.get("item", [])

    if isinstance(item_list, dict):
        item_list = [item_list]

    inserted = 0
    updated = 0
    skipped = 0
    samples = []

    for item in item_list:
        try:
            intersection_id = str(
                pick_first(item, ["crsrdId", "itstId", "intersectionId"], "")
            ).strip()

            if not intersection_id:
                skipped += 1
                continue

            name = str(
                pick_first(item, ["crsrdNm", "itstNm", "intersectionName", "lclgvNm"], "")
            ).strip()

            municipality_code = str(
                pick_first(item, ["stdgCd", "mngOrgCd", "sidoCd"], "")
            ).strip()

            raw_lat = item.get("mapCtptIntLat")
            raw_lon = item.get("mapCtptIntLot")

            lat = None
            lon = None
            has_valid_coord = False

            if raw_lat not in [None, ""]:
                lat = float(str(raw_lat).strip())

            if raw_lon not in [None, ""]:
                lon = float(str(raw_lon).strip())

            if lat is not None and lon is not None:
                has_valid_coord = True

            exists = db.query(Intersection).filter(
                Intersection.intersection_id == intersection_id
            ).first()

            if exists:
                exists.name = name
                exists.municipality_code = municipality_code
                exists.lat = lat
                exists.lon = lon
                exists.has_valid_coord = has_valid_coord
                updated += 1
            else:
                row = Intersection(
                    intersection_id=intersection_id,
                    name=name,
                    municipality_code=municipality_code,
                    lat=lat,
                    lon=lon,
                    has_valid_coord=has_valid_coord,
                )
                db.add(row)
                inserted += 1

            if len(samples) < 3:
                samples.append({
                    "intersection_id": intersection_id,
                    "name": name,
                    "raw_lat": raw_lat,
                    "raw_lon": raw_lon,
                    "lat": lat,
                    "lon": lon,
                    "has_valid_coord": has_valid_coord
                })

        except Exception as e:
            skipped += 1
            if len(samples) < 3:
                samples.append({"error": str(e)})

    db.commit()

    return {
        "message": "sync complete",
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "sample_count": len(item_list),
        "samples": samples
    }


@router.get("/", response_model=List[IntersectionOut])
def list_intersections(db: Session = Depends(get_db)):
    return db.query(Intersection).all()


@router.get("/valid-coords", response_model=List[IntersectionOut])
def list_valid_coord_intersections(db: Session = Depends(get_db)):
    return db.query(Intersection).filter(
        Intersection.has_valid_coord == True
    ).all()


@router.get("/nearest")
def nearest_intersection(lat: float, lon: float, db: Session = Depends(get_db)):
    intersections = db.query(Intersection).filter(
        Intersection.has_valid_coord == True
    ).all()

    if not intersections:
        return {"message": "no intersections with valid coordinates"}

    nearest = min(
        intersections,
        key=lambda x: haversine(lat, lon, x.lat, x.lon)
    )
    dist = haversine(lat, lon, nearest.lat, nearest.lon)

    return {
        "intersection_id": nearest.intersection_id,
        "name": nearest.name,
        "distance_m": round(dist, 2)
    }