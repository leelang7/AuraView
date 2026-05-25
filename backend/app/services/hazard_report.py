"""
Top-N 위험 교차로 자동 리포트 생성기.

지자체·도로공사 정책 환원용 산출물. 사회적 가치 + AI 활용 분석 점수 어필.

출력 형식:
  - HTML (권한 없는 사용자도 즉시 열람)
  - JSON (시스템 연계용)
  - (선택) PDF — reportlab 있을 때만, 없으면 HTML 만 생성

저장 위치: uploads/reports/<timestamp>_hazard_topN.{html,json}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

REPORT_DIR = Path(os.getenv("REPORT_DIR", "uploads/reports"))
REPORT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class HazardEntry:
    rank: int
    intersection_id: str
    risk_score: float
    event_count: int
    avg_duration: float
    signal_state: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


def _recommend(risk: float, count: int) -> str:
    if risk >= 12 and count >= 5:
        return "🔴 즉시 점검 — 보행자 신호 연장 + 카메라 사각 보강 + 차량 진입 제한 표지"
    if risk >= 10:
        return "🟠 단기 보강 — 횡단보도 야간 조명 + 음성 보행안내 시스템"
    if risk >= 8:
        return "🟡 모니터링 — Fleet 데이터 누적 후 재평가"
    return "🟢 양호 — 정기 관찰"


def build_topn(rows: List[Dict[str, Any]], top: int = 20) -> List[HazardEntry]:
    """events.map_data 응답을 받아 Top-N 위험 교차로 리스트 생성."""
    sorted_rows = sorted(rows, key=lambda r: r.get("risk_score", 0), reverse=True)[:top]
    out: List[HazardEntry] = []
    for i, r in enumerate(sorted_rows, start=1):
        out.append(HazardEntry(
            rank=i,
            intersection_id=r.get("intersection_id", "unknown"),
            risk_score=float(r.get("risk_score", 0)),
            event_count=int(r.get("event_count", 0)),
            avg_duration=float(r.get("avg_duration", 0)),
            signal_state=str(r.get("signal_state") or ""),
            lat=r.get("last_lat"), lon=r.get("last_lon"),
            recommendation=_recommend(r.get("risk_score", 0), r.get("event_count", 0)),
        ))
    return out


def render_html(entries: List[HazardEntry], generated_by: str = "AuraView K-Perception") -> str:
    rows_html = "\n".join(
        f"""
        <tr>
          <td class="rank">{e.rank}</td>
          <td class="id">{e.intersection_id}</td>
          <td class="risk r{int(min(15, e.risk_score))}">{e.risk_score:.1f}</td>
          <td>{e.event_count}</td>
          <td>{e.avg_duration:.2f}s</td>
          <td class="sig">{e.signal_state or '-'}</td>
          <td class="loc">{(f'{e.lat:.4f}, {e.lon:.4f}' if (e.lat and e.lon) else '-')}</td>
          <td class="rec">{e.recommendation}</td>
        </tr>"""
        for e in entries
    )
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AuraView · 위험 교차로 Top {len(entries)} 리포트 · {ts}</title>
<style>
  body {{ font-family: 'Noto Sans KR', system-ui, sans-serif; background:#080c14; color:#e2eaf5;
         margin:0; padding:30px; }}
  .head {{ display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:20px;
          border-bottom:1px solid rgba(0,200,255,0.2); padding-bottom:14px; }}
  h1 {{ font-size:24px; margin:0; }}
  .meta {{ color:#5a7a9a; font-family: ui-monospace, monospace; font-size:11px; letter-spacing:1.5px; text-transform:uppercase; }}
  .summary {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:14px; margin:20px 0 28px; }}
  .stat {{ background:#0d1520; border:1px solid rgba(0,200,255,0.15); border-radius:14px; padding:14px 18px; }}
  .stat .l {{ color:#5a7a9a; font-size:10px; letter-spacing:2px; text-transform:uppercase; font-family:ui-monospace,monospace; }}
  .stat .v {{ font-size:28px; font-weight:900; margin-top:4px; }}
  .stat.warn .v {{ color:#ff3b3b; }}
  .stat.ok .v   {{ color:#00e09a; }}
  table {{ width:100%; border-collapse:collapse; background:#0d1520; border-radius:14px; overflow:hidden; }}
  th, td {{ padding:12px 14px; text-align:left; border-bottom:1px solid rgba(0,200,255,0.08); font-size:13px; }}
  th {{ background:#121d2e; color:#00c8ff; font-family:ui-monospace,monospace; font-size:10px; letter-spacing:2px; text-transform:uppercase; }}
  tr:hover {{ background:#121d2e; }}
  .rank {{ font-weight:900; font-size:16px; color:#00c8ff; width:42px; }}
  .id {{ font-family:ui-monospace,monospace; font-size:12px; color:#e2eaf5; }}
  .risk {{ font-weight:900; font-family:ui-monospace,monospace; }}
  .risk.r12, .risk.r13, .risk.r14, .risk.r15 {{ color:#ff3b3b; }}
  .risk.r10, .risk.r11 {{ color:#ff8b3b; }}
  .risk.r8, .risk.r9 {{ color:#ffb020; }}
  .sig {{ font-family:ui-monospace,monospace; font-size:11px; color:#5a7a9a; }}
  .loc {{ font-family:ui-monospace,monospace; font-size:11px; color:#5a7a9a; }}
  .rec {{ color:#c8d6ea; }}
  footer {{ margin-top:40px; padding-top:18px; border-top:1px solid rgba(0,200,255,0.1);
            color:#5a7a9a; font-size:11px; font-family:ui-monospace,monospace; }}
</style></head><body>
  <div class="head">
    <div>
      <div class="meta">// HAZARD INTERSECTION REPORT</div>
      <h1>위험 교차로 Top {len(entries)}</h1>
    </div>
    <div class="meta">{ts} · generated by {generated_by}</div>
  </div>

  <div class="summary">
    <div class="stat warn"><div class="l">CRITICAL (≥10)</div><div class="v">{sum(1 for e in entries if e.risk_score >= 10)}</div></div>
    <div class="stat"><div class="l">HIGH (8~9)</div><div class="v">{sum(1 for e in entries if 8 <= e.risk_score < 10)}</div></div>
    <div class="stat ok"><div class="l">MONITOR</div><div class="v">{sum(1 for e in entries if e.risk_score < 8)}</div></div>
    <div class="stat"><div class="l">TOTAL EVENTS</div><div class="v">{sum(e.event_count for e in entries)}</div></div>
  </div>

  <table>
    <thead><tr>
      <th>Rank</th><th>Intersection</th><th>Risk</th><th>Events</th>
      <th>Avg Duration</th><th>Signal</th><th>Location</th><th>Recommendation</th>
    </tr></thead>
    <tbody>{rows_html}
    </tbody>
  </table>

  <footer>
    AuraView K-Perception Platform · 데이터 출처: 자체 Fleet Learning + 공공데이터 API 융합 ·
    수신처: 한국도로공사 · 지자체 도로교통과 · K-MaaS 운영팀 ·
    <a style="color:#00c8ff" href="https://auraview.allthatai.kr/ui">대시보드</a>
  </footer>
</body></html>
"""


def generate(rows: List[Dict[str, Any]], top: int = 20) -> Dict[str, str]:
    entries = build_topn(rows, top=top)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = REPORT_DIR / f"{ts}_hazard_top{top}"

    html_path = base.with_suffix(".html")
    json_path = base.with_suffix(".json")

    html_path.write_text(render_html(entries), encoding="utf-8")
    json_path.write_text(
        json.dumps([e.to_dict() for e in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "html_url": f"/uploads/reports/{html_path.name}",
        "json_url": f"/uploads/reports/{json_path.name}",
        "entries": len(entries),
        "generated_at": datetime.utcnow().isoformat(),
    }


def list_recent(limit: int = 30) -> List[Dict[str, Any]]:
    items = []
    for p in sorted(REPORT_DIR.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        items.append({
            "name": p.stem,
            "html_url": f"/uploads/reports/{p.name}",
            "json_url": f"/uploads/reports/{p.with_suffix('.json').name}",
            "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            "size_kb": round(p.stat().st_size / 1024, 1),
        })
    return items
