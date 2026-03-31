#!/bin/bash
# =============================================================
# Recipe App デプロイスクリプト（Xserver VPS / Ubuntu）
# 実行: bash setup.sh
# =============================================================
set -e

APP_DIR="/home/ubuntu/recipe-app"
REPO_URL="https://github.com/mamizonoria/recipe-app.git"

echo "=== [1/8] パッケージ更新 ==="
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv nginx git

echo "=== [2/8] リポジトリをクローン/更新 ==="
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

echo "=== [3/8] Python仮想環境のセットアップ ==="
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "=== [4/8] .envファイルの確認 ==="
if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERROR: .envファイルが存在しません"
    echo "次のコマンドで作成してください:"
    echo "  nano $APP_DIR/.env"
    echo ""
    echo "必要な環境変数:"
    echo "  DATABASE_URL=..."
    echo "  CLOUDINARY_CLOUD_NAME=..."
    echo "  CLOUDINARY_API_KEY=..."
    echo "  CLOUDINARY_API_SECRET=..."
    exit 1
fi

echo "=== [5/8] ログディレクトリの作成 ==="
sudo mkdir -p /var/log/recipe-app
sudo chown ubuntu:ubuntu /var/log/recipe-app

echo "=== [6/8] systemdサービスの設定 ==="
sudo cp "$APP_DIR/deploy/recipe-app.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable recipe-app
sudo systemctl restart recipe-app

echo "=== [7/8] Nginx設定 ==="
sudo cp "$APP_DIR/deploy/nginx-recipe-app.conf" /etc/nginx/sites-available/recipe-app
sudo ln -sf /etc/nginx/sites-available/recipe-app /etc/nginx/sites-enabled/recipe-app
# デフォルト設定を無効化（競合防止）
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "=== [8/8] 起動状態確認 ==="
sleep 2
sudo systemctl status recipe-app --no-pager
echo ""
echo "✅ デプロイ完了！"
echo "   アクセス: http://210.131.216.191"
