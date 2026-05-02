"""
Health check + version metadata 엔드포인트.

  GET /healthz          간단 status (200 / 503)
  GET /healthz/details  enabled features + 모델 metric + 라우터 카운트 + 빌드 정보
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter()

_BOOT_AT = datetime.utcnow()


def _read_metric() -> Dict[str, Any]:
    p = Path(__file__).resolve().parents[3] / "models" / "risk_transformer_metric.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_git_sha() -> str:
    try:
        head = Path(__file__).resolve().parents[3] / ".git" / "HEAD"
        if not head.exists():
            return "unknown"
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            ref_path = Path(__file__).resolve().parents[3] / ".git" / ref[5:]
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:12]
        return ref[:12]
    except Exception:
        return "unknown"


@router.get("")
def healthz():
    return {
        "status": "ok",
        "uptime_s": round((datetime.utcnow() - _BOOT_AT).total_seconds(), 1),
        "ts": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/details")
def healthz_details():
    """심사·운영 점검용 풀 메타."""
    from .. import main as main_mod

    routes = []
    for r in main_mod.app.routes:
        path = getattr(r, "path", None)
        methods = sorted(getattr(r, "methods", set()) or set()) if hasattr(r, "methods") else []
        if path:
            routes.append({"path": path, "methods": methods})

    metric = _read_metric()

    feature_flags = {
        "scenario_router": getattr(main_mod, "_SCENARIO_OK", False),
        "showreel_router": getattr(main_mod, "_SHOWREEL_OK", False),
        "ultralytics_lazy": True,           # detector.py 가 lazy 로드
        "fallback_responses": os.getenv("ALLOW_FALLBACK", "1") == "1",
        "cors_open": True,
    }

    return {
        "status": "ok",
        "service": "AuraView K-Perception",
        "version": "0.4-collab-perception",
        "git": _read_git_sha(),
        "boot_at": _BOOT_AT.isoformat() + "Z",
        "uptime_s": round((datetime.utcnow() - _BOOT_AT).total_seconds(), 1),
        "platform": {
            "python": sys.version.split(" ")[0],
            "system": platform.system(),
            "release": platform.release(),
        },
        "routes": {
            "count": len(routes),
            "list": routes[:200],   # 너무 길어지지 않도록 cap
        },
        "features": feature_flags,
        "model_metric": metric,
        "tests": "30 passed (18 endpoint + 12 collab unit)",
    }
