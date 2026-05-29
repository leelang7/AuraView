"""라이브 웹페이지 캡쳐 — 별첨 PDF용 스크린샷 자동 수집.

사용:
    python scripts/capture_live_pages.py
    → docs/captures/*.png

확장:
  - 13 기본 페이지 + story 스크롤 다중 + kiosk 자동순환 다른 장면 + gallery 라이트박스
  - fleet 페이지는 호출 완료 대기 후 캡쳐 (이전 빈 화면 캡쳐 방지)
  - visuals SVG → PNG 추출
"""

from __future__ import annotations

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "captures"
LIVE = "https://auraview.allthatai.kr"

# (파일명, URL, 대기 ms, 스크롤 px, 라벨)
PAGES = [
    ("01_home.png", "/ui", 4000, 0, "메인 대시보드"),
    ("02_story_top.png", "/story/", 4000, 0, "스토리 (상단 hero)"),
    ("03_story_mid.png", "/story/", 4000, 1000, "스토리 (중간 BEFORE/AFTER)"),
    ("04_story_bot.png", "/story/", 4000, 2200, "스토리 (시뮬레이터)"),
    ("05_summary.png", "/submission/", 5000, 0, "One-page Summary"),
    ("06_fleet.png", "/fleet-dash/", 8000, 0, "데이터 라이브 그리드"),
    ("07_policy.png", "/policy/", 4000, 0, "정책 의사결정 대시보드"),
    ("08_safezone.png", "/safezone/", 4000, 0, "DSZ 안심구역 시각화"),
    ("09_privacy.png", "/privacy/", 4000, 0, "PII 마스킹 검증"),
    ("10_gallery_top.png", "/gallery/", 4000, 0, "갤러리 (상단)"),
    ("11_gallery_mid.png", "/gallery/", 4000, 900, "갤러리 (8 시나리오)"),
    ("12_slides.png", "/slides/", 4000, 0, "발표 슬라이드"),
    ("13_kiosk_1.png", "/kiosk/", 4000, 0, "키오스크 (장면 A)"),
    ("14_kiosk_2.png", "/kiosk/", 12000, 0, "키오스크 (장면 B - 자동순환)"),
    ("15_bev3d.png", "/bev3d/", 5000, 0, "3D BEV 시각화"),
    ("16_competition.png", "/competition/", 4000, 0, "통합 검증 허브"),
    ("17_scorecard.png", "/scorecard/", 4000, 0, "데이터 활용 증빙 라이브"),
    ("18_reel.png", "/reel/", 4000, 0, "시네마틱 영상 합본"),
]

# visuals SVG → PNG 변환 (브라우저에서 SVG 로드 후 캡쳐)
VISUALS = [
    ("v01_fusion_diagram.png", "/static/visuals/fusion_diagram.svg", "25 데이터 융합 다이어그램"),
    ("v02_before_after.png", "/static/visuals/before_after.svg", "BEFORE/AFTER 비교"),
    ("v03_hud_mockup.png", "/static/visuals/hud_mockup.svg", "HUD UI mockup"),
    ("v04_og_card.png", "/static/visuals/og_card.svg", "OG 공유 카드"),
    ("v05_timeline.png", "/static/visuals/timeline_57s.svg", "3.38초 선행경고 타임라인"),
    ("v06_impact.png", "/static/visuals/impact_waffle.svg", "21명 생명 살림 waffle"),
    ("v07_ai_metrics.png", "/static/visuals/ai_metrics.svg", "AI 학습 메트릭"),
    ("v08_tesla_vs.png", "/static/visuals/tesla_vs_auraview.svg", "Tesla vs AuraView 비교"),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n[Capture] live: {LIVE}")
    print(f"          out:  {OUT_DIR}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=1.5,
        )
        page = ctx.new_page()

        # === 1. 페이지 캡쳐 ===
        results = []
        for fname, path, wait_ms, scroll_y, label in PAGES:
            url = f"{LIVE}{path}"
            out = OUT_DIR / fname
            try:
                print(f"  [+] {fname:30s} ← {url}")
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                except Exception:
                    page.goto(url, wait_until="load", timeout=30000)
                page.wait_for_timeout(wait_ms)
                if scroll_y > 0:
                    page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    page.wait_for_timeout(1500)
                page.screenshot(path=str(out), full_page=False)
                size_kb = out.stat().st_size / 1024
                results.append((fname, label, size_kb, "OK" if size_kb > 30 else "EMPTY?"))
                print(f"      → {size_kb:.1f} KB {'[!] EMPTY?' if size_kb < 30 else ''}")
            except Exception as exc:
                print(f"      [!] FAIL: {exc}")
                results.append((fname, label, 0, f"FAIL"))

        # === 2. visuals SVG → PNG ===
        print("\n[Visuals] SVG → PNG capture")
        # SVG 를 큰 크기로 보기 위해 viewport 변경
        ctx2 = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=1.5,
        )
        page2 = ctx2.new_page()
        # SVG 를 가운데 정렬한 HTML 래퍼로 표시
        for fname, path, label in VISUALS:
            url = f"{LIVE}{path}"
            out = OUT_DIR / fname
            try:
                print(f"  [+] {fname:30s} ← {url}")
                page2.goto(url, wait_until="load", timeout=20000)
                page2.wait_for_timeout(2000)
                page2.screenshot(path=str(out), full_page=False)
                size_kb = out.stat().st_size / 1024
                results.append((fname, label, size_kb, "OK"))
                print(f"      → {size_kb:.1f} KB")
            except Exception as exc:
                print(f"      [!] FAIL: {exc}")

        browser.close()

    print(f"\n[Summary]")
    ok = sum(1 for _, _, _, s in results if s == "OK")
    print(f"  Captured: {ok}/{len(results)}")
    print(f"  Output:   {OUT_DIR}")


if __name__ == "__main__":
    main()
