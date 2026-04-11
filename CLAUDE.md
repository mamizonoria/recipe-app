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
- VPS操作（SSH・cron設定など）はユーザーに手順を伝えるのではなく、Claudeが直接SSHして実行する
  - SSHキー: `~/.ssh/xserver-vps2.pem`、ユーザー: `ubuntu`、IP: `210.131.216.191`

## 環境変数（必須）
- `DATABASE_URL`: Neon.tech接続文字列
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

## 本番環境
- URL: https://recipe-app.zono-design.com
- サーバー: Xserver VPS（IP: 210.131.216.191）
- ユーザー: ubuntu
- SSHキー: `~/.ssh/xserver-vps2.pem`（`xserver-vps2_fixed.pem` は存在しない）
- アプリディレクトリ: `/home/ubuntu/recipe-app`
- 構成: Gunicorn（ポート8000） + Nginx（ポート80/443） + systemd
- GitHubリポジトリ: https://github.com/mamizonoria/recipe-app（公開）

### デプロイ設定ファイル
- `deploy/recipe-app.service`: systemdサービス定義
- `deploy/nginx-recipe-app.conf`: Nginx設定

### コード更新手順
```bash
# git push するだけで数十秒以内にVPSへ自動デプロイされる（GitHub Actions設定済み）
git push
```

### デプロイの仕組み
- **GitHub Actions**（`.github/workflows/deploy.yml`）が main へのプッシュをトリガーに SSH でVPSに接続し即時デプロイ
  - `git pull` → `pip install` → `systemctl restart recipe-app` を実行
  - GitHub Secrets に `VPS_SSH_KEY`（`~/.ssh/xserver-vps2.pem` の中身）を設定済み
- **VPS cron**（バックアップ）: 1分ごとにgit pullを確認（GitHub Actionsが主、cronは保険）

### VPS の cron 設定（ubuntu ユーザー）
```
# 自動デプロイ（1分ごと・バックアップ）
* * * * * cd /home/ubuntu/recipe-app && git fetch -q && git diff --quiet HEAD origin/main || (git pull -q && ./venv/bin/pip install -r requirements.txt -q && sudo systemctl restart recipe-app >> /var/log/recipe-app/deploy.log 2>&1)

# DB キープアライブ（4分ごと）
*/4 * * * * curl -s https://recipe-app.zono-design.com/ > /dev/null
```

### Neon.tech の DB スリープについて
- 無料プランのため「Scale to zero（5分で自動スリープ）」が固定で有効
- 久々にサイトを開くと DB 起動待ちで表示が遅くなる
- 上記キープアライブ cron（4分ごと）で対処済み
- キープアライブを止めると再び遅くなるので削除しないこと

### urllib3 に関する注意（2026-04-11）
- `requirements.txt` に `urllib3<2` の制約を入れると urllib3 1.x がインストールされ、Python 3.12環境でCookpadなど一部サイトのスクレイピングが失敗する
- urllib3 は 2.x（制約なし）のままにすること
- VPS上のurllib3バージョンは `./venv/bin/pip show urllib3` で確認できる

### パフォーマンス改善済み（2026-04-11）
- トップページのDB接続を3回→1回に削減（categories・tags取得を統合）
- last_cooked の相関サブクエリを LEFT JOIN に変更
- DBインデックスを追加（created_at, category, recipe_id, date）→ `init_db()` で自動作成
- `/ping` エンドポイントを追加（ログイン不要・DBに `SELECT 1` するだけ）
  - キープアライブcronが `/` を叩いてもログインリダイレクトでDBに届かない問題を修正
  - VPS cronを `/ping` に変更済み

## 作業終了時のルール
作業が一段落したら、必ず以下を実行すること：
```bash
git add -A
git commit -m "作業内容のメモ"
git push
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
