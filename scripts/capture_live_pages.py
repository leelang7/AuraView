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

# (파일명, URL, 대기 ms, full_page, 라벨)
# 페이지 길이가 viewport 보다 짧으면 full_page=False (그대로),
# 길고 위쪽이 중요한 페이지는 full_page=False + viewport 1280x1400 으로 크게,
# 전체가 다 의미 있는 페이지는 full_page=True (전체 캡쳐)
PAGES = [
    ("01_home.png", "/ui", 4000, False, "메인 대시보드"),
    ("02_story_top.png", "/story/", 4000, False, "스토리 (상단 hero)"),
    ("03_story_mid.png", "/story/", 4000, False, "스토리 (전체)"),
    ("04_summary.png", "/submission/", 5000, False, "One-page Summary"),
    ("05_fleet.png", "/fleet-dash/", 8000, False, "데이터 라이브 그리드"),
    ("06_policy.png", "/policy/", 4000, False, "정책 의사결정 대시보드"),
    ("07_safezone.png", "/safezone/", 4000, False, "DSZ 안심구역 시각화"),
    ("08_privacy.png", "/privacy/", 4000, False, "PII 마스킹 검증"),
    ("09_gallery_top.png", "/gallery/", 4000, False, "갤러리 (상단)"),
    ("10_gallery_full.png", "/gallery/", 4000, False, "갤러리 (전체)"),
    ("11_slides.png", "/slides/", 4000, False, "발표 슬라이드"),
    ("12_kiosk_1.png", "/kiosk/", 4000, False, "키오스크 (장면 A)"),
    ("13_kiosk_2.png", "/kiosk/", 12000, False, "키오스크 (장면 B)"),
    ("14_bev3d.png", "/bev3d/", 5000, False, "3D BEV 시각화"),
    ("15_competition.png", "/competition/", 4000, False, "통합 검증 허브"),
    ("16_scorecard.png", "/scorecard/", 4000, False, "데이터 활용 증빙 라이브"),
    ("17_reel.png", "/reel/", 4000, False, "시네마틱 영상 합본"),
]

# visuals SVG → PNG 변환 (브라우저에서 SVG 로드 후 캡쳐)
# SVG 원본 (width, height) 비율에 맞춰 viewport 동적 변경 → 빈 여백 제거
# (파일명, SVG URL, viewport_w, viewport_h, 설명)
VISUALS = [
    ("v01_fusion_diagram.png", "/static/visuals/fusion_diagram.svg", 1600, 960, "25 데이터 융합 다이어그램"),  # 1200x720 → 1.33배
    ("v02_before_after.png", "/static/visuals/before_after.svg", 1600, 800, "BEFORE/AFTER 비교"),  # 1200x600
    ("v03_hud_mockup.png", "/static/visuals/hud_mockup.svg", 720, 1440, "HUD UI mockup"),  # 720x1440 세로
    ("v04_og_card.png", "/static/visuals/og_card.svg", 1600, 840, "OG 공유 카드"),  # 1200x630
    ("v05_timeline.png", "/static/visuals/timeline_57s.svg", 1600, 670, "3.38초 선행경고 타임라인"),  # 1200x500
    ("v06_impact.png", "/static/visuals/impact_waffle.svg", 1600, 960, "21명 생명 살림 waffle"),
    ("v07_ai_metrics.png", "/static/visuals/ai_metrics.svg", 1600, 960, "AI 학습 메트릭"),
    ("v08_tesla_vs.png", "/static/visuals/tesla_vs_auraview.svg", 1600, 960, "Tesla vs AuraView 비교"),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    OUT_DIR.mkdir(parents=False, exist_ok=True)
    print(f"\n[Capture] live: {LIVE}")
    print(f"          out:  {OUT_DIR}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # viewport 높이 1500으로 확대 (기본 900 → 1500) → 페이지 첫 화면에서
        # 더 많은 콘텐츠 캡쳐. PDF aspect ratio 약 1.17 → 페이지에 잘 들어감.
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 1500},
            device_scale_factor=1.5,
        )
        page = ctx.new_page()

        # === 1. 페이지 캡쳐 ===
        results = []
        for fname, path, wait_ms, full_page, label in PAGES:
            url = f"{LIVE}{path}"
            out = OUT_DIR / fname
            try:
                fp_tag = "(full)" if full_page else "(view)"
                print(f"  [+] {fname:30s} {fp_tag} ← {url}")
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                except Exception:
                    page.goto(url, wait_until="load", timeout=30000)
                page.wait_for_timeout(wait_ms)
                page.screenshot(path=str(out), full_page=full_page)
                size_kb = out.stat().st_size / 1024
                results.append((fname, label, size_kb, "OK" if size_kb > 30 else "EMPTY?"))
                print(f"      → {size_kb:.1f} KB {'[!] EMPTY?' if size_kb < 30 else ''}")
            except Exception as exc:
                print(f"      [!] FAIL: {exc}")
                results.append((fname, label, 0, f"FAIL"))

        # === 2. visuals SVG → PNG ===
        # SVG 비율에 맞춰 viewport 동적 변경 → 빈 여백 최소화
        print("\n[Visuals] SVG → PNG capture")
        for fname, path, vw, vh, label in VISUALS:
            url = f"{LIVE}{path}"
            out = OUT_DIR / fname
            try:
                print(f"  [+] {fname:30s} ({vw}x{vh}) ← {url}")
                ctx2 = browser.new_context(
                    viewport={"width": vw, "height": vh},
                    device_scale_factor=1.5,
                )
                page2 = ctx2.new_page()
                page2.goto(url, wait_until="load", timeout=20000)
                page2.wait_for_timeout(2000)
                page2.screenshot(path=str(out), full_page=False)
                ctx2.close()
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
