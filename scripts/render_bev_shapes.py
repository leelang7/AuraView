"""실검출(YOLO11) → Tesla식 객체 모양 BEV (정사영 · 실측 비율).

핵심:
  - 정사영(orthographic): 가로/세로 동일 px/m → 폭·길이 실측 비율 정확
  - 클래스별 실측 크기: 차 1.9×4.6 · 트럭 2.6×9 · 버스 2.6×11 · 이륜 0.8×2.1 · 자전거 0.65×1.8 · 사람 Ø0.55
  - 보이는 객체 = 실루엣 / 트럭·버스 뒤 = 사각지대(occlusion) 음영

사용: python scripts/render_bev_shapes.py [이미지경로] [출력파일명]
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.services import yolo11_detector as y
from PIL import Image, ImageDraw, ImageFont

ROOT = y._REPO_ROOT
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs/captures/hero_02_truck_occlusion.png")
out_name = sys.argv[2] if len(sys.argv) > 2 else "yolo11_bev_shapes.png"

b = y.detect_to_bev(src, conf=0.30)

# 정사영 좌표계: 전방 0~FWD m, 횡 ±LAT m, 동일 px/m
FWD, LAT = 40.0, 9.0
PXM = 22
MB, MT = 80, 96
W = int(2 * LAT * PXM) + 200
H = int(FWD * PXM) + MB + MT
CX = W // 2

def gx(lat):  return int(CX + lat * PXM)
def gy(dist): return int(H - MB - dist * PXM)

im = Image.new("RGB", (W, H), (7, 11, 18))
d = ImageDraw.Draw(im, "RGBA")
def F(sz): return ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", sz)

road_half = 3.6
d.rectangle([gx(-road_half * 2), gy(FWD), gx(road_half * 2), gy(0)], fill=(20, 28, 42, 255))
for m in range(0, int(FWD) + 1, 5):
    yy = gy(m)
    d.line([(40, yy), (W - 40, yy)], fill=(45, 60, 82, 110), width=1)
    d.text((10, yy - 9), f"{m}m", font=F(15), fill=(80, 100, 122))
for m in range(0, int(FWD), 3):
    d.line([(gx(0), gy(m)), (gx(0), gy(m + 1.6))], fill=(232, 200, 74, 150), width=3)
d.line([(gx(-road_half), gy(0)), (gx(-road_half), gy(FWD))], fill=(110, 190, 255, 90), width=2)
d.line([(gx(road_half), gy(0)), (gx(road_half), gy(FWD))], fill=(110, 190, 255, 90), width=2)

KIND = {"car": "veh", "truck": "veh", "bus": "veh",
        "motorcycle": "two", "bicycle": "two", "person": "ped"}
COLOR = {"car": (150, 170, 190), "truck": (110, 125, 145), "bus": (200, 165, 80),
         "motorcycle": (255, 176, 32), "bicycle": (0, 224, 154), "person": (255, 90, 90)}

def _car_silhouette(cx, cy, w, l, color):
    """top-view 차 실루엣 — 앞코(위) 살짝 좁힘 + 앞/뒤 유리 + 지붕."""
    nose = w * 0.16
    body = [
        (cx - w/2, cy - l/2 + nose), (cx - w/2 + nose, cy - l/2),       # 앞 좌
        (cx + w/2 - nose, cy - l/2), (cx + w/2, cy - l/2 + nose),       # 앞 우
        (cx + w/2, cy + l/2 - nose*0.6), (cx + w/2 - nose*0.6, cy + l/2),
        (cx - w/2 + nose*0.6, cy + l/2), (cx - w/2, cy + l/2 - nose*0.6),
    ]
    d.polygon(body, fill=color + (245,), outline=(255, 255, 255, 70))
    # 앞 유리(어둡게) + 지붕(밝게) + 뒤 유리
    d.rounded_rectangle([cx - w*0.36, cy - l*0.22, cx + w*0.36, cy - l*0.02], radius=3, fill=(20, 30, 45, 150))
    d.rounded_rectangle([cx - w*0.34, cy - l*0.02, cx + w*0.34, cy + l*0.20], radius=3, fill=(255, 255, 255, 55))
    d.rounded_rectangle([cx - w*0.34, cy + l*0.20, cx + w*0.34, cy + l*0.34], radius=3, fill=(20, 30, 45, 120))

def draw_obj(p):
    cx, cy = gx(p["lateral_m"]), gy(p["distance_m"])
    cls = p["cls"]; kind = KIND.get(cls, "veh"); color = COLOR.get(cls, (150, 160, 175))
    w = p.get("width_m", 1.9) * PXM
    l = p.get("length_m", 4.6) * PXM
    if kind == "ped":
        r = max(5, int(w / 2))
        d.ellipse([cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6], outline=color + (130,), width=2)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (255,))
        lbl = f"보행자 {p['distance_m']}m"
    elif kind == "two":
        d.rounded_rectangle([cx - w/2, cy - l/2, cx + w/2, cy + l/2], radius=3,
                            fill=color + (240,), outline=(255, 255, 255, 70), width=1)
        d.ellipse([cx - 3, cy - l/2 - 3, cx + 3, cy - l/2 + 3], fill=(255, 255, 255, 170))  # 헤드라이트(앞)
        lbl = f"{'오토바이' if cls == 'motorcycle' else '자전거'} {p['distance_m']}m"
    else:
        _car_silhouette(cx, cy, w, l, color)
        lbl = f"{cls} {p.get('width_m','?')}×{p.get('length_m','?')}m"
    d.text((cx + w/2 + 6, cy - 9), lbl, font=F(15),
           fill=(255, 200, 200) if kind == "ped" else (225, 238, 248))

occ = next((p for p in b["placed"] if p["cls"] in ("truck", "bus")), None)
if occ:
    ox, oy = gx(occ["lateral_m"]), gy(occ["distance_m"])
    fy2 = gy(min(FWD, occ["distance_m"] + 12))
    spread = occ.get("width_m", 2.5) * PXM
    d.polygon([(ox - spread, oy), (ox + spread, oy), (ox + spread * 2.4, fy2), (ox - spread * 2.4, fy2)],
              fill=(255, 70, 70, 50))
    d.text((ox - spread * 1.6, (oy + fy2) // 2), "사각지대(가려짐)", font=F(16), fill=(255, 150, 150))

for p in sorted(b["placed"], key=lambda z: -z["distance_m"]):
    draw_obj(p)

ex = gx(0); ey = gy(2.3)
_car_silhouette(ex, ey, 1.85 * PXM, 4.7 * PXM, (46, 134, 200))
d.ellipse([ex - 1.85*PXM/2 - 7, ey - 4.7*PXM/2 - 7, ex + 1.85*PXM/2 + 7, ey + 4.7*PXM/2 + 7],
          outline=(120, 220, 255, 120), width=2)
d.text((ex - 30, ey + 4.7*PXM/2 + 8), "EGO (내 차)", font=F(17), fill=(140, 230, 255))

d.text((24, 22), "AuraView BEV — YOLO11 실검출 · 핀홀 실측 치수", font=F(23), fill=(235, 245, 252))
d.text((24, 56), f"치수 = bbox 폭(px) × 거리 / 초점거리 (핀홀 계산) · 22px=1m · {b['summary']}",
       font=F(14), fill=(120, 175, 205))

im.save(os.path.join(ROOT, "docs", "captures", out_name))
print(f"saved {out_name} · {len(b['placed'])} objects · {b['summary']}")
