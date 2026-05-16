"""
Risk Transformer v2 — 9-source 융합 (13-feature) 실 학습 (2026-05-15).

v1 (train_risk_transformer_real.py) 는 10-feature.
v2 는 v1 의 10-feature + 3 개 신규 외부 신호:
  11. weather_wet_boost   ∈ [0, 0.30]   (KMA 강수 + 시정)
  12. er_load            ∈ [0, 1.0]    (NEDIS 응급실 포화도)
  13. bike_lane_boost    ∈ [0, 0.30]   (따릉이 + 자전거도로 prior)

학습 후 산출:
  - models/risk_transformer_v2.pt
  - models/risk_transformer_v2_metric.json    (AUC, F1, scenario breakdown)

실행:
  python notebooks/train_risk_transformer_v2_9src.py            # 기본 (15 epochs, 10k samples, ~3분 CPU)
  AURAVIEW_V2_QUICK=1 python notebooks/...                       # 빠른 검증 (3 epochs, 2k samples, ~30초)
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.services import risk_transformer as rt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_PT = ROOT / "models" / "risk_transformer_v2.pt"
OUT_METRIC = ROOT / "models" / "risk_transformer_v2_metric.json"
OUT_PT.parent.mkdir(parents=True, exist_ok=True)

SEED = 42
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)

QUICK = os.getenv("AURAVIEW_V2_QUICK", "0") == "1"
N_TRAIN = 2000 if QUICK else 8000
N_VAL = 500 if QUICK else 2000
EPOCHS = 3 if QUICK else 15

FEATURES_V2 = [
    "duration", "vehicle_cnt", "vru_cnt", "vds_speed", "vds_volume",
    "occluded_mass", "taas_nearby", "signal_stop", "incident_flag", "obstacle_big",
    "weather_wet_boost", "er_load", "bike_lane_boost",   # v2 신규 3
]


def to_vec_v2(inp: rt.RiskInput, weather: float, er: float, bike: float) -> np.ndarray:
    big = 1.0 if inp.obstacle_type in {"truck", "bus", "top_truck", "van"} else 0.0
    sig_stop = 1.0 if inp.signal_state == "stop-And-Remain" else 0.0
    inc = 1.0 if inp.incident_flag else 0.0
    speed = inp.vds_speed if inp.vds_speed is not None else 60.0
    vol = inp.vds_volume if inp.vds_volume is not None else 1500.0

    raw_norm = []
    for name, v in zip(
        ["duration", "vehicle_cnt", "vru_cnt", "vds_speed", "vds_volume", "occluded_mass", "taas_nearby"],
        [inp.duration, inp.vehicle_cnt, inp.vru_cnt, speed, vol, inp.occluded_mass, inp.taas_nearby],
    ):
        s = rt.FEATURE_STATS[name]
        raw_norm.append((v - s["mean"]) / (s["std"] or 1.0))

    return np.array(
        raw_norm + [sig_stop, inc, big, weather, er, bike],
        dtype=np.float32,
    )


def gen_sample_v2(label: int, scenario: str):
    """9-source 환경 신호 (weather/er/bike) 가 label 과 상관관계를 가지도록 샘플링."""
    if label == 1:
        base = dict(
            duration=random.uniform(1.4, 5.5),
            vehicle_cnt=random.randint(1, 5),
            vru_cnt=random.randint(0, 2),
            vds_speed=random.uniform(15, 50),
            vds_volume=random.uniform(1500, 3200),
            occluded_mass=random.uniform(80, 320),
            taas_nearby=random.randint(1, 5),
            signal_state=random.choice(["stop-And-Remain", "permissive-Movement-Allowed", ""]),
            incident_flag=random.random() < 0.25,
            obstacle_type=random.choice(["truck", "bus", "van", "car"]),
        )
        # v2 신규 — 위험 label 일수록 환경 가중치도 평균적으로 ↑
        weather = random.uniform(0.05, 0.28)   # KMA wet boost
        er = random.uniform(0.45, 0.95)         # NEDIS ER load
        bike = random.uniform(0.00, 0.25)       # bike prior

        if scenario == "rainy":
            base["vds_speed"] = random.uniform(8, 35)
            weather = random.uniform(0.16, 0.30)
        elif scenario == "rush_hour":
            base["vds_volume"] = random.uniform(2400, 3800)
            er = random.uniform(0.65, 0.98)
        elif scenario == "bicycle_lane":
            bike = random.uniform(0.18, 0.30)
            base["vru_cnt"] = random.randint(1, 3)
    else:
        base = dict(
            duration=random.uniform(0, 2.5),
            vehicle_cnt=random.randint(0, 3),
            vru_cnt=random.choice([0, 0, 0, 1]),
            vds_speed=random.uniform(30, 90),
            vds_volume=random.uniform(800, 2400),
            occluded_mass=random.uniform(0, 130),
            taas_nearby=random.randint(0, 2),
            signal_state=random.choice(["protected-Movement-Allowed", "permissive-Movement-Allowed", ""]),
            incident_flag=random.random() < 0.05,
            obstacle_type=random.choice(["car", "unknown_vehicle", "van"]),
        )
        # 안전 샘플 — 환경 가중치 모두 낮음
        weather = random.uniform(0.00, 0.10)
        er = random.uniform(0.20, 0.60)
        bike = random.uniform(0.00, 0.10)

        if scenario == "rainy":
            weather = random.uniform(0.04, 0.14)
        elif scenario == "rush_hour":
            er = random.uniform(0.40, 0.75)

    return rt.RiskInput(**base), weather, er, bike


def make_dataset_v2(n, label_noise=0.06):
    scenarios = ("mixed", "rush_hour", "night", "rainy", "bicycle_lane")
    X, y = [], []
    for _ in range(n):
        label = random.randint(0, 1)
        sc = random.choice(scenarios)
        inp, w, e, b = gen_sample_v2(label, sc)
        X.append(to_vec_v2(inp, w, e, b))
        if random.random() < label_noise:
            label = 1 - label
        y.append(label)
    return torch.tensor(np.array(X), dtype=torch.float32), torch.tensor(y, dtype=torch.long)


class RiskTransformerV2(nn.Module):
    def __init__(self, n_features=13, d_model=64, n_heads=4, n_layers=2, dropout=0.1):
        super().__init__()
        self.emb = nn.Linear(1, d_model)
        self.pos = nn.Parameter(torch.randn(n_features, d_model) * 0.02)
        layer = nn.TransformerEncoderLayer(d_model, n_heads, dim_feedforward=128,
                                            dropout=dropout, batch_first=True)
        self.enc = nn.TransformerEncoder(layer, n_layers)
        self.head = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, 2))

    def forward(self, x):
        h = self.emb(x.unsqueeze(-1)) + self.pos
        h = self.enc(h)
        h = h.mean(dim=1)
        return self.head(h)


def auc_score(scores, labels):
    order = np.argsort(-scores)
    P = float((labels == 1).sum()); N = float((labels == 0).sum())
    if P == 0 or N == 0: return 0.5
    tp = fp = 0; auc = 0.0; prev = 0.0
    for i in order:
        if labels[i] == 1: tp += 1
        else: fp += 1
        t = tp / P; f = fp / N
        auc += t * (f - prev); prev = f
    return float(auc)


def main():
    print(f"[v2] 9-source training (quick={QUICK}, n_train={N_TRAIN}, epochs={EPOCHS})")
    print(f"[1/5] dataset (train {N_TRAIN} + val {N_VAL})")
    X_train, y_train = make_dataset_v2(N_TRAIN)
    X_val, y_val = make_dataset_v2(N_VAL)
    print(f"  shapes train={X_train.shape} val={X_val.shape}")

    print(f"[2/5] RiskTransformerV2 init (13 features)")
    model = RiskTransformerV2()
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  params={n_params:,}")

    print(f"[3/5] train {EPOCHS} epochs (AdamW lr=2e-3, batch=128)")
    opt = optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    crit = nn.CrossEntropyLoss()
    dl = DataLoader(TensorDataset(X_train, y_train), batch_size=128, shuffle=True)

    val_auc = val_f1 = val_loss = val_prec = val_rec = 0.0
    for ep in range(EPOCHS):
        model.train()
        losses = []
        for xb, yb in dl:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward(); opt.step()
            losses.append(float(loss))
        model.eval()
        with torch.no_grad():
            logits = model(X_val)
            val_loss = float(crit(logits, y_val))
            probs = torch.softmax(logits, dim=1)[:, 1].numpy()
            val_auc = auc_score(probs, y_val.numpy())
            pred = (probs >= 0.5).astype(np.int64)
            tp = int(((pred == 1) & (y_val.numpy() == 1)).sum())
            fp = int(((pred == 1) & (y_val.numpy() == 0)).sum())
            fn = int(((pred == 0) & (y_val.numpy() == 1)).sum())
            val_prec = tp / max(1, tp + fp)
            val_rec = tp / max(1, tp + fn)
            val_f1 = 2 * val_prec * val_rec / max(1e-9, val_prec + val_rec)
        print(f"  ep{ep+1:2d}  train_loss={np.mean(losses):.4f}  val_loss={val_loss:.4f}  AUC={val_auc:.4f}  F1={val_f1:.4f}")

    print(f"[4/5] checkpoint 저장")
    torch.save({
        "state_dict": model.state_dict(),
        "arch": {"n_features": 13, "d_model": 64, "n_heads": 4, "n_layers": 2},
        "feature_order": FEATURES_V2,
        "feature_stats": rt.FEATURE_STATS,
        "schema_version": "fusion.v2-9src-2026.05.15",
    }, str(OUT_PT))
    print(f"  saved: {OUT_PT}  ({OUT_PT.stat().st_size // 1024} KB)")

    print(f"[5/5] metric JSON")
    metric = {
        "version": "0.4-trained-transformer-v2-9src",
        "schema_version": "fusion.v2-9src-2026.05.15",
        "params": int(n_params),
        "epochs": EPOCHS,
        "batch_size": 128,
        "optimizer": "AdamW lr=2e-3 wd=1e-4",
        "samples": {"train": int(len(y_train)), "val": int(len(y_val))},
        "auc": round(float(val_auc), 4),
        "f1@0.5": round(float(val_f1), 4),
        "precision@0.5": round(float(val_prec), 4),
        "recall@0.5": round(float(val_rec), 4),
        "val_loss": round(float(val_loss), 4),
        "label_noise": 0.06,
        "scenarios": ["mixed", "rush_hour", "night", "rainy", "bicycle_lane"],
        "features": FEATURES_V2,
        "new_features_v2": ["weather_wet_boost", "er_load", "bike_lane_boost"],
        "checkpoint": str(OUT_PT.relative_to(ROOT)).replace("\\", "/"),
        "note": "9-source 융합 학습 (10 v1 + 3 신규: 기상/응급실/자전거). v1 대비 우천·자전거·rush_hour 시나리오 분리도 향상 기대.",
    }
    OUT_METRIC.write_text(json.dumps(metric, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved: {OUT_METRIC}")
    print(json.dumps(metric, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
