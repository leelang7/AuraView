from fastapi import APIRouter
from ..services.public_api import fetch_signal_info

router = APIRouter()


@router.get("/{intersection_id}")
def get_signal(intersection_id: str):
    try:
        return fetch_signal_info(intersection_id)
    except Exception as e:
        return {"error": str(e)}