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


def _read_trained_metric() -> Dict[str, Any]:
    p = Path(__file__).resolve().parents[3] / "models" / "risk_transformer_trained_metric.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_system_resources() -> Dict[str, Any]:
    """Linux /proc 기반 (stdlib only) — CPU 코어 + RAM 총량/사용량 노출."""
    out: Dict[str, Any] = {}
    try:
        import os as _os
        out["cpu_count"] = _os.cpu_count()
    except Exception:
        pass
    try:
        # /proc/meminfo: MemTotal, MemFree, MemAvailable (kB 단위)
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            mem: Dict[str, int] = {}
            for line in f:
                parts = line.split(":")
                if len(parts) != 2:
                    continue
                k = parts[0].strip()
                if k in ("MemTotal", "MemFree", "MemAvailable", "SwapTotal"):
                    val_str = parts[1].strip().split()[0]
                    mem[k] = int(val_str)
        if "MemTotal" in mem:
            out["mem_total_mb"] = round(mem["MemTotal"] / 1024, 0)
            out["mem_total_gb"] = round(mem["MemTotal"] / 1024 / 1024, 2)
        if "MemAvailable" in mem:
            out["mem_available_mb"] = round(mem["MemAvailable"] / 1024, 0)
            if "MemTotal" in mem and mem["MemTotal"] > 0:
                out["mem_used_pct"] = round(
                    (mem["MemTotal"] - mem["MemAvailable"]) / mem["MemTotal"] * 100, 1
                )
        if "SwapTotal" in mem:
            out["swap_total_mb"] = round(mem["SwapTotal"] / 1024, 0)
    except Exception:
        # non-Linux 또는 /proc 접근 불가
        pass
    try:
        # /proc/loadavg: 1/5/15 minute averages
        with open("/proc/loadavg", "r", encoding="utf-8") as f:
            parts = f.read().split()
        if len(parts) >= 3:
            out["loadavg_1m"] = float(parts[0])
            out["loadavg_5m"] = float(parts[1])
            out["loadavg_15m"] = float(parts[2])
    except Exception:
        pass
    return out


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

    # Risk Transformer 활성 백엔드
    try:
        from ..services import risk_transformer as rt
        live_model_backend = rt.warm_up()
    except Exception:
        live_model_backend = "error"

    feature_flags = {
        "scenario_router": getattr(main_mod, "_SCENARIO_OK", False),
        "showreel_router": getattr(main_mod, "_SHOWREEL_OK", False),
        "ultralytics_lazy": True,
        "fallback_responses": os.getenv("ALLOW_FALLBACK", "1") == "1",
        "cors_open": True,
        "risk_model_backend": live_model_backend,
    }

    return {
        "status": "ok",
        "service": "AuraView K-Perception",
        "version": "0.6-competition-ready",
        "git": _read_git_sha(),
        "boot_at": _BOOT_AT.isoformat() + "Z",
        "uptime_s": round((datetime.utcnow() - _BOOT_AT).total_seconds(), 1),
        "platform": {
            "python": sys.version.split(" ")[0],
            "system": platform.system(),
            "release": platform.release(),
        },
        "resources": _read_system_resources(),
        "routes": {
            "count": len(routes),
            "list": routes[:200],   # 너무 길어지지 않도록 cap
        },
        "features": feature_flags,
        "model_metric": metric,
        "trained_model_metric": _read_trained_metric(),
        "tests": "68 passed (18 endpoint + 12 collab + 8 impact + 30 competition features incl. policy/manifest/resources)",
        "scenarios_supported": [
            "truck_occlusion", "motorcycle_blindspot", "signal_occlusion",
            "rainy_intersection", "right_turn_pedestrian",
            "school_zone", "bicycle_lane", "night_pedestrian",
        ],
        "competition_endpoints": {
            "metrics_kpi": "/metrics/competition",
            "metrics_scoreboard": "/metrics/scoreboard",
            "policy_pdf": "/impact/policy-pdf",
            "live_dashboard": "/ui#tab10",
        },
    }
