"""라이브 웹페이지 캡쳐 — 별첨 PDF용 스크린샷 자동 수집.

사용:
    python scripts/capture_live_pages.py
    → docs/captures/*.png (각 페이지)
"""

from __future__ import annotations

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "captures"
LIVE = "https://auraview.allthatai.kr"

# 캡쳐 대상 페이지 (파일명, URL, 설명)
PAGES = [
    ("01_home.png", "/ui", "메인 대시보드"),
    ("02_story.png", "/story/", "30초 스토리"),
    ("03_scorecard.png", "/scorecard/", "25점 항목 적격 증거표"),
    ("04_summary.png", "/submission/", "One-page Summary"),
    ("05_fleet.png", "/fleet/", "25 데이터 라이브 grid"),
    ("06_policy.png", "/policy/", "정책 의사결정 대시보드"),
    ("07_safezone.png", "/safezone/", "DSZ 안심구역 결합"),
    ("08_privacy.png", "/privacy/", "PII 마스킹 검증"),
    ("09_gallery.png", "/gallery/", "8 시나리오 SVG 갤러리"),
    ("10_slides.png", "/slides/", "발표 슬라이드"),
    ("11_kiosk.png", "/kiosk/", "키오스크 자동 시연"),
    ("12_bev3d.png", "/bev3d/", "3D BEV 시각화"),
    ("13_competition.png", "/competition/", "통합 검증 허브"),
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
            device_scale_factor=1.5,  # 고해상도
        )
        page = ctx.new_page()

        results = []
        for fname, path, label in PAGES:
            url = f"{LIVE}{path}"
            out = OUT_DIR / fname
            try:
                print(f"  [+] {fname:25s} ← {url}")
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)  # 동적 로딩 + 애니메이션 대기
                page.screenshot(path=str(out), full_page=False)
                size_kb = out.stat().st_size / 1024
                results.append((fname, label, size_kb, "OK"))
                print(f"      → {size_kb:.1f} KB")
            except Exception as exc:
                print(f"      [!] FAIL: {exc}")
                results.append((fname, label, 0, f"FAIL: {exc}"))

        browser.close()

    print("\n[Summary]")
    print(f"  Captured: {sum(1 for _, _, _, s in results if s == 'OK')}/{len(PAGES)}")
    print(f"  Output:   {OUT_DIR}")


if __name__ == "__main__":
    main()
