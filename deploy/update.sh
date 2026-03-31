#!/bin/bash
# =============================================================
# Recipe App 更新スクリプト（コード更新時に使用）
# 実行: bash update.sh
# =============================================================
set -e

APP_DIR="/home/ubuntu/recipe-app"

echo "=== コードを最新化 ==="
cd "$APP_DIR"
git pull

echo "=== 依存関係を更新 ==="
./venv/bin/pip install -r requirements.txt

echo "=== アプリを再起動 ==="
sudo systemctl restart recipe-app

sleep 2
sudo systemctl status recipe-app --no-pager
echo "✅ 更新完了"
