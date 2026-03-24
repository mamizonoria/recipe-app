"""
SQLiteのデータをNeon(PostgreSQL)に移行するスクリプト
一度だけ実行してください
"""
import sqlite3
import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

print("Neonに接続中...")
pg = psycopg2.connect(DATABASE_URL)
pg_cur = pg.cursor()

# テーブル作成
pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS recipes (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        url TEXT DEFAULT '',
        ingredients TEXT DEFAULT '',
        steps TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        memo TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        category TEXT DEFAULT '',
        tags TEXT DEFAULT ''
    )
""")
pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE
    )
""")
pg.commit()

print("SQLiteからデータ読み込み中...")
sq = sqlite3.connect("recipes.db")
sq_cur = sq.cursor()

# カテゴリーを移行
sq_cur.execute("SELECT name FROM categories ORDER BY id")
cats = sq_cur.fetchall()
for (name,) in cats:
    pg_cur.execute(
        "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
        (name,)
    )
print(f"カテゴリー {len(cats)}件 移行完了")

# レシピを移行
sq_cur.execute("""
    SELECT title, url, ingredients, steps, image_url, memo, created_at, category, tags
    FROM recipes
""")
recipes = sq_cur.fetchall()
for r in recipes:
    pg_cur.execute("""
        INSERT INTO recipes (title, url, ingredients, steps, image_url, memo, created_at, category, tags)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        r[0] or '', r[1] or '', r[2] or '', r[3] or '',
        r[4] or '', r[5] or '', r[6], r[7] or '', r[8] or ''
    ))
print(f"レシピ {len(recipes)}件 移行完了")

pg.commit()
pg_cur.close()
pg.close()
sq.close()
print("✅ 移行完了！")
