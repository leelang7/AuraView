#!/usr/bin/env bash
# AuraView monorepo → allthatai-landing GitHub Pages 자동 sync
#
# 사용:
#   bash scripts/sync-landing.sh              # 자동 커밋 메시지
#   bash scripts/sync-landing.sh "msg"        # 커스텀 커밋 메시지
#
# 동작:
#   1. /tmp 에 allthatai-landing 클론 (얕게)
#   2. AuraView/landing/ 의 index.html · CNAME · *.css · *.js · 이미지 등을 덮어쓰기
#   3. 변화 있으면 커밋 + main 으로 push
#
# 필요: 본인 GitHub 자격 증명이 git credential helper 에 등록돼 있어야 함.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/landing"
TMP="$(mktemp -d -t auraview-sync-XXXX)"
TRG="https://github.com/leelang7/allthatai-landing.git"
MSG="${1:-sync landing from AuraView monorepo $(date -u +%Y-%m-%dT%H:%MZ)}"

echo "▶ source : $SRC"
echo "▶ target : $TRG"
echo "▶ tmp    : $TMP"

if [ ! -d "$SRC" ]; then
  echo "✗ landing/ 폴더가 없습니다." >&2
  exit 1
fi

git clone --depth 1 "$TRG" "$TMP"
cd "$TMP"

# CNAME 은 항상 동기화
cp "$SRC/CNAME" "$TMP/CNAME"

# index.html 같은 정적 파일들 — landing/ 의 모든 파일/디렉토리(.git 제외) 로 덮어씀
shopt -s dotglob
for f in "$SRC"/*; do
  base="$(basename "$f")"
  case "$base" in
    .git|node_modules) continue ;;
    *) cp -r "$f" "$TMP/" ;;
  esac
done

if [ -z "$(git -C "$TMP" status --porcelain)" ]; then
  echo "✓ 변경 없음 — push 생략."
  exit 0
fi

git -c user.name="leelang7" -c user.email="leescvsir@gmail.com" \
    -C "$TMP" add -A
git -c user.name="leelang7" -c user.email="leescvsir@gmail.com" \
    -C "$TMP" commit -m "$MSG"
git -C "$TMP" push origin main
echo "✓ allthatai-landing 으로 push 완료."
