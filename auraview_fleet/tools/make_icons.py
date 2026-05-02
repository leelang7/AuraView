"""
AuraView Fleet 앱 아이콘 생성기.

디자인 철학:
  - "Perception eye" — 어두운 배경 위 사이안 글로우 + 스캔 라인
  - 작은 사이즈 (48px) 에서도 인식 가능하도록 단순한 실루엣
  - 다크 테마와 같은 톤으로 브랜드 통일

생성물:
  - 1024×1024 마스터 PNG (preview 용)
  - Android mipmap-mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi 의 ic_launcher.png + ic_launcher_round.png
  - Adaptive icon foreground PNG (mipmap-mdpi ... -xxxhdpi) — 432×432 기준 SCALE 비례
  - web/icons/Icon-192.png, Icon-512.png, Icon-maskable-*, favicon.png
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]      # auraview_fleet/
ANDROID_RES = ROOT / "android" / "app" / "src" / "main" / "res"
WEB_ICONS = ROOT / "web" / "icons"
WEB_DIR = ROOT / "web"
OUT_PREVIEW = ROOT / "tools" / "_preview"
OUT_PREVIEW.mkdir(exist_ok=True)


# ──────────────────────────────────────────────────────────────────────
# Master 1024×1024 design
# ──────────────────────────────────────────────────────────────────────

def design_master(size: int = 1024, with_circle_clip: bool = False) -> Image.Image:
    """다크 베이스 + 사이안→퍼플 라디얼 + 스캔 곡선 + 중앙 글로우."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    r_outer = size // 2

    # 1) 배경 — 라디얼 그라디언트 (사이안 → 퍼플 → 검정)
    # Pillow 에는 직접 라디얼 없으니 동심원으로 구현
    bg_layers = 60
    for i in range(bg_layers, 0, -1):
        t = i / bg_layers       # 0 (center) → 1 (edge)
        # 컬러 보간: center #00d8ff → mid #1a3a8a → edge #060a14
        if t < 0.55:
            tt = t / 0.55
            r = int(0   + (26 - 0)   * tt)
            g = int(216 + (58 - 216) * tt)
            b = int(255 + (138 - 255) * tt)
        else:
            tt = (t - 0.55) / 0.45
            r = int(26  + (6  - 26)  * tt)
            g = int(58  + (10 - 58)  * tt)
            b = int(138 + (20 - 138) * tt)
        rad = int(r_outer * t)
        draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad),
                     fill=(r, g, b, 255))

    # 2) 동심 스캔 링 3개 (반투명 사이안)
    for t, alpha in [(0.55, 50), (0.72, 35), (0.88, 22)]:
        rad = int(r_outer * t)
        ring_w = max(2, size // 200)
        draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad),
                     outline=(0, 220, 255, alpha), width=ring_w)

    # 3) 스캔 빔 (방사형 8개)
    beam_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(beam_layer)
    beams = 8
    inner_r = size * 0.15
    outer_r = size * 0.46
    beam_w = max(3, size // 240)
    for i in range(beams):
        ang = (math.pi * 2) * (i / beams) + math.pi / beams / 2
        x1 = cx + inner_r * math.cos(ang)
        y1 = cy + inner_r * math.sin(ang)
        x2 = cx + outer_r * math.cos(ang)
        y2 = cy + outer_r * math.sin(ang)
        bd.line([(x1, y1), (x2, y2)], fill=(180, 240, 255, 90), width=beam_w)
    img = Image.alpha_composite(img, beam_layer)

    # 4) 중앙 글로우 코어 (밝은 사이안)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    core_r = int(size * 0.18)
    gd.ellipse((cx - core_r, cy - core_r, cx + core_r, cy + core_r),
               fill=(220, 250, 255, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.025))
    img = Image.alpha_composite(img, glow)

    # 5) 정중앙 작은 단단한 점
    dot_r = int(size * 0.07)
    draw = ImageDraw.Draw(img)
    draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r),
                 fill=(255, 255, 255, 255))

    # 6) 호 — 도로 지평선 메타포 (하단 원호)
    arc_box = (
        int(size * 0.12), int(size * 0.45),
        int(size * 0.88), int(size * 1.10),
    )
    arc_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc_layer)
    arc_w = max(6, size // 60)
    ad.arc(arc_box, start=200, end=340, fill=(255, 255, 255, 230), width=arc_w)
    img = Image.alpha_composite(img, arc_layer)

    if with_circle_clip:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, mask=mask)
        img = out

    return img


