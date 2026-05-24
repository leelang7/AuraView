"""
정책 임팩트 1-pager PDF 생성기.

매 호출마다 TAAS 베이스라인 + 공공데이터 freshness + KPI 요약을 단일 A4 페이지로 묶어
개발자·정책담당자 배포용으로 즉석 출력. matplotlib backend(Agg/PDF) 사용.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # 서버 환경 — 화면 백엔드 비활성

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch

# 한글 폰트 (Noto Sans CJK 우선, 없으면 fallback)
def _setup_korean_font():
    candidates = [
        "Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic",
        "AppleGothic", "Nanum Gothic", "DejaVu Sans",
    ]
    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    for c in candidates:
        if c in available:
            matplotlib.rcParams["font.family"] = c
            return c
    return "DejaVu Sans"


_FONT = _setup_korean_font()


def _add_text(ax, x, y, text, fontsize=10, weight="normal", color="#222", ha="left", va="top"):
    ax.text(x, y, text, fontsize=fontsize, fontweight=weight, color=color, ha=ha, va=va,
            transform=ax.transAxes)


def render_policy_pdf(
    *,
    coverage: float = 0.05,
    lead_time_s: float = 3.38,
    title: str = "AuraView 정책 임팩트 보고서",
) -> bytes:
    """단일 A4 PDF (bytes) 반환."""
    from . import impact as impact_service
    from . import public_api

    # 임팩트 계산
    inp = impact_service.ImpactInputs(
        avg_lead_time_s=lead_time_s,
        coverage_urban_intersections=coverage,
    )
    est = impact_service.estimate(inp).to_dict()
    scenarios = impact_service.scenarios(lead_time_s=lead_time_s)

    # 공공데이터 freshness
    fresh = public_api.get_freshness() if hasattr(public_api, "get_freshness") else {}
    sources_total = 6
    sources_live = sum(1 for v in fresh.values() if v.get("mode") == "live")
    sources_stub = sum(1 for v in fresh.values() if v.get("mode") == "stub")

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))  # A4
        fig.patch.set_facecolor("#f8f9fb")

        # ── 헤더 영역
        ax_head = fig.add_axes([0, 0.88, 1, 0.12])
        ax_head.axis("off")
        ax_head.add_patch(FancyBboxPatch((0.04, 0.05), 0.92, 0.90,
                                          boxstyle="round,pad=0.02",
                                          facecolor="#1a2336", edgecolor="none"))
        _add_text(ax_head, 0.07, 0.78, "AuraView K-Perception", fontsize=20, weight="bold", color="#ffffff")
        _add_text(ax_head, 0.07, 0.42, "정책 임팩트 보고서  ·  Korean Road Safety Impact",
                  fontsize=10, color="#aabac9")
        _add_text(ax_head, 0.07, 0.15, datetime.now().strftime("발행일 %Y-%m-%d %H:%M  ·  v0.5"),
                  fontsize=9, color="#7a8794")
        _add_text(ax_head, 0.95, 0.78, "1-pager", fontsize=10, color="#00c8ff", ha="right")
        _add_text(ax_head, 0.95, 0.42, "AuraView K-Perception",
                  fontsize=9, color="#7a8794", ha="right")

        # ── 헤드라인 KPI 4-grid
        ax_kpi = fig.add_axes([0, 0.66, 1, 0.20])
        ax_kpi.axis("off")
        cards = [
            ("연간 사고 예방", f"{int(est.get('prevented_incidents_yr', 0)):,} 건",
             f"도시 교차로 도입 {int(coverage*100)}%", "#00e09a"),
            ("연간 사망 예방", f"{int(est.get('prevented_deaths_yr', 0))} 명",
             f"평균 선행경고 {lead_time_s:.2f}초", "#ffb020"),
            ("연간 부상 예방", f"{int(est.get('prevented_injuries_yr', 0)):,} 명",
             "TAAS 2024 baseline", "#00c8ff"),
            ("공공데이터", f"{sources_live}/{sources_total} live",
             f"stub {sources_stub} · 실시간 폴링", "#7c3aed"),
        ]
        for i, (label, val, sub, color) in enumerate(cards):
            x0 = 0.04 + i * 0.235
            ax_kpi.add_patch(FancyBboxPatch((x0, 0.10), 0.215, 0.80,
                                             boxstyle="round,pad=0.015",
                                             facecolor="#ffffff", edgecolor="#e0e6ec"))
            _add_text(ax_kpi, x0 + 0.01, 0.78, label, fontsize=8.5, color="#7a8794")
            _add_text(ax_kpi, x0 + 0.01, 0.55, val, fontsize=18, weight="bold", color=color)
            _add_text(ax_kpi, x0 + 0.01, 0.25, sub, fontsize=7.5, color="#7a8794")

        # ── 시나리오 테이블 (5%/25%/100%)
        ax_tbl = fig.add_axes([0, 0.42, 1, 0.22])
        ax_tbl.axis("off")
        _add_text(ax_tbl, 0.04, 0.95, "도입 시나리오별 효과", fontsize=12, weight="bold", color="#1a2336")
        _add_text(ax_tbl, 0.04, 0.84, f"평균 선행경고 시간 {lead_time_s:.2f} 초 기준 (KOTI ITS · 라이브 검증)",
                  fontsize=8, color="#7a8794")
        scns = scenarios.get("scenarios") if isinstance(scenarios, dict) else scenarios
        if isinstance(scns, list):
            cols = ["도입 비율", "사고 예방/년", "사망 예방/년", "부상 예방/년"]
            x_starts = [0.04, 0.30, 0.50, 0.74]
            y0 = 0.66
            for x, h in zip(x_starts, cols):
                _add_text(ax_tbl, x, y0, h, fontsize=9, weight="bold", color="#1a2336")
            for i, sc in enumerate(scns[:5]):
                y = y0 - 0.13 * (i + 1)
                cov_pct = int((sc.get("coverage_urban_intersections", 0) or 0) * 100)
                row = [
                    f"{cov_pct}% — {sc.get('label', '')}",
                    f"{int(sc.get('prevented_incidents_yr', 0)):,}",
                    f"{int(sc.get('prevented_deaths_yr', 0)):,}",
                    f"{int(sc.get('prevented_injuries_yr', 0)):,}",
                ]
                for x, val in zip(x_starts, row):
                    _add_text(ax_tbl, x, y, val, fontsize=9, color="#222")

        # ── 공공데이터 6종 상태
        ax_data = fig.add_axes([0, 0.24, 1, 0.18])
        ax_data.axis("off")
        _add_text(ax_data, 0.04, 0.95, "공공데이터 융합 현황", fontsize=12, weight="bold", color="#1a2336")
        _add_text(ax_data, 0.04, 0.84,
                  "신호·VDS·돌발·TAAS·ITS·DSZ — freshness 추적 + fallback 모드 명시",
                  fontsize=8, color="#7a8794")
        sources = [
            ("signal",    "교통안전 실시간 신호",     "apis.data.go.kr"),
            ("vds",       "VDS 실시간 소통",          "data.ex.co.kr"),
            ("incidents", "한국도로공사 돌발",        "data.ex.co.kr"),
            ("taas",      "TAAS 교통사고분석",        "taas.koroad.or.kr"),
            ("its",       "ITS 국가교통정보센터",     "openapi.its.go.kr"),
            ("dsz",       "데이터안심구역",           "dsz.ex.co.kr"),
        ]
        for i, (sid, name, origin) in enumerate(sources):
            row = i // 3
            col = i % 3
            x0 = 0.04 + col * 0.32
            y0 = 0.55 - row * 0.30
            mode = (fresh.get(sid) or {}).get("mode", "stub")
            mode_color = {"live": "#00e09a", "stub": "#ffb020", "error": "#ff3b3b"}.get(mode, "#7a8794")
            _add_text(ax_data, x0, y0, f"● {name}", fontsize=9, weight="bold", color="#1a2336")
            _add_text(ax_data, x0, y0 - 0.08, origin, fontsize=7.5, color="#7a8794")
            _add_text(ax_data, x0 + 0.21, y0, mode.upper(), fontsize=9, weight="bold", color=mode_color)

        # ── 법적 근거 (도로교통법 + 대법원 판례)
        ax_law = fig.add_axes([0, 0.13, 1, 0.10])
        ax_law.axis("off")
        _add_text(ax_law, 0.04, 0.92, "법적 근거 — 도로교통법 + 대법원 판례",
                  fontsize=11, weight="bold", color="#1a2336")
        law_bullets = [
            "우회전 보행자: 도로교통법 25조 4항 + 대법 2022도10752 (보행자 우선)",
            "스쿨존: 도로교통법 12조 + 민식이법 (헌재 2019헌마927) + 어린이안전관리법",
            "자전거: 도로교통법 13조 + 자전거이용활성화법 + 대법 2021도8395",
            "데이터 컴플라이언스: 개인정보보호법 28조의2 + k=5 가명결합",
        ]
        for i, b in enumerate(law_bullets):
            _add_text(ax_law, 0.04, 0.78 - i * 0.18, "» " + b, fontsize=7.8, color="#222")

        # ── 기술 차별화 + 검증
        ax_diff = fig.add_axes([0, 0.04, 1, 0.09])
        ax_diff.axis("off")
        _add_text(ax_diff, 0.04, 0.94, "기술 차별화 + 검증",
                  fontsize=11, weight="bold", color="#1a2336")
        bullets = [
            "Tesla 자기 카메라만 → AuraView 블랙박스 V2V 협업으로 사각지대 복원",
            "BEV 3D occupancy + Risk Transformer (AUC 0.94 · p99 1.04ms · CPU 단일 코어)",
            "65 pytest · GitHub CI · /metrics/competition (4축 KPI · git_sha)",
        ]
        for i, b in enumerate(bullets):
            _add_text(ax_diff, 0.04, 0.74 - i * 0.22, "• " + b, fontsize=7.8, color="#222")

        # ── 푸터
        ax_foot = fig.add_axes([0, 0, 1, 0.05])
        ax_foot.axis("off")
        _add_text(ax_foot, 0.04, 0.5, "https://auraview.allthatai.kr  ·  /metrics/competition",
                  fontsize=7.5, color="#7a8794")
        _add_text(ax_foot, 0.96, 0.5, "AuraView K-Perception © 2026", fontsize=7.5, color="#7a8794", ha="right")

        pdf.savefig(fig, bbox_inches=None, facecolor=fig.get_facecolor())
        plt.close(fig)

    return buf.getvalue()
