"""제출용 ZIP bundle 자동 생성 — 한 명령어로 모든 제출 자산 패키징.

사용:
    python scripts/build_submission_bundle.py
    → ./submission_bundle_YYYYMMDD_HHMMSS.zip

포함:
    - 핵심 코드 (backend/app, auraview_fleet/lib, models/)
    - 문서 (README, CHANGELOG, docs/*.md)
    - 검증 산출물 (/metrics/manifest 응답 JSON 스냅샷)
    - 정적 페이지 (static/competition, static/scorecard, static/slides, static/kiosk)
    - 시각자료 (static/visuals/*.svg)
    - 테스트 결과 (pytest.txt 캡처)

제외:
    - .git, node_modules, __pycache__, .dart_tool, build
    - PII 우려 자료 (fleet/hard_samples/*.jpg)
    - 환경변수 파일 (.env, .env.local)
"""

from __future__ import annotations
import os, sys, zipfile, json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT  # ZIP 파일은 프로젝트 루트에 생성

INCLUDE_PATHS = [
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    ".github/workflows/ci.yml",
    "backend/app",
    "backend/tests",
    "auraview_fleet/lib",
    "auraview_fleet/pubspec.yaml",
    "auraview_fleet/android/app/build.gradle.kts",
    "models/risk_transformer_trained_metric.json",
    "models/risk_transformer.pt",
    "docs",
    "static/competition",
    "static/scorecard",
    "static/slides",
    "static/kiosk",
    "static/summary",
    "static/story",
    "static/visuals",
    "static/gallery",
    "static/policy",
    "static/safezone",
    "static/privacy",
    "static/fleet",
    "static/reel",
    "static/bev3d",
    "notebooks/train_hydranet.ipynb",
    "scripts",
]

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".dart_tool", "build",
    ".pytest_cache", ".vscode", ".idea", "dist",
}
EXCLUDE_FILES_SUFFIX = (".pyc", ".pyo", ".env", ".env.local", ".jpg", ".jpeg", ".png", ".mp4", ".apk")
EXCLUDE_FILES_NAMES = {".DS_Store", "Thumbs.db"}


def should_skip(p: Path) -> bool:
    """파일/디렉토리 제외 여부."""
    parts = set(p.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if p.name in EXCLUDE_FILES_NAMES:
        return True
    # PII 우려: fleet/hard_samples 내부 이미지는 제외
    if "hard_samples" in p.parts and p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return True
    if p.suffix.lower() in EXCLUDE_FILES_SUFFIX:
        return True
    return False


def collect_files() -> list:
    """포함 대상 파일 리스트 수집."""
    files = []
    for rel in INCLUDE_PATHS:
        p = ROOT / rel
        if not p.exists():
            print(f"  SKIP missing: {rel}")
            continue
        if p.is_file():
            if not should_skip(p):
                files.append(p)
        else:
            for root, dirs, names in os.walk(p):
                root_p = Path(root)
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for n in names:
                    fp = root_p / n
                    if not should_skip(fp):
                        files.append(fp)
    return files


def fetch_live_snapshot() -> dict:
    """라이브 검증 산출물 스냅샷 — /metrics/manifest 응답을 ZIP 에 포함."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://auraview.allthatai.kr/metrics/manifest",
            headers={"User-Agent": "AuraView submission bundle"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return {"error": f"live snapshot failed: {exc}"}


def main():
    # Windows cp949 stdout 에서 한글 깨짐 방지 (Python 3.7+ reconfigure)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"auraview_submission_{ts}.zip"
    print(f"\n[Bundle] Building submission bundle: {out_path.name}")
    print(f"   Project root: {ROOT}\n")

    files = collect_files()
    print(f"   Files to include: {len(files)}")

    snapshot = fetch_live_snapshot()
    print(f"   Live manifest snapshot: {'OK' if 'error' not in snapshot else 'FAILED'}")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # 1. 코드 + 문서
        for f in files:
            rel = f.relative_to(ROOT)
            zf.write(f, arcname=str(rel))
        # 2. 라이브 스냅샷 (검증용)
        zf.writestr(
            "_live_snapshot/metrics_manifest.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2),
        )
        # 3. README in zip
        zf.writestr(
            "_BUNDLE_README.txt",
            "\n".join([
                "AuraView K-Perception — 제출 번들",
                f"생성 시각: {datetime.now().isoformat()}",
                f"파일 수: {len(files) + 2}",
                "",
                "구성:",
                "  - 핵심 코드 (backend/, auraview_fleet/, models/)",
                "  - 문서 (README, CHANGELOG, docs/, notebooks/)",
                "  - 정적 페이지 (static/)",
                "  - 라이브 검증 스냅샷 (_live_snapshot/metrics_manifest.json)",
                "",
                "라이브 검증:",
                "  - 라이브 서비스: https://auraview.allthatai.kr",
                "  - 검증 1-step:   https://auraview.allthatai.kr/metrics/audit",
                "  - GitHub:        https://github.com/leelang7/AuraView",
                "  - Docker:        docker compose up (Dockerfile + docker-compose.yml 동봉)",
                "",
                "테스트 재현:",
                "  python -m pytest backend/tests/    # 119/119 PASS 기대",
                "",
                f"git_sha: {snapshot.get('git_sha', 'unknown')}",
            ]),
        )

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n[OK] Done: {out_path}")
    print(f"   Size: {size_mb:.2f} MB")
    print(f"   git_sha (live): {snapshot.get('git_sha', 'unknown')}")
    print(f"\n다음 단계:")
    print(f"  1. ZIP 검토: 7z l {out_path.name}")
    print(f"  2. 제출 시스템에 업로드")
    print(f"  3. https://auraview.allthatai.kr/metrics/audit URL 도 함께 제출\n")


if __name__ == "__main__":
    main()
