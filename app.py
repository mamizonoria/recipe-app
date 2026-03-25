from flask import Flask, render_template, request, redirect, jsonify
import re
import json
import os
import requests
from bs4 import BeautifulSoup
import psycopg2
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
import calendar as cal_module
from datetime import date

load_dotenv()

app = Flask(__name__)
app.jinja_env.filters["enumerate"] = enumerate

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

COLS = "id, title, url, ingredients, steps, image_url, memo, created_at, category, tags"

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def save_upload(file):
    if not file or file.filename == "":
        return None
    if not allowed_file(file.filename):
        return None
    try:
        result = cloudinary.uploader.upload(file)
        url = result.get("secure_url")
        app.logger.info(f"Cloudinary upload success: {url}")
        return url
    except Exception as e:
        app.logger.error(f"Cloudinary upload error: {e}")
        return None

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cooking_records (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
            custom_name TEXT DEFAULT '',
            meal_type TEXT DEFAULT '夕食',
            memo TEXT DEFAULT ''
        )
    """)
    # 既存テーブルへのカラム追加（マイグレーション）
    for col, defn in [("custom_name", "TEXT DEFAULT ''"), ("meal_type", "TEXT DEFAULT '夕食'")]:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='cooking_records' AND column_name=%s",
            (col,)
        )
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE cooking_records ADD COLUMN {col} {defn}")
    cur.execute("ALTER TABLE cooking_records ALTER COLUMN recipe_id DROP NOT NULL")
    for name in ["主食", "副食"]:
        cur.execute(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,)
        )
    conn.commit()
    cur.close()
    conn.close()

def migrate_steps():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, steps FROM recipes WHERE steps IS NOT NULL AND steps != ''")
    rows = cur.fetchall()
    for row in rows:
        new_steps = "\n".join(split_steps(row[1]))
        if new_steps != row[1]:
            cur.execute("UPDATE recipes SET steps = %s WHERE id = %s", (new_steps, row[0]))
    conn.commit()
    cur.close()
    conn.close()

def split_steps(text):
    if not text:
        return []
    pattern = re.compile(
        r'(?=[１-９][　\s])'
        r'|(?=（\d+[)）])'
        r'|(?=\(\d+\))'
        r'|(?=\d+\.\s)'
        r'|(?=STEP\s*\d)',
        re.UNICODE
    )
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in pattern.split(line) if p.strip()]
        result.extend(parts if parts else [line])
    return result if result else [text.strip()]

def get_categories():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM categories ORDER BY id")
    cats = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return cats

def parse_manual_recipe(text):
    if not text:
        return "", ""
    ingredient_header = re.compile(
        r'[【《＜<〔\[]?(?:材料|食材|ingredients)[】》＞>\]〕]?', re.IGNORECASE
    )
    step_header = re.compile(
        r'[【《＜<〔\[]?(?:作り方|つくり方|手順|調理方法|作法|how\s*to)[】》＞>\]〕]?', re.IGNORECASE
    )
    step_line = re.compile(
        r'^(?:[①-⑳➀-➉]|\d+[.)）、]|[１-９][.)）、]|STEP\s*\d)\s*\S'
    )
    ingredients, steps = [], []
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ingredient_header.fullmatch(line) or (ingredient_header.match(line) and len(line) < 12):
            section = 'ingredients'
            continue
        if step_header.fullmatch(line) or (step_header.match(line) and len(line) < 12):
            section = 'steps'
            continue
        if step_line.match(line) and section != 'ingredients':
            section = 'steps'
            steps.append(line)
            continue
        if section == 'ingredients':
            ingredients.append(line)
        elif section == 'steps':
            steps.append(line)
    return '\n'.join(ingredients), '\n'.join(steps)

def fetch_recipe(url):
    result = {"title": "タイトル不明", "ingredients": "", "steps": "", "image_url": ""}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        res = requests.get(url, timeout=8, headers=headers)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = next((d for d in data if d.get("@type") == "Recipe"), {})
                if data.get("@type") == "Recipe":
                    result["title"] = data.get("name", result["title"])
                    result["ingredients"] = "\n".join(data.get("recipeIngredient", []))
                    steps = []
                    for s in data.get("recipeInstructions", []):
                        if isinstance(s, dict):
                            steps.extend(split_steps(s.get("text", "")))
                        elif isinstance(s, str):
                            steps.extend(split_steps(s))
                    result["steps"] = "\n".join(steps)
                    image = data.get("image", "")
                    if isinstance(image, list): image = image[0]
                    if isinstance(image, dict): image = image.get("url", "")
                    result["image_url"] = image
                    return result
            except Exception:
                continue
        title_tag = soup.find("title")
        if title_tag:
            result["title"] = title_tag.text.strip()
        og_image = soup.find("meta", property="og:image")
        if og_image:
            result["image_url"] = og_image.get("content", "")
    except Exception:
        result["title"] = "取得失敗"
    return result

@app.route("/")
def index():
    keyword  = request.args.get("q", "")
    category = request.args.get("cat", "")
    tag      = request.args.get("tag", "")
    conn = get_conn()
    cur = conn.cursor()
    conditions, params = [], []
    if keyword:
        conditions.append("(title ILIKE %s OR ingredients ILIKE %s OR tags ILIKE %s)")
        params += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
    if category:
        conditions.append("category = %s")
        params.append(category)
    if tag:
        conditions.append("tags ILIKE %s")
        params.append(f"%{tag}%")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    cur.execute(f"SELECT {COLS} FROM recipes {where} ORDER BY created_at DESC", params)
    recipes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("index.html", recipes=recipes, keyword=keyword,
                           category=category, tag=tag, categories=get_categories())

@app.route("/recipe/<int:recipe_id>")
def recipe_detail(recipe_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {COLS} FROM recipes WHERE id = %s", (recipe_id,))
    recipe = cur.fetchone()
    cur.close()
    conn.close()
    if not recipe:
        return "レシピが見つかりません", 404
    return render_template("recipe.html", recipe=recipe, categories=get_categories())

@app.route("/fetch-preview")
def fetch_preview():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URLが必要です"}), 400
    info = fetch_recipe(url)
    return jsonify({"title": info["title"]})

@app.route("/add", methods=["POST"])
def add():
    url            = request.form.get("url", "").strip()
    title_override = request.form.get("title_override", "").strip()
    memo           = request.form.get("memo", "").strip()
    category       = request.form.get("category", "").strip()
    tags           = ", ".join([t.strip() for t in request.form.get("tags", "").split(",") if t.strip()])
    if url:
        info  = fetch_recipe(url)
        title = title_override if title_override else info["title"]
        conn  = get_conn()
        cur   = conn.cursor()
        cur.execute(
            "INSERT INTO recipes (title, url, ingredients, steps, image_url, memo, category, tags) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (title, url, info["ingredients"], info["steps"], info["image_url"], memo, category, tags)
        )
        conn.commit()
        cur.close()
        conn.close()
    return redirect("/")

@app.route("/add-manual", methods=["POST"])
def add_manual():
    title       = request.form.get("title", "").strip()
    url         = request.form.get("url", "").strip()
    full_text   = request.form.get("full_text", "").strip()
    ingredients = request.form.get("ingredients", "").strip()
    steps       = request.form.get("steps", "").strip()
    category    = request.form.get("category", "").strip()
    tags        = ", ".join([t.strip() for t in request.form.get("tags", "").split(",") if t.strip()])
    memo        = request.form.get("memo", "").strip()
    image_url   = save_upload(request.files.get("photo")) or ""
    if full_text and (not ingredients and not steps):
        ingredients, steps = parse_manual_recipe(full_text)
    if title:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO recipes (title, url, ingredients, steps, image_url, memo, category, tags) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (title, url, ingredients, steps, image_url, memo, category, tags)
        )
        conn.commit()
        cur.close()
        conn.close()
    return redirect("/")

@app.route("/recipe/<int:recipe_id>/update", methods=["POST"])
def update(recipe_id):
    category    = request.form.get("category", "").strip()
    tags        = ", ".join([t.strip() for t in request.form.get("tags", "").split(",") if t.strip()])
    memo        = request.form.get("memo", "").strip()
    ingredients = request.form.get("ingredients", "").strip()
    steps       = request.form.get("steps", "").strip()
    url         = request.form.get("url", "").strip()
    new_image   = save_upload(request.files.get("photo"))
    conn = get_conn()
    cur = conn.cursor()
    if new_image:
        cur.execute(
            "UPDATE recipes SET category=%s,tags=%s,memo=%s,ingredients=%s,steps=%s,url=%s,image_url=%s WHERE id=%s",
            (category, tags, memo, ingredients, steps, url, new_image, recipe_id)
        )
    else:
        cur.execute(
            "UPDATE recipes SET category=%s,tags=%s,memo=%s,ingredients=%s,steps=%s,url=%s WHERE id=%s",
            (category, tags, memo, ingredients, steps, url, recipe_id)
        )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(f"/recipe/{recipe_id}")

@app.route("/recipe/<int:recipe_id>/update-lines", methods=["POST"])
def update_lines(recipe_id):
    field = request.form.get("field")
    value = request.form.get("value", "")
    if field not in ("ingredients", "steps", "title"):
        return jsonify({"error": "invalid field"}), 400
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(f"UPDATE recipes SET {field} = %s WHERE id = %s", (value, recipe_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/fix-steps/<int:recipe_id>", methods=["POST"])
def fix_steps(recipe_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, steps FROM recipes WHERE id = %s", (recipe_id,))
    row = cur.fetchone()
    if row and row[1]:
        cur.execute("UPDATE recipes SET steps = %s WHERE id = %s",
                    ("\n".join(split_steps(row[1])), recipe_id))
        conn.commit()
    cur.close()
    conn.close()
    return redirect(f"/recipe/{recipe_id}")

@app.route("/categories/add", methods=["POST"])
def category_add():
    name = request.form.get("name", "").strip()
    if name:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
        conn.commit()
        cur.close()
        conn.close()
    return redirect("/")

@app.route("/categories/delete", methods=["POST"])
def category_delete():
    name = request.form.get("name", "").strip()
    if name:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM categories WHERE name = %s", (name,))
        conn.commit()
        cur.close()
        conn.close()
    return redirect("/")

@app.route("/bulk-update", methods=["POST"])
def bulk_update():
    ids      = request.form.getlist("ids")
    category = request.form.get("category", "").strip()
    if ids and category:
        conn = get_conn()
        cur = conn.cursor()
        cur.executemany(
            "UPDATE recipes SET category = %s WHERE id = %s",
            [(category, id_) for id_ in ids]
        )
        conn.commit()
        cur.close()
        conn.close()
    return redirect("/")

@app.route("/delete/<int:recipe_id>", methods=["POST"])
def delete(recipe_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM recipes WHERE id = %s", (recipe_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect("/")

@app.route("/calendar")
def calendar_view():
    from datetime import datetime as dt
    today         = date.today()
    year          = int(request.args.get("year",  today.year))
    month         = int(request.args.get("month", today.month))
    selected_date = request.args.get("date", "")

    conn = get_conn()
    cur  = conn.cursor()

    # その月の日付×食事タイプ（ドット表示用）
    cur.execute("""
        SELECT DISTINCT date, meal_type FROM cooking_records
        WHERE EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
    """, (year, month))
    dates_with_records = {}
    for row in cur.fetchall():
        dk = row[0].strftime("%Y-%m-%d")
        dates_with_records.setdefault(dk, set()).add(row[1])

    # 選択日の記録
    records_by_meal = {"朝食": [], "昼食": [], "夕食": []}
    if selected_date:
        cur.execute("""
            SELECT cr.id, cr.meal_type, cr.custom_name, cr.memo, r.id, r.title
            FROM cooking_records cr
            LEFT JOIN recipes r ON cr.recipe_id = r.id
            WHERE cr.date = %s
            ORDER BY CASE cr.meal_type WHEN '朝食' THEN 1 WHEN '昼食' THEN 2 ELSE 3 END, cr.id
        """, (selected_date,))
        for rec in cur.fetchall():
            meal = rec[1] if rec[1] in records_by_meal else "夕食"
            records_by_meal[meal].append(rec)

    cur.execute("SELECT id, title, category FROM recipes ORDER BY title")
    recipes = cur.fetchall()
    cur.close()
    conn.close()

    prev_year,  prev_month  = (year - 1, 12) if month == 1  else (year, month - 1)
    next_year,  next_month  = (year + 1,  1) if month == 12 else (year, month + 1)

    selected_date_label = ""
    if selected_date:
        d = dt.strptime(selected_date, "%Y-%m-%d")
        selected_date_label = f"{d.year}年{d.month}月{d.day}日"

    return render_template("calendar.html",
        year=year, month=month,
        cal=cal_module.monthcalendar(year, month),
        dates_with_records=dates_with_records,
        selected_date=selected_date,
        selected_date_label=selected_date_label,
        records_by_meal=records_by_meal,
        recipes=recipes,
        categories=get_categories(),
        today=today.strftime("%Y-%m-%d"),
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        month_name=f"{year}年{month}月"
    )

@app.route("/calendar/add", methods=["POST"])
def calendar_add():
    date_str    = request.form.get("date", "").strip()
    recipe_id   = request.form.get("recipe_id", "").strip() or None
    custom_name = request.form.get("custom_name", "").strip()
    meal_type   = request.form.get("meal_type", "夕食").strip()
    memo        = request.form.get("memo", "").strip()
    year        = request.form.get("year", "")
    month       = request.form.get("month", "")
    if date_str and (recipe_id or custom_name):
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO cooking_records (date, recipe_id, custom_name, meal_type, memo) VALUES (%s, %s, %s, %s, %s)",
            (date_str, recipe_id, custom_name, meal_type, memo)
        )
        conn.commit()
        cur.close()
        conn.close()
    return redirect(f"/calendar?year={year}&month={month}&date={date_str}#detail")

@app.route("/calendar/delete/<int:record_id>", methods=["POST"])
def calendar_delete(record_id):
    year      = request.form.get("year", "")
    month     = request.form.get("month", "")
    date_str  = request.form.get("date", "")
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM cooking_records WHERE id = %s", (record_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(f"/calendar?year={year}&month={month}&date={date_str}#detail")

# gunicornでもローカルでもDB初期化を実行
with app.app_context():
    init_db()

if __name__ == "__main__":
    migrate_steps()
    app.run(host="0.0.0.0", port=8080)
