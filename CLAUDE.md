# Project: recipe-app（レシピ管理アプリ）

## 目的
個人用のレシピを登録・管理し、画像付きで一覧・詳細表示できるWebアプリ。料理記録カレンダー機能あり。

## Tech Stack / 実装の前提
- Web: Flask 2.2.5（`app.py` がルーティングと主要ロジック）
- DB: PostgreSQL（Neon.tech）、接続は `DATABASE_URL` 環境変数
- 画像: Cloudinary（アップロード・URL保存）、ローカルには保存しない
- 起動:
  - ローカル: `python app.py`
  - 本番（Procfile）: `gunicorn app:app`
- DB接続: `psycopg2.pool.ThreadedConnectionPool`（コネクションプール、1〜5接続）
- テーブル作成: 起動時に `init_db()` で自動作成

## 参照ファイル（まず見る場所）
- `app.py`: ルート・DBアクセス・Cloudinary連携・カレンダーロジック
- `templates/`: Jinja2テンプレート（一覧・詳細・登録・カレンダー画面）
- `static/`: CSS・JS
- `.env`: `DATABASE_URL`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`
- `Procfile`: 本番起動コマンド

## DBスキーマ（主要カラム）
```sql
recipes (
    id, title, url, ingredients, steps,
    image_url, memo, created_at, category, tags
)
```
- `image_url`: CloudinaryのURL（ローカルパスは使わない）
- `tags`: テキスト形式で保存

## 開発時の前提（安全な作業）
- 変更は最小限にする（既存機能の互換性を優先）
- DBスキーマを変更する場合は既存データを壊さない方針で
- Cloudinaryへのアップロード処理（`save_upload()`）は慎重に扱う
- 副作用の強い操作は実行前に必ず確認を取る

## 環境変数（必須）
- `DATABASE_URL`: Neon.tech接続文字列
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

## 本番環境
- URL: https://recipe-app.zono-design.com
- サーバー: Xserver VPS（IP: 210.131.216.191）
- ユーザー: ubuntu
- SSHキー: `~/.ssh/xserver-vps2.pem`
- アプリディレクトリ: `/home/ubuntu/recipe-app`
- 構成: Gunicorn（ポート8000） + Nginx（ポート80/443） + systemd
- GitHubリポジトリ: https://github.com/mamizonoria/recipe-app（公開）

### デプロイ設定ファイル
- `deploy/recipe-app.service`: systemdサービス定義
- `deploy/nginx-recipe-app.conf`: Nginx設定

### コード更新手順
```bash
# ローカルで変更をプッシュ
git push

# VPSで反映
ssh -i ~/.ssh/xserver-vps2.pem ubuntu@210.131.216.191
cd ~/recipe-app && git pull && sudo systemctl restart recipe-app
```

## コマンド
```bash
# ローカル起動
python app.py

# 依存関係インストール
pip install -r requirements.txt
```

## Do NOT
- `.env` を読み取ったり内容を出力しない
- `rm -rf` 系コマンドを実行しない
- 既存のDBテーブル定義を無断で変更しない
- `git push --force` は実行しない
- Cloudinaryに不要なファイルをアップロードしない
