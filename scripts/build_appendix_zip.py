"""별첨 ZIP 자동 생성 — 기획서 + 별첨 PDF + binary (APK·모델 가중치·라이브 스냅샷) 단일 ZIP.

사용:
    python scripts/build_appendix_zip.py
    → docs/별첨_AuraView_2026.zip

포함:
    01_기획서_본문/         제출용_제품서비스_개발기획서.docx
    02_별첨_종합_PDF/       별첨_AuraView_2026.pdf (11페이지, 라이브 데이터 반영)
    03_AI_모델_가중치/      models/risk_transformer.pt + risk_transformer_trained_metric.json
    04_네이티브_APK/        app-release.apk (v12.170, 56MB)
    05_라이브_스냅샷/       /metrics/audit + /fusion/sources + /impact/submission-ready JSON
    06_라이센스_컴플라이언스/ LICENSE
    README.txt              구성 안내 + 라이브 검증 URL
"""

from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "별첨_AuraView_2026.zip"
LIVE = "https://auraview.allthatai.kr"


def _fetch(path):
    try:
        req = urllib.request.Request(f"{LIVE}{path}", headers={"User-Agent": "AuraView appendix-zip"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except Exception as exc:
        return json.dumps({"_error": str(exc)}, ensure_ascii=False, indent=2).encode("utf-8")


def build():
    # Windows cp949 stdout 한글 깨짐 방지
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"\n[Appendix-ZIP] Building {OUT.name} ...")
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # 라이브 스냅샷 수집
    print("                fetching live snapshots ...")
    snapshots = {
        "metrics_audit.json": _fetch("/metrics/audit"),
        "fusion_sources.json": _fetch("/fusion/sources"),
        "impact_submission_ready.json": _fetch("/impact/submission-ready"),
        "impact_top_intersections.json": _fetch("/impact/top-intersections?scope=seoul&top_n=10"),
        "policy_laws.json": _fetch("/policy/laws"),
        "metrics_manifest.json": _fetch("/metrics/manifest"),
        "metrics_data_attribution.json": _fetch("/metrics/data-attribution"),
        "ai_model_card.json": _fetch("/ai/model-card"),
    }

    # 파일 경로 정의
    items = {
        # 01. 기획서 본문 (docx)
        "01_기획서_본문/제출용_제품서비스_개발기획서.docx": ROOT / "docs" / "제출용_제품서비스_개발기획서.docx",
        # 02. 별첨 종합 PDF (11페이지)
        "02_별첨_종합_PDF/별첨_AuraView_2026.pdf": ROOT / "docs" / "별첨_AuraView_2026.pdf",
        # 03. AI 모델 가중치 + 학습 메트릭
        "03_AI_모델_가중치/risk_transformer.pt": ROOT / "models" / "risk_transformer.pt",
        "03_AI_모델_가중치/risk_transformer_trained_metric.json": ROOT / "models" / "risk_transformer_trained_metric.json",
        # 04. 네이티브 APK
        "04_네이티브_APK/AuraView_v12.170_arm64-v8a.apk": ROOT / "auraview_fleet" / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk",
        # 06. 라이센스
        "06_라이센스_컴플라이언스/LICENSE": ROOT / "LICENSE",
    }

    bundle_size = 0
    files_included = 0
    missing = []

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # 파일 추가
        for arc_name, src_path in items.items():
            if src_path.exists():
                zf.write(src_path, arcname=arc_name)
                size = src_path.stat().st_size
                bundle_size += size
                files_included += 1
                print(f"   [+] {arc_name}  ({size / 1024:.1f} KB)")
            else:
                missing.append(arc_name)
                print(f"   [!] MISSING: {arc_name}  ← {src_path}")

        # 05. 라이브 스냅샷 (메모리에서 직접 ZIP 에 쓰기)
        for fname, content in snapshots.items():
            arc_name = f"05_라이브_스냅샷/{fname}"
            zf.writestr(arc_name, content)
            files_included += 1
            print(f"   [+] {arc_name}  ({len(content) / 1024:.1f} KB · 라이브)")

        # README.txt
        readme = f"""AuraView K-Perception — 2026 국토교통 데이터활용 경진대회 별첨 자료

생성 시각: {datetime.now().isoformat()}
GitHub:    https://github.com/leelang7/AuraView (MIT)
라이브:    https://auraview.allthatai.kr

────────────────────────────────────────────────────────────
구성
────────────────────────────────────────────────────────────

01_기획서_본문/
   제출용_제품서비스_개발기획서.docx
   → 한컴 한글 또는 MS Word 로 열기. 3장 분량.

02_별첨_종합_PDF/
   별첨_AuraView_2026.pdf  (11 페이지)
   → 자가 진단 결과, 25 sources 카탈로그, Risk Transformer 모델 카드,
      8 시나리오 × 도로교통법 매핑, 정량 임팩트, 위험 교차로 Top-10,
      라이브 시스템 헬스, DSZ 컴플라이언스, 재현 가이드.

03_AI_모델_가중치/
   risk_transformer.pt                       AI 학습도구 증빙 (PyTorch state_dict)
   risk_transformer_trained_metric.json     학습 메트릭 (AUC/F1/loss curve)

04_네이티브_APK/
   AuraView_v12.170_arm64-v8a.apk           Galaxy Z Fold 3 검증, Android 14, ~56MB
   → adb install -r AuraView_v12.170_arm64-v8a.apk

05_라이브_스냅샷/                            본 ZIP 생성 시점의 라이브 응답
   metrics_audit.json                       전체 시스템 헬스
   fusion_sources.json                      25 소스 카탈로그 + freshness
   impact_submission_ready.json             9 게이트 자가 진단 (ready=true/9/9)
   impact_top_intersections.json            위험 교차로 Top-10 (서울)
   policy_laws.json                         8 시나리오 × 도로교통법 매핑
   metrics_manifest.json                    URL master index
   metrics_data_attribution.json            25 소스 라이센스 + 활용 위치
   ai_model_card.json                       Risk Transformer 모델 카드

06_라이센스_컴플라이언스/
   LICENSE                                  MIT + 공공데이터 컴플라이언스
                                            (개인정보보호법 28조의2 + 국토부 훈령 1456호)

────────────────────────────────────────────────────────────
라이브 1-step 검증 (평가자 활용)
────────────────────────────────────────────────────────────

  curl https://auraview.allthatai.kr/impact/submission-ready
  → ready=true, passed=9/9

  curl https://auraview.allthatai.kr/metrics/audit
  → 25 sources + tests 119/119 + git_sha + verified_pct

  curl https://auraview.allthatai.kr/impact/proposal-pdf -o proposal.pdf
  → 호출 시점 기준 자동 생성된 3-page 기획서 PDF

────────────────────────────────────────────────────────────
재현 (개발자 검증용)
────────────────────────────────────────────────────────────

  git clone https://github.com/leelang7/AuraView
  cd AuraView
  docker compose up -d
  python -m pytest backend/tests/   # 119 / 119 PASS 기대

────────────────────────────────────────────────────────────
"""
        zf.writestr("README.txt", readme)
        files_included += 1

    final_size = OUT.stat().st_size
    print(f"\n[OK] {OUT}")
    print(f"     Total: {files_included} files · {final_size / (1024 * 1024):.2f} MB")
    if missing:
        print(f"\n[Warning] Missing files (별첨 일부 누락):")
        for m in missing:
            print(f"   - {m}")
        print("   → 필요 시 해당 파일 생성 후 본 스크립트 재실행.")


if __name__ == "__main__":
    build()
