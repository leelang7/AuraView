"""
신호등 정보 + 가려진 신호 대체 안내 (기획서 핵심 시나리오).
"""
from fastapi import APIRouter
from ..services.public_api import fetch_signal_info

router = APIRouter()


@router.get("/{intersection_id}")
def get_signal(intersection_id: str):
    try:
        return fetch_signal_info(intersection_id)
    except Exception as e:
        return {"error": str(e)}


@router.get("/{intersection_id}/alternate")
def get_signal_alternate(intersection_id: str, occlusion_score: float = 0.0):
    """
    기획서: '가려진 신호등 대체 안내 활성화'.

    occlusion_score (0~1) — 카메라 시야에서 신호등이 가려진 정도.
    >= 0.4 일 때 alternate guide 활성화.

    응답:
      {intersection_id, signal_state, remain_time_s, risk_score,
       occlusion, alt_guide, alt_action}
    """
    try:
        sig = fetch_signal_info(intersection_id)
    except Exception as exc:
        sig = {"error": str(exc)}

    # signal_state 추출 (다중 응답 형식 호환)
    state = "unknown"
    remain = None
    try:
        item = sig.get("body", {}).get("items", {}).get("item", {})
        state = item.get("stPdsgSttsNm", item.get("st_pdsg_stts_nm", "unknown"))
        remain_raw = item.get("stPdsgRmndCs", item.get("st_pdsg_rmnd_cs"))
        if remain_raw is not None:
            remain = int(float(remain_raw))
    except Exception:
        pass

    # 가림 점수 → risk + alternate 활성화 여부
    activated = occlusion_score >= 0.4
    risk = round(occlusion_score * 25.0 + (5 if "stop" in str(state).lower() else 0), 1)

    if "stop" in str(state).lower():
        action = "정지선 지나지 말 것 · 좌우 보행자 확인"
        guide = "🚦 적색/정지 신호 — 가려진 신호등 음성/HUD 안내 작동"
    elif "go" in str(state).lower() or "proceed" in str(state).lower():
        action = "주의 통과 · 보행자 우선"
        guide = "🟢 녹색 신호 — 직진 가능 (가려진 신호 복원)"
    else:
        action = "감속 후 좌우 확인"
        guide = "⚠ 신호 상태 불확실 — 일시정지 권장"

    return {
        "intersection_id": intersection_id,
        "signal_state": state,
        "remain_time_s": remain,
        "occlusion_score": round(occlusion_score, 2),
        "activated": activated,
        "risk_score": risk,
        "alt_guide": guide,
        "alt_action": action,
        "source": "교통안전 실시간 신호 API + AuraView occupancy",
    }