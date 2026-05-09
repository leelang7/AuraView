"""
신규 router 통합 테스트 — /privacy · /ai · /competition

경진대회 가점 25점 증빙 엔드포인트 전체 smoke test.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ─── /privacy ─────────────────────────────────────────────────────────────────

def test_privacy_pipeline_spec_200():
    r = client.get("/privacy/pipeline-spec")
    assert r.status_code == 200
    j = r.json()
    assert "steps" in j
    assert len(j["steps"]) == 6
    assert j["k_anonymity_k"] == 5
    assert "standard" in j


def test_privacy_pseudonymize_returns_masked_ids():
    r = client.post("/privacy/pseudonymize", json={
        "ids": ["VEHICLE-001", "VEHICLE-002"],
        "data_category": "vehicle_id",
    })
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 2
    results = j["results"]
    assert len(results) == 2
    for res in results:
        assert len(res["pseudonymized"]) == 16
        assert res["irreversible"] is True
        assert res["method"] == "HMAC-SHA256[:16]"


def test_privacy_pseudonymize_deterministic():
    """동일 입력 → 동일 출력 (HMAC 특성)."""
    payload = {"ids": ["TEST-ID-XYZ"], "data_category": "vehicle_id"}
    r1 = client.post("/privacy/pseudonymize", json=payload)
    r2 = client.post("/privacy/pseudonymize", json=payload)
    assert r1.json()["results"][0]["pseudonymized"] == r2.json()["results"][0]["pseudonymized"]


def test_privacy_k_anonymize_removes_small_groups():
    records = [
        {"district_code": "11680", "date_hour": "2024-08-14-18", "accident_type": "추돌"},
        {"district_code": "11680", "date_hour": "2024-08-14-18", "accident_type": "추돌"},
        {"district_code": "11680", "date_hour": "2024-08-14-18", "accident_type": "추돌"},
        {"district_code": "11680", "date_hour": "2024-08-14-18", "accident_type": "추돌"},
        {"district_code": "11680", "date_hour": "2024-08-14-18", "accident_type": "추돌"},
        {"district_code": "99999", "date_hour": "2024-08-14-18", "accident_type": "단독"},
    ]
    r = client.post("/privacy/k-anonymize", json={
        "records": records,
        "quasi_identifiers": ["district_code", "date_hour", "accident_type"],
        "k": 5,
    })
    assert r.status_code == 200
    j = r.json()
    assert j["k_threshold"] == 5
    # 11680 그룹(5개) 통과, 99999 그룹(1개) 제거
    assert j["passed_records"] == 5
    assert j["removed_records"] == 1


def test_privacy_demo_join_returns_pipeline_result():
    r = client.post("/privacy/demo-join", json={
        "taas_count": 20,
        "vds_count": 30,
        "district_code": "11680",
    })
    assert r.status_code == 200
    j = r.json()
    assert "export_statistics" in j
    assert "k_anonymity" in j
    assert j["k_anonymity"]["k"] == 5
    assert j["input"]["pii_fields_excluded"] is not None


def test_privacy_evidence_report_has_all_items():
    r = client.get("/privacy/evidence-report")
    assert r.status_code == 200
    j = r.json()
    assert j["score_category"] == "가명정보결합 5점"
    evidence_items = {e["item"] for e in j["evidence"]}
    for required in ("가명화 구현", "k-익명성 검증", "결합키 설계", "반출 통제"):
        assert required in evidence_items, f"evidence missing: {required}"


# ─── /ai ──────────────────────────────────────────────────────────────────────

def test_ai_model_card_200():
    r = client.get("/ai/model-card")
    assert r.status_code == 200
    j = r.json()
    assert j["model_name"] == "AuraView Risk Transformer"
    assert j["performance"]["auc_roc"] >= 0.90
    assert j["performance"]["f1_score"] >= 0.90
    assert "학습_5점" in j["ai_score_claim"]
    assert "분석_5점" in j["ai_score_claim"]


def test_ai_training_history_has_correct_epochs():
    r = client.get("/ai/training-history")
    assert r.status_code == 200
    j = r.json()
    assert j["epochs"] == 15
    assert len(j["history"]) == 15
    # 마지막 epoch의 AUC가 final_auc와 일치
    last = j["history"][-1]
    assert abs(last["val_auc"] - j["final_auc"]) < 0.01


def test_ai_roc_curve_has_valid_points():
    r = client.get("/ai/roc-curve")
    assert r.status_code == 200
    j = r.json()
    assert j["auc"] == 0.9403
    points = j["roc_points"]
    assert len(points) >= 50
    # 첫 점 (0,0), 마지막 점 (1,1)
    assert points[0]["fpr"] == 0.0 and points[0]["tpr"] == 0.0
    assert points[-1]["fpr"] == 1.0 and points[-1]["tpr"] == 1.0
    # 단조증가 확인 (FPR)
    fprs = [p["fpr"] for p in points]
    assert fprs == sorted(fprs)


def test_ai_confusion_matrix_sums_correctly():
    r = client.get("/ai/confusion-matrix")
    assert r.status_code == 200
    j = r.json()
    m = j["matrix"]
    report = j["classification_report"]
    total = m["true_positive"] + m["false_negative"] + m["false_positive"] + m["true_negative"]
    assert total == report["support_total"]
    assert report["precision"] >= 0.90
    assert report["recall"] >= 0.90


def test_ai_feature_importance_sums_to_one():
    r = client.get("/ai/feature-importance")
    assert r.status_code == 200
    j = r.json()
    features = j["features"]
    assert len(features) == 10
    total = sum(f["importance"] for f in features)
    assert abs(total - 1.0) < 0.05  # 반올림 오차 허용


def test_ai_scenario_analysis_four_scenarios():
    r = client.get("/ai/scenario-analysis")
    assert r.status_code == 200
    j = r.json()
    results = j["scenarios"]
    assert len(results) == 4
    scenario_names = {s["scenario"] for s in results}
    assert scenario_names == {"mixed", "rush_hour", "night", "rainy"}
    for s in results:
        assert 0.0 <= s["p_collision"] <= 1.0
        assert s["risk_level"] in ("LOW", "MEDIUM", "HIGH")


def test_ai_live_inference_returns_risk():
    r = client.post("/ai/live-inference", json={
        "duration": 5.0,
        "vehicle_cnt": 3,
        "vru_cnt": 1,
        "vds_speed": 20.0,
        "vds_volume": 2400,
        "occluded_mass": 200.0,
        "taas_nearby": 2,
        "signal_state": "stop-And-Remain",
        "incident_flag": True,
        "obstacle_type": "truck",
    })
    assert r.status_code == 200
    j = r.json()
    out = j["output"]
    assert 0.0 <= out["p_collision"] <= 1.0
    assert out["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert j["latency_ms"] < 1000  # 1초 이내


def test_ai_evidence_report_has_10_point_claim():
    r = client.get("/ai/evidence-report")
    assert r.status_code == 200
    j = r.json()
    assert j["score_category"] == "AI활용 10점 (학습 5점 + 분석 5점)"
    assert len(j["학습_5점"]["evidence"]) >= 4
    assert len(j["분석_5점"]["evidence"]) >= 4
    metrics = j["학습_5점"]["metrics"]
    assert metrics["AUC-ROC"] >= 0.90


# ─── /competition ─────────────────────────────────────────────────────────────

def test_competition_scorecard_25_points():
    r = client.get("/competition/scorecard")
    assert r.status_code == 200
    j = r.json()
    assert j["total_possible"] == 25
    assert j["total_claimed"] == 25
    assert len(j["score_items"]) == 4
    for item in j["score_items"]:
        assert item["claimed"] == item["max_score"]


def test_competition_scorecard_has_evidence_for_all():
    r = client.get("/competition/scorecard")
    j = r.json()
    for item in j["score_items"]:
        assert len(item["evidence"]) >= 3
        assert len(item["endpoints"]) >= 1


def test_competition_summary_has_kpis():
    r = client.get("/competition/summary")
    assert r.status_code == 200
    j = r.json()
    assert j["ai_performance"]["auc"] >= 0.90
    assert j["competition_score"]["total_claimed"] == 25
    assert j["safety_impact"]["estimated_accidents_prevented_per_year"] > 1000


def test_competition_api_map_covers_all_categories():
    r = client.get("/competition/api-map")
    assert r.status_code == 200
    j = r.json()
    mappings = j["mapping"]
    score_items = {m["score_item"] for m in mappings}
    for needed in ("AI활용/학습", "AI활용/분석", "데이터융합", "가명정보결합", "안심구역"):
        assert needed in score_items, f"api-map missing category: {needed}"


def test_competition_checklist_passes_basic_items():
    r = client.get("/competition/checklist")
    assert r.status_code == 200
    j = r.json()
    assert "checklist" in j
    assert j["days_remaining"] > 0
    # 반드시 True여야 하는 항목들
    by_item = {c["item"]: c["ok"] for c in j["checklist"]}
    assert by_item.get("AI 증빙 엔드포인트 응답 (GET /ai/evidence-report)") is True
    assert by_item.get("경진대회 가점 스코어카드 (GET /competition/scorecard)") is True


# ─── /dsz 신규 엔드포인트 ─────────────────────────────────────────────────────

def test_dsz_pipeline_report_200():
    r = client.get("/dsz/pipeline-report")
    assert r.status_code == 200
    j = r.json()
    assert j["score_category"] == "안심구역(국토교통 데이터안심구역 dsz.ex.co.kr) 5점"
    assert len(j["pipeline_overview"]) == 6
    assert "compliance" in j


def test_dsz_seed_demo_creates_artifact():
    r = client.post("/dsz/seed-demo")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "created"
    assert j["rows"] > 0
    assert len(j["sha256"]) == 64
    assert j["artifact_path"].endswith(".json")


def test_dsz_compliance_status_200():
    r = client.get("/dsz/compliance-status")
    assert r.status_code == 200
    j = r.json()
    assert j["k_anonymity"]["enabled"] is True
    assert j["pii_masking"]["enabled"] is True
    assert len(j["pii_masking"]["methods"]) >= 2
