"""
Risk Transformer 합성 데이터 baseline 학습 → metric.

작성 목적:
  - 백서·발표자료에 박을 *수치 결과* 확보 (AUC, F1, lead-time 등)
  - 실제 사고/Fleet 데이터가 부족한 시점에서도 모델 거동 검증
  - CI / 재현 가능한 결과 (random seed 고정)

산출:
  - models/risk_transformer_metric.json  ← 발표자료 자동 인용
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services import risk_transformer as rt   # noqa: E402

OUT = Path(os.path.join(os.path.dirname(__file__), "..", "models", "risk_transformer_metric.json"))
OUT.parent.mkdir(parents=True, exist_ok=True)

random.seed(42)


def _gen_sample(label: int, scenario: str = "mixed"):
    """label=1 위험, label=0 안전. scenario 별 분포 차등.

    scenarios:
      'mixed'      혼합 (기본)
      'rush_hour'  러시아워 — 정체·VRU 많음
      'night'      야간 — 시야 가림 ↑·신호 정확 ↓
      'rainy'      우천 — occlusion ↑·속도 ↓
    """
    if label == 1:
        base = dict(
            duration=random.uniform(1.4, 5.5),
            vehicle_cnt=random.randint(1, 5),
            vru_cnt=random.randint(0, 2),
            vds_speed=random.uniform(15.0, 50.0),
            vds_volume=random.uniform(1500, 3200),
            occluded_mass=random.uniform(80.0, 320.0),
            taas_nearby=random.randint(1, 5),
            signal_state=random.choice(["stop-And-Remain", "permissive-Movement-Allowed", ""]),
            incident_flag=random.random() < 0.25,
            obstacle_type=random.choice(["truck", "bus", "van", "car"]),
        )
        if scenario == "rush_hour":
            base["vds_speed"] = random.uniform(5, 25)
            base["vds_volume"] = random.uniform(2400, 3800)
            base["vru_cnt"] = random.randint(1, 3)
        elif scenario == "night":
            base["occluded_mass"] = random.uniform(180, 450)
            base["incident_flag"] = random.random() < 0.40
        elif scenario == "rainy":
            base["occluded_mass"] = random.uniform(150, 400)
            base["vds_speed"] = random.uniform(8, 35)
        return rt.RiskInput(**base)

    base = dict(
        duration=random.uniform(0.0, 2.5),
        vehicle_cnt=random.randint(0, 3),
        vru_cnt=random.choice([0, 0, 0, 1]),
        vds_speed=random.uniform(30.0, 90.0),
        vds_volume=random.uniform(800, 2400),
        occluded_mass=random.uniform(0.0, 130.0),
        taas_nearby=random.randint(0, 2),
        signal_state=random.choice(["protected-Movement-Allowed", "permissive-Movement-Allowed", ""]),
        incident_flag=random.random() < 0.05,
        obstacle_type=random.choice(["car", "unknown_vehicle", "van"]),
    )
    if scenario == "rush_hour":
        base["vds_volume"] = random.uniform(1200, 2600)
        base["vds_speed"] = random.uniform(20, 60)
    elif scenario == "night":
        base["occluded_mass"] = random.uniform(40, 200)
    elif scenario == "rainy":
        base["vds_speed"] = random.uniform(20, 70)
    return rt.RiskInput(**base)


def _label_with_noise(true_label: int, swap_p: float = 0.06) -> int:
    """라벨 노이즈 — 사후 사고/미사고 자체에 노이즈가 있다는 가정."""
    if random.random() < swap_p:
        return 1 - true_label
    return true_label


def evaluate(n: int = 2000, scenarios=("mixed", "rush_hour", "night", "rainy")):
    samples = []
    per_scenario = {}
    for sc in scenarios:
        per_scenario[sc] = []

    for i in range(n):
        true_label = random.randint(0, 1)
        sc = random.choice(scenarios)
        sample = _gen_sample(label=true_label, scenario=sc)
        score = rt.predict(sample).p_collision
        observed_label = _label_with_noise(true_label)
        samples.append((score, observed_label))
        per_scenario[sc].append((score, observed_label))

    # ROC AUC
    sorted_s = sorted(samples, key=lambda x: -x[0])
    P = sum(1 for _, y in samples if y == 1)
    N = len(samples) - P
    tp = fp = 0
    auc = 0.0
    prev_fpr = 0.0
    for score, y in sorted_s:
        if y == 1: tp += 1
        else: fp += 1
        tpr = tp / max(1, P)
        fpr = fp / max(1, N)
        auc += tpr * (fpr - prev_fpr)
        prev_fpr = fpr

    # F1 @ 0.5
    threshold = 0.5
    tp = sum(1 for s, y in samples if s >= threshold and y == 1)
    fp = sum(1 for s, y in samples if s >= threshold and y == 0)
    fn = sum(1 for s, y in samples if s <  threshold and y == 1)
    prec = tp / max(1, tp + fp)
    rec  = tp / max(1, tp + fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)

    # 시나리오별 평균 score (분리도 — 모델이 시나리오를 다르게 평가하는지)
    per_sc_avg_score = {}
    for sc, ss in per_scenario.items():
        if len(ss) < 10: continue
        pos = [s for s, y in ss if y == 1]
        neg = [s for s, y in ss if y == 0]
        per_sc_avg_score[sc] = {
            "n": len(ss),
            "pos_avg": round(sum(pos) / max(1, len(pos)), 3),
            "neg_avg": round(sum(neg) / max(1, len(neg)), 3),
            "separation": round(sum(pos) / max(1, len(pos)) - sum(neg) / max(1, len(neg)), 3),
        }

    # Lead-time 시뮬
    lead_durations = [s.duration for s in [_gen_sample(1, "mixed") for _ in range(200)]]
    avg_lead = sum(lead_durations) / max(1, len(lead_durations))

    return {
        "version": "0.2-baseline-logistic-multi-scenario",
        "samples": n,
        "scenarios_per_class": list(scenarios),
        "auc": round(auc, 4),
        "f1@0.5": round(f1, 4),
        "precision@0.5": round(prec, 4),
        "recall@0.5": round(rec, 4),
        "scenario_separation": per_sc_avg_score,
        "avg_lead_time_synth_s": round(avg_lead, 2),
        "note": (
            "Risk Transformer 의 해석 가능 baseline (linear logistic) 에 4개 시나리오 (혼합/러시아워/야간/우천) "
            "분포로 평가. 실 데이터·trained Transformer 로 교체 시 AUC ≥ 0.85, F1 ≥ 0.80 목표."
        ),
    }


if __name__ == "__main__":
    metric = evaluate()
    OUT.write_text(json.dumps(metric, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metric, indent=2, ensure_ascii=False))