def design_foreground(size: int = 1024) -> Image.Image:
    """
    Adaptive icon foreground — 마스킹 영역(중앙 ~66%)에 들어가야 함.
    배경은 별도 컬러이므로 transparent 영역은 비워둠.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx, cy = size // 2, size // 2

    # 중앙 origin 의 ~50% 영역만 사용 (안전 영역)
    safe = int(size * 0.66)
    sx = (size - safe) // 2
    sy = (size - safe) // 2

    # 사이안 글로우 코어
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    core_r = int(size * 0.20)
    gd.ellipse((cx - core_r, cy - core_r, cx + core_r, cy + core_r),
               fill=(0, 220, 255, 230))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.04))
    img = Image.alpha_composite(img, glow)

    # 흰색 단단한 코어
    draw = ImageDraw.Draw(img)
    dot_r = int(size * 0.10)
    draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r),
                 fill=(255, 255, 255, 255))

    # 도로 호
    arc_box = (
        int(size * 0.20), int(size * 0.42),
        int(size * 0.80), int(size * 0.95),
    )
    arc_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc_layer)
    arc_w = max(6, size // 60)
    ad.arc(arc_box, start=200, end=340, fill=(255, 255, 255, 240), width=arc_w)
    img = Image.alpha_composite(img, arc_layer)

    # 스캔 빔 (foreground 안에서 4개로 단순)
    beam_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(beam_layer)
    inner_r = size * 0.18
    outer_r = size * 0.32
    beam_w = max(4, size // 200)
    for ang_deg in (45, 135, 225, 315):
        ang = math.radians(ang_deg)
        x1 = cx + inner_r * math.cos(ang)
        y1 = cy + inner_r * math.sin(ang)
        x2 = cx + outer_r * math.cos(ang)
        y2 = cy + outer_r * math.sin(ang)
        bd.line([(x1, y1), (x2, y2)], fill=(180, 230, 255, 200), width=beam_w)
    img = Image.alpha_composite(img, beam_layer)

    return img


# ──────────────────────────────────────────────────────────────────────
# Output writers
# ──────────────────────────────────────────────────────────────────────

ANDROID_LAUNCHER_SIZES = {
    "mipmap-mdpi":     48,
    "mipmap-hdpi":     72,
    "mipmap-xhdpi":    96,
    "mipmap-xxhdpi":  144,
    "mipmap-xxxhdpi": 192,
}

# Adaptive foreground 권장 base 108dp → 각 dpi 마다 크기 다름
ANDROID_ADAPTIVE_FG_SIZES = {
    "mipmap-mdpi":    108,
    "mipmap-hdpi":    162,
    "mipmap-xhdpi":   216,
    "mipmap-xxhdpi":  324,
    "mipmap-xxxhdpi": 432,
}


def write_legacy_icons(master: Image.Image):
    for folder, size in ANDROID_LAUNCHER_SIZES.items():
        out = ANDROID_RES / folder
        out.mkdir(parents=True, exist_ok=True)
        master.resize((size, size), Image.LANCZOS).save(out / "ic_launcher.png", "PNG")
        # round
        round_master = Image.new("RGBA", master.size, (0, 0, 0, 0))
        mask = Image.new("L", master.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, master.width, master.height), fill=255)
        round_master.paste(master, mask=mask)
        round_master.resize((size, size), Image.LANCZOS).save(out / "ic_launcher_round.png", "PNG")


def write_adaptive_foreground(fg: Image.Image):
    for folder, size in ANDROID_ADAPTIVE_FG_SIZES.items():
        out = ANDROID_RES / folder
        out.mkdir(parents=True, exist_ok=True)
        fg.resize((size, size), Image.LANCZOS).save(out / "ic_launcher_foreground.png", "PNG")


def write_adaptive_xml():
    """mipmap-anydpi-v26/ic_launcher.xml + ic_launcher_round.xml"""
    target_dir = ANDROID_RES / "mipmap-anydpi-v26"
    target_dir.mkdir(parents=True, exist_ok=True)
    body = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background"/>
    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
</adaptive-icon>
"""
    (target_dir / "ic_launcher.xml").write_text(body, encoding="utf-8")
    (target_dir / "ic_launcher_round.xml").write_text(body, encoding="utf-8")

    # 색상 정의
    values = ANDROID_RES / "values"
    values.mkdir(parents=True, exist_ok=True)
    color_xml = values / "ic_launcher_background.xml"
    color_xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">#080C14</color>
</resources>
""",
        encoding="utf-8",
    )


def write_web_icons(master: Image.Image):
    WEB_ICONS.mkdir(parents=True, exist_ok=True)
    sizes_pwa = {
        "Icon-192.png": 192, "Icon-512.png": 512,
        "Icon-maskable-192.png": 192, "Icon-maskable-512.png": 512,
    }
    for name, size in sizes_pwa.items():
        master.resize((size, size), Image.LANCZOS).save(WEB_ICONS / name, "PNG")
    # favicon
    master.resize((32, 32), Image.LANCZOS).save(WEB_DIR / "favicon.png", "PNG")


def main():
    print("Designing master 1024×1024…")
    master = design_master(1024)
    master.save(OUT_PREVIEW / "icon_master_1024.png", "PNG")
    fg = design_foreground(1024)
    fg.save(OUT_PREVIEW / "icon_foreground_1024.png", "PNG")

    print("Writing Android legacy launcher icons…")
    write_legacy_icons(master)

    print("Writing Android adaptive foreground…")
    write_adaptive_foreground(fg)

    print("Writing adaptive XML + background color…")
    write_adaptive_xml()

    print("Writing web/PWA icons…")
    write_web_icons(master)

    print("✓ icons generated.")
    print(f"  preview: {OUT_PREVIEW}")
    print(f"  android res: {ANDROID_RES}")
    print(f"  web icons: {WEB_ICONS}")


if __name__ == "__main__":
    main()
