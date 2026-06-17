"""AuraView 2차 발표 PPTX — 풀블리드 디자인 이미지 12장 그대로 삽입.

각 슬라이드 = docs/pitch_slides/slide_NN.png (1920x1080, HTML/CSS 렌더).
PowerPoint 네이티브 요소 0 — 디자인은 전부 이미지에 구워짐.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches


ROOT = Path(__file__).resolve().parent.parent
SLIDES = ROOT / "docs" / "pitch_slides"
OUT = ROOT / "docs" / "AuraView_pitch_2026.pptx"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    imgs = sorted(SLIDES.glob("slide_*.png"))
    if not imgs:
        print("[ERR] no slide images found in docs/pitch_slides/")
        return

    blank = prs.slide_layouts[6]
    for img in imgs:
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(str(img), 0, 0, width=SLIDE_W, height=SLIDE_H)
        print(f"  + {img.name}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"\n[OK] {OUT}")
    print(f"    {OUT.stat().st_size / 1024 / 1024:.1f} MB · {len(prs.slides)} 슬라이드 · 16:9")


if __name__ == "__main__":
    main()
