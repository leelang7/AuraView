"""실검출(YOLO11) → Tesla식 객체 모양 BEV 렌더.

복셀 블롭 대신 클래스별 실루엣(차/트럭/버스/사람/이륜)을 거리·횡방향에 배치.
가려진 영역(트럭 뒤)은 occlusion shadow 로 음영.
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.services import yolo11_detector as y
from PIL import Image, ImageDraw, ImageFont

ROOT = y._REPO_ROOT
img = os.path.join(ROOT, "docs", "captures", "hero_02_truck_occlusion.png")
b = y.detect_to_bev(img)

# 캔버스: 전방 0~40m(세로) × 횡 -12..12m(가로), 약한 원근
W, H = 900, 1000
FWD, LAT = b["forward_m"], 12.0
scene = Image.new("RGB", (W, H), (7, 11, 18))
d = ImageDraw.Draw(scene, "RGBA")

def fy(dist):   # 전방거리 → y (가까울수록 아래), 약한 원근(먼 곳 압축)
    t = max(0.0, min(1.0, dist / FWD))
    return int(H - 60 - (1 - (1 - t) ** 1.25) * (H - 140))
def fx(lat, dist):  # 횡방향(m) → x, 먼 곳일수록 화면중앙 수렴(원근)
    t = max(0.0, min(1.0, dist / FWD))
    persp = 0.55 + 0.45 * (1 - t)
    return int(W / 2 + (lat / LAT) * (W / 2 - 70) * persp)
def scl(dist):  # 먼 객체 작게
    t = max(0.0, min(1.0, dist / FWD))
    return 0.45 + 0.55 * (1 - t)

# 바닥 격자 + 도로
for m in range(0, int(FWD) + 1, 5):
    yy = fy(m)
    d.line([(70, yy), (W - 70, yy)], fill=(40, 55, 75, 90), width=1)
    d.text((20, yy - 8), f"{m}m", font=None, fill=(70, 90, 110))
# 차선(중앙 노랑)
for m in range(0, int(FWD), 3):
    y0, y1 = fy(m), fy(m + 1.6)
    d.line([(fx(0, m), y0), (fx(0, m + 1.6), y1)], fill=(232, 200, 74, 150), width=3)

CLS_SIZE = {  # (폭 m, 길이 m, 색)
    "car": (1.9, 4.6, (150, 170, 190)),
    "truck": (2.6, 9.0, (110, 125, 145)),
    "bus": (2.6, 11.0, (200, 165, 80)),
    "motorcycle": (0.9, 2.2, (255, 176, 32)),
    "bicycle": (0.7, 1.8, (0, 224, 154)),
    "person": (0.6, 0.6, (255, 90, 90)),
}

def draw_vehicle(cx, cy, w_px, l_px, color, label, dist):
    # 차체(둥근 사각) + 캐빈(밝은 윗부분) — top-view
    d.rounded_rectangle([cx - w_px/2, cy - l_px/2, cx + w_px/2, cy + l_px/2],
                        radius=max(3, int(w_px*0.18)), fill=color + (235,),
                        outline=(255, 255, 255, 60), width=1)
    d.rounded_rectangle([cx - w_px*0.32, cy - l_px*0.28, cx + w_px*0.32, cy + l_px*0.12],
                        radius=3, fill=(255, 255, 255, 45))
    d.text((cx + w_px/2 + 6, cy - 8), label, font=FNT, fill=(235, 245, 252))

def draw_person(cx, cy, color, label):
    d.ellipse([cx-7, cy-7, cx+7, cy+7], fill=color + (255,))
    d.ellipse([cx-13, cy-13, cx+13, cy+13], outline=color + (140,), width=2)
    d.text((cx + 12, cy - 8), label, font=FNT, fill=(255, 200, 200))

try:
    FNT = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 19)
except Exception:
    FNT = ImageFont.load_default()

# occlusion shadow: 가장 가까운 트럭/버스 뒤(먼쪽) 부채꼴 음영
occ = None
for p in b["placed"]:
    if p["cls"] in ("truck", "bus"):
        occ = p; break
if occ:
    ox, oy = fx(occ["lateral_m"], occ["distance_m"]), fy(occ["distance_m"])
    far_y = fy(min(FWD, occ["distance_m"] + 14))
    d.polygon([(ox-70, oy), (ox+70, oy), (ox+150, far_y), (ox-150, far_y)],
              fill=(255, 70, 70, 55))
    d.text((ox - 70, (oy+far_y)//2), "사각지대 (트럭 뒤)", font=FNT, fill=(255, 150, 150))

# 검출 객체 그리기 (먼 것부터)
for p in sorted(b["placed"], key=lambda z: -z["distance_m"]):
    cx, cy = fx(p["lateral_m"], p["distance_m"]), fy(p["distance_m"])
    w_m, l_m, color = CLS_SIZE.get(p["cls"], (1.8, 4.0, (150, 160, 175)))
    sc = scl(p["distance_m"])
    px_per_m_w = (W - 140) / (2 * LAT)
    px_per_m_l = 9.0
    if p["cls"] == "person":
        draw_person(cx, cy, color, f"보행자 {p['distance_m']}m")
    else:
        draw_vehicle(cx, cy, w_m * px_per_m_w * sc, l_m * px_per_m_l * sc, color,
                     f"{p['cls']} {p['distance_m']}m", p["distance_m"])

# EGO (하단 중앙, 파랑)
ex, ey = W // 2, H - 70
d.rounded_rectangle([ex-26, ey-46, ex+26, ey+46], radius=10,
                    fill=(46, 134, 200, 255), outline=(150, 230, 255, 200), width=2)
d.rounded_rectangle([ex-17, ey-30, ex+17, ey-2], radius=5, fill=(170, 235, 255, 90))
d.text((ex - 26, ey + 52), "EGO (내 차)", font=FNT, fill=(140, 230, 255))

# 헤더
d.text((30, 24), "AuraView BEV — YOLO11 실검출 객체 모양",
       font=ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 24), fill=(235, 245, 252))
d.text((30, 58), f"source: live_detection · {b['summary']}", font=FNT, fill=(120, 175, 205))

scene.save(os.path.join(ROOT, "docs", "captures", "yolo11_bev_shapes.png"))
print("saved yolo11_bev_shapes.png · objects:", len(b["placed"]), "·", b["summary"])
