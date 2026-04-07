#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-$SCRIPT_DIR/../Nesting-Sandbox-Android}"
REMOTE_URL="${2:-}"

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"

rsync -a \
  --exclude='.git' \
  --exclude='.gradle' \
  --exclude='build' \
  --exclude='app/build' \
  "$SCRIPT_DIR/" "$TARGET_DIR/"

pushd "$TARGET_DIR" > /dev/null

git init -b main

git add .
git commit -m "Initial Android app for Nesting Sandbox"

if [[ -n "$REMOTE_URL" ]]; then
  git remote add origin "$REMOTE_URL"
  git push -u origin main
fi

popd > /dev/null

echo "Standalone Android repo created at: $TARGET_DIR"
if [[ -n "$REMOTE_URL" ]]; then
  echo "Pushed to: $REMOTE_URL"
else
  echo "No remote provided. To push later:"
  echo "  cd $TARGET_DIR"
  echo "  git remote add origin <your-remote-url>"
  echo "  git push -u origin main"
fi
