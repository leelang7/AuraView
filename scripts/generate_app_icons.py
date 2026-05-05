#!/usr/bin/env python3
"""
AuraView Fleet 앱 아이콘 생성기.

AuraView 브랜드 마크 (dark navy + cyan accent + 곡선 'A' + eye dot) 를
Pillow 로 직접 그려서 Android/Web 모든 사이즈 PNG 생성.

출력:
  Android: auraview_fleet/android/app/src/main/res/mipmap-{m,h,xh,xxh,xxxh}dpi/ic_launcher.png
           + ic_launcher_round.png + ic_launcher_foreground.png (adaptive)
  Web:     auraview_fleet/web/icons/Icon-192.png, Icon-512.png, maskable variants
           + auraview_fleet/web/favicon.png
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ANDROID_RES = ROOT / "auraview_fleet" / "android" / "app" / "src" / "main" / "res"
WEB_DIR = ROOT / "auraview_fleet" / "web"

# 브랜드 컬러
BG_DARK = (8, 12, 20)         # #080c14
CYAN_GLOW = (0, 216, 255)     # #00d8ff (radial center)
CYAN_ACCENT = (0, 200, 255)   # #00c8ff (eye dot)
TEXT = (226, 234, 245)        # #e2eaf5 (curved A + ring)


def _radial_bg(size: int, corner_radius: int) -> Image.Image:
    """다크 → 시안 radial gradient 배경."""
    img = Image.new("RGBA", (size, size), BG_DARK + (255,))
    px = img.load()
    cx, cy = size * 0.5, size * 0.45
    max_r = size * 0.65
    for y in range(size):
        for x in range(size):
            r = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            t = min(1.0, r / max_r)
            # 중심 시안 → 가장자리 진네이비
            r_c = int(CYAN_GLOW[0] * (1 - t) ** 2 + BG_DARK[0] * (1 - (1 - t) ** 2))
            g_c = int(CYAN_GLOW[1] * (1 - t) ** 2 + BG_DARK[1] * (1 - (1 - t) ** 2))
            b_c = int(CYAN_GLOW[2] * (1 - t) ** 2 + BG_DARK[2] * (1 - (1 - t) ** 2))
            px[x, y] = (r_c, g_c, b_c, 255)
    # 라운드 모서리 마스크
    if corner_radius > 0:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, size, size), radius=corner_radius, fill=255
        )
        rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        rounded.paste(img, (0, 0), mask)
        return rounded
    return img


def _draw_logo(img: Image.Image, scale: float = 1.0) -> None:
    """곡선 'A' 지붕 + 시안 dot 그리기 (logo)."""
    d = ImageDraw.Draw(img)
    W = img.size[0]
    s = W / 64.0  # 64x64 기준 좌표 → 실제 px

    # 1) 곡선 지붕 (roof) — Quadratic curve approximation: 호로 그림
    #    M 14 42 Q 32 18 50 42  → 시작 (14,42), 제어 (32,18), 끝 (50,42)
    pts = []
    for i in range(81):
        t = i / 80.0
        # quadratic bezier
        x = (1 - t) ** 2 * 14 + 2 * (1 - t) * t * 32 + t ** 2 * 50
        y = (1 - t) ** 2 * 42 + 2 * (1 - t) * t * 18 + t ** 2 * 42
        pts.append((x * s, y * s))
    # 굵은 line (stroke 3) — Pillow 의 line 으로 다중 두께
    d.line(pts, fill=TEXT + (255,), width=max(2, int(3 * s * scale)))

    # 2) Eye dot (circle) — center (32, 36), r=5
    cx, cy, r = 32 * s, 36 * s, 5 * s * scale
    # 외곽 ring
    d.ellipse(
        (cx - r - 0.8 * s, cy - r - 0.8 * s, cx + r + 0.8 * s, cy + r + 0.8 * s),
        outline=TEXT + (255,), width=max(1, int(1.5 * s * scale)),
    )
    # 내부 시안
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CYAN_ACCENT + (255,))


def make_icon(size: int, *, rounded: bool = False, foreground_only: bool = False,
              adaptive_background: bool = False) -> Image.Image:
    """단일 아이콘 생성.

    Android adaptive icon 구조:
      ic_launcher_background : 풀 캔버스 (108dp, 안전영역 X — 시스템이 마스킹)
      ic_launcher_foreground : 풀 캔버스, logo 는 중앙 66% 안에 (안전영역)
    """
    if adaptive_background:
        # 그라디언트 배경만 (logo X) — adaptive layer 1
        return _radial_bg(size, 0)

    if foreground_only:
        # 풀 캔버스 투명 + logo 중앙 (안전영역 안에)
        # 시스템이 1.5x 확대 후 마스크 — 그래서 안전영역은 캔버스 66%
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        # safe zone 안에 logo 그리기 — 캔버스 66% 영역 (size*0.34 마진)
        margin = int(size * 0.17)
        inner_size = size - margin * 2
        layer = Image.new("RGBA", (inner_size, inner_size), (0, 0, 0, 0))
        _draw_logo(layer, scale=1.6)  # 더 크게 — 안전영역 잘 채우게
        img.paste(layer, (margin, margin), layer)
        return img

    corner = int(size * (0.5 if rounded else 0.22))
    bg = _radial_bg(size, corner)
    _draw_logo(bg, scale=1.0)
    return bg


def main():
    # Android mipmap sizes
    android_sizes = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    for folder, size in android_sizes.items():
        p = ANDROID_RES / folder
        p.mkdir(parents=True, exist_ok=True)
        # 1) Legacy launcher icon (Android < 26)
        make_icon(size, rounded=False).save(p / "ic_launcher.png", "PNG")
        make_icon(size, rounded=True).save(p / "ic_launcher_round.png", "PNG")
        # 2) Adaptive icon layers (Android 8+)
        # foreground: logo 만 중앙 안전영역에
        make_icon(size, foreground_only=True).save(p / "ic_launcher_foreground.png", "PNG")
        # background: 풀 라디알 (logo X) — adaptive 시스템이 합성
        make_icon(size, adaptive_background=True).save(p / "ic_launcher_background.png", "PNG")
        print(f"[ok] {folder}/ ({size}px)")

    # Web (PWA manifest)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    icons_dir = WEB_DIR / "icons"
    icons_dir.mkdir(exist_ok=True)
    make_icon(192, rounded=False).save(icons_dir / "Icon-192.png", "PNG")
    make_icon(512, rounded=False).save(icons_dir / "Icon-512.png", "PNG")
    # Maskable: 안전 영역 80% 안에 logo (전체 캔버스에 배경)
    make_icon(192, rounded=False).save(icons_dir / "Icon-maskable-192.png", "PNG")
    make_icon(512, rounded=False).save(icons_dir / "Icon-maskable-512.png", "PNG")
    print(f"[ok] web/icons/Icon-{192,512}.png + maskable")

    # favicon (32px)
    make_icon(64, rounded=False).save(WEB_DIR / "favicon.png", "PNG")
    print("[ok] web/favicon.png (64px)")

    print("\n[done] AuraView 브랜드 아이콘 생성 완료.")


if __name__ == "__main__":
    main()
