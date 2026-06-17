"""SDXL hero 5장 위에 한글 텍스트/UI overlay 합성 → pitch 슬라이드용 final 이미지.

출력:
  docs/captures/slide_01_cover.png       (1920x1080, hero_01 기반)
  docs/captures/slide_03_truck.png       (1920x1080, hero_02 기반)
  docs/captures/slide_05_schoolzone.png  (1920x1080, hero_03 기반)
  docs/captures/slide_06_v2v.png         (1920x1080, hero_04 기반)
  docs/captures/slide_04_fusion.png      (1920x1080, hero_05 기반)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parent.parent
CAPS = ROOT / "docs" / "captures"

W, H = 1920, 1080

FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"
FONT_REG = "C:/Windows/Fonts/malgun.ttf"


def load_font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def darken_overlay(img: Image.Image, opacity: float = 0.55) -> Image.Image:
    """이미지 위에 검정 반투명 overlay (텍스트 가독성)."""
    overlay = Image.new("RGBA", img.size, (10, 14, 24, int(255 * opacity)))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def fit_hero(path: Path, target_w: int = W, target_h: int = H) -> Image.Image:
    """1024 hero → 1920x1080 으로 cover-fit (잘려도 되는 풍부한 영역)."""
    src = Image.open(path).convert("RGB")
    sw, sh = src.size
    s = max(target_w / sw, target_h / sh)
    nw, nh = int(sw * s), int(sh * s)
    src = src.resize((nw, nh), Image.LANCZOS)
    left = (nw - target_w) // 2
    top = (nh - target_h) // 2
    return src.crop((left, top, left + target_w, top + target_h))


def gradient_band(img: Image.Image, side: str = "bottom", height: int = 540) -> Image.Image:
    """하단/측면 그라데이션 띠 (검정 → 투명)."""
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for i in range(height):
        if side == "bottom":
            alpha = int(220 * (i / height) ** 1.5)
            bd.line([(0, img.height - i), (img.width, img.height - i)], fill=(8, 12, 22, alpha))
        elif side == "left":
            alpha = int(220 * (i / height) ** 1.5)
            bd.line([(i, 0), (i, img.height)], fill=(8, 12, 22, alpha))
    return Image.alpha_composite(img.convert("RGBA"), band)


def slide_01_cover():
    img = fit_hero(CAPS / "hero_01_cover.png")
    img = darken_overlay(img, 0.30)
    img = gradient_band(img, "bottom", 700)
    img = gradient_band(img, "left", 500)
    d = ImageDraw.Draw(img)

    # 좌측 정렬 hero text
    d.text((90, 320), "AuraView", font=load_font(120, True), fill=(255, 255, 255))
    d.text((90, 460), "K-Perception", font=load_font(84, True), fill=(0, 200, 255))
    d.text((90, 600), "공공데이터 융합 · 차량 협력 인지 기반",
           font=load_font(38, True), fill=(180, 220, 240))
    d.text((90, 656), "한국 도로 안전 AI 블랙박스 플랫폼",
           font=load_font(38, True), fill=(180, 220, 240))

    # 하단 KPI 4축
    y = 870
    kpis = [
        ("3.38초", "사전 경고", "#00C8FF"),
        ("84.5%", "회피 성공률", "#00E09A"),
        ("AUC 0.9403", "Risk Transformer", "#FFB020"),
        ("25종", "공공데이터 융합", "#FF6B6B"),
    ]
    for i, (val, lbl, color) in enumerate(kpis):
        x = 90 + i * 440
        d.text((x, y), val, font=load_font(56, True), fill=color)
        d.text((x, y + 70), lbl, font=load_font(22, False), fill=(180, 200, 220))

    # 우측 하단 brand chip
    d.rectangle([(W - 480, H - 80), (W - 30, H - 30)], outline=(255, 255, 255, 60))
    d.text((W - 470, H - 70), "2026 · 국토교통 데이터 활용 · v12.171",
           font=load_font(18, False), fill=(180, 200, 220))

    out = CAPS / "slide_01_cover.png"
    img.convert("RGB").save(out, quality=92)
    print(f"  [+] {out.name}")


def slide_03_truck():
    img = fit_hero(CAPS / "hero_02_truck_occlusion.png")
    img = darken_overlay(img, 0.35)
    img = gradient_band(img, "bottom", 600)
    img = gradient_band(img, "left", 700)
    d = ImageDraw.Draw(img)

    # 상단 좌측 시나리오 라벨
    d.rectangle([(80, 80), (520, 140)], fill=(255, 64, 64, 220))
    d.text((100, 92), "시나리오 ①  ·  트럭이 신호 가림",
           font=load_font(28, True), fill=(255, 255, 255))

    # 좌 중앙 메인 메시지
    d.text((90, 480), "운전자가 못 보는 곳을", font=load_font(72, True), fill=(255, 255, 255))
    d.text((90, 580), "AuraView가 본다", font=load_font(96, True), fill=(0, 200, 255))

    # 우측 데이터 칩 (해결 방법)
    y = 200
    chips = [
        ("도로교통공단 신호 위상 API", "+0.55"),
        ("KOTSA V2X 협력 인지", "반경 200m"),
        ("Risk Transformer AUC 0.9403", "p99 1.04ms"),
    ]
    for label, val in chips:
        d.rectangle([(W - 660, y), (W - 80, y + 110)], outline=(0, 200, 255, 120), width=2)
        d.text((W - 640, y + 18), label, font=load_font(26, True), fill=(255, 255, 255))
        d.text((W - 640, y + 60), val, font=load_font(34, True), fill=(0, 200, 255))
        y += 140

    # 하단 정량 효과
    d.text((90, 880), "→ 3.38초 사전 경고 (일반 ADAS 0.5초)",
           font=load_font(32, True), fill=(0, 224, 154))
    d.text((90, 940), "→ 회피 성공률 25% → 84.5% (KOTI ITS 모델)",
           font=load_font(28, False), fill=(180, 220, 240))

    out = CAPS / "slide_03_truck.png"
    img.convert("RGB").save(out, quality=92)
    print(f"  [+] {out.name}")


def slide_04_fusion():
    img = fit_hero(CAPS / "hero_05_data_fusion.png")
    img = darken_overlay(img, 0.55)
    img = gradient_band(img, "bottom", 600)
    d = ImageDraw.Draw(img)

    # 상단 헤더
    d.text((90, 80), "공공데이터 25종 × 11개 기관 실시간 융합",
           font=load_font(54, True), fill=(255, 255, 255))
    d.text((90, 150), "fusion.v11-2026.05.25-25src · p50 180ms · stub→live 점진 확장",
           font=load_font(24, False), fill=(180, 220, 240))

    # 우측 11 기관 리스트 (작은 표)
    agencies = [
        ("한국도로공사", "VDS · 돌발 · RWIS · 노후도"),
        ("한국교통안전공단", "자동차검사 · DTG · V2X"),
        ("도로교통공단", "신호 · TAAS · 보행자 · 통학로"),
        ("국토교통부", "ITS · DSZ · 스쿨존 · 횡단보도"),
        ("기상청", "동네예보 · 결빙"),
        ("환경부 · 환경공단", "미세먼지 · EV"),
        ("소방청 · 복지부", "119 · E-Gen"),
        ("경찰청 · 행안부 · 서울시", "단속 · 노후 · 따릉이"),
        ("USGS (글로벌)", "실시간 지진 M2.0+"),
        ("OpenStreetMap", "철도 건널목 · 횡단보도"),
    ]
    y = 240
    for ag, dat in agencies:
        d.text((W - 880, y), ag, font=load_font(22, True), fill=(0, 200, 255))
        d.text((W - 600, y + 2), dat, font=load_font(20, False), fill=(220, 230, 240))
        y += 36

    # 하단 좌측 4축 KPI
    d.text((90, 820), "9 자가진단 게이트", font=load_font(32, True), fill=(0, 224, 154))
    d.text((90, 870), "통과: 9 / 9  ·  banned words: 0 leaks",
           font=load_font(22, False), fill=(180, 220, 240))
    d.text((90, 920), "라이브 검증: auraview.allthatai.kr/impact/submission-ready",
           font=load_font(20, False), fill=(160, 200, 220))

    out = CAPS / "slide_04_fusion.png"
    img.convert("RGB").save(out, quality=92)
    print(f"  [+] {out.name}")


def slide_05_schoolzone():
    img = fit_hero(CAPS / "hero_03_schoolzone.png")
    img = darken_overlay(img, 0.25)
    img = gradient_band(img, "bottom", 580)
    d = ImageDraw.Draw(img)

    # 시나리오 라벨
    d.rectangle([(80, 80), (510, 140)], fill=(0, 200, 100, 220))
    d.text((100, 92), "시나리오 ⑥  ·  스쿨존 등하교",
           font=load_font(28, True), fill=(255, 255, 255))

    # 메시지
    d.text((90, 580), "어린이가 가장 위험한 시간을",
           font=load_font(56, True), fill=(255, 255, 255))
    d.text((90, 650), "데이터가 먼저 알린다",
           font=load_font(72, True), fill=(0, 224, 154))

    # 우측 데이터 칩
    y = 200
    chips = [
        ("V-World 어린이보호구역 GIS", "DSZ +0.62"),
        ("도로교통공단 통학로 GIS", "통학시간 +0.18"),
        ("TAAS 보행자 다발지점", "prior +0.30"),
        ("등하교 시간대 ×1.5", "자동 부스트"),
    ]
    for label, val in chips:
        d.rectangle([(W - 640, y), (W - 80, y + 90)], outline=(0, 224, 154, 120), width=2)
        d.text((W - 620, y + 14), label, font=load_font(22, True), fill=(255, 255, 255))
        d.text((W - 620, y + 50), val, font=load_font(28, True), fill=(0, 224, 154))
        y += 115

    # 하단 법적 근거
    d.text((90, 870), "도교법 12조 (어린이 보호구역) · 민식이법 (특정범죄가중)",
           font=load_font(26, True), fill=(255, 200, 100))
    d.text((90, 920), "운전자에 객관적 회피 데이터 제공 · 형사 책임 부담 경감",
           font=load_font(22, False), fill=(200, 220, 240))

    out = CAPS / "slide_05_schoolzone.png"
    img.convert("RGB").save(out, quality=92)
    print(f"  [+] {out.name}")


def slide_06_v2v():
    img = fit_hero(CAPS / "hero_04_v2v.png")
    img = darken_overlay(img, 0.45)
    img = gradient_band(img, "bottom", 580)
    d = ImageDraw.Draw(img)

    # 상단
    d.text((90, 80), "V2V Cross-Vehicle 협력 인지",
           font=load_font(54, True), fill=(255, 255, 255))
    d.text((90, 150), "반경 200m · heading 130° 이상 가중 · KOTSA 자율주행 허브 연계",
           font=load_font(24, False), fill=(180, 220, 240))

    # 중앙 메시지
    d.text((90, 540), "한 대가 본 위험을",
           font=load_font(72, True), fill=(255, 255, 255))
    d.text((90, 640), "주변 모두가 동시에 안다",
           font=load_font(80, True), fill=(0, 200, 255))

    # 차별점 박스
    d.text((90, 820), "Tesla FSD 시점 vs AuraView",
           font=load_font(28, True), fill=(255, 200, 100))
    diffs = [
        "• Tesla: 단일 차량 시점만 인지",
        "• AuraView: 차량 간 위험 전파 + 정책 환원",
    ]
    for i, txt in enumerate(diffs):
        d.text((90, 870 + i * 36), txt, font=load_font(22, False), fill=(220, 235, 245))

    out = CAPS / "slide_06_v2v.png"
    img.convert("RGB").save(out, quality=92)
    print(f"  [+] {out.name}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"[Composite] {W}x{H} pitch slides ...")
    slide_01_cover()
    slide_03_truck()
    slide_04_fusion()
    slide_05_schoolzone()
    slide_06_v2v()
    print(f"\n[OK] 5 composites saved → {CAPS}")


if __name__ == "__main__":
    main()
