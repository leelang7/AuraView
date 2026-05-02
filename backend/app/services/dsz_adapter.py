"""
국토교통 데이터안심구역(DSZ, dsz.ex.co.kr) 어댑터.

경진대회 "안심구역(5점)" 가점 충족을 위한 **반입 → 분석 → 반출** 파이프라인.

안심구역 규정 핵심:
  - 개인정보 포함 원천 데이터는 외부 반출 금지.
  - 분석 결과물(집계·분포·추세)만 승인 후 반출.
  - 모든 반출물은 해시·서명으로 변조 여부 검증.

본 어댑터는 AuraView 로컬에서 '반출 승인이 된 요약 결과'만 수신한다고 가정하고,
해시 검증 · 메타 기록만 담당한다. 실제 반입·반출은 안심구역 웹 UI로 수행됨.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("auraview.dsz")

DSZ_VERIFY_HASH = os.getenv("DSZ_VERIFY_HASH", "")
EXPORT_DIR = Path(os.getenv("DSZ_EXPORT_DIR", "dsz_exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class DSZArtifact:
    name: str
    purpose: str        # 예: "TAAS×VDS 2024 결합분석 보행자 중상사고"
    rows: int
    schema: List[str]
    sha256: str
    imported_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "rows": self.rows,
            "schema": self.schema,
            "sha256": self.sha256,
            "imported_at": self.imported_at,
        }


def verify_artifact(path: str) -> DSZArtifact:
    """안심구역에서 반출한 요약 결과물을 검증하고 메타를 기록."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    content = p.read_bytes()
    h = hashlib.sha256(content).hexdigest()

    if DSZ_VERIFY_HASH and h != DSZ_VERIFY_HASH:
        raise ValueError(f"DSZ hash mismatch: expected {DSZ_VERIFY_HASH}, got {h}")

    payload: Dict[str, Any] = {}
    try:
        payload = json.loads(content.decode("utf-8"))
    except Exception as exc:
        log.warning("DSZ artifact not JSON (%s), treating as opaque", exc)

    artifact = DSZArtifact(
        name=p.name,
        purpose=payload.get("purpose", "unspecified"),
        rows=len(payload.get("rows", [])) if isinstance(payload, dict) else 0,
        schema=payload.get("schema", []) if isinstance(payload, dict) else [],
        sha256=h,
        imported_at=datetime.utcnow().isoformat(),
    )

    # 수신 로그 (감사 추적)
    with (EXPORT_DIR / "manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(artifact.to_dict(), ensure_ascii=False) + "\n")

    return artifact


def list_imported() -> List[Dict[str, Any]]:
    manifest = EXPORT_DIR / "manifest.jsonl"
    if not manifest.exists():
        return []
    with manifest.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
