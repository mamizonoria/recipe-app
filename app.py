from flask import Flask, render_template, request, redirect
import re
import json
import os
import requests
from bs4 import BeautifulSoup
import psycopg2
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

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
    result = cloudinary.uploader.upload(file)
    return result.get("secure_url")

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

@app.route("/add", methods=["POST"])
def add():
    url      = request.form.get("url", "").strip()
    memo     = request.form.get("memo", "").strip()
    category = request.form.get("category", "").strip()
    tags     = ", ".join([t.strip() for t in request.form.get("tags", "").split(",") if t.strip()])
    if url:
        info = fetch_recipe(url)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO recipes (title, url, ingredients, steps, image_url, memo, category, tags) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (info["title"], url, info["ingredients"], info["steps"], info["image_url"], memo, category, tags)
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

if __name__ == "__main__":
    init_db()
    migrate_steps()
    app.run(host="0.0.0.0", port=8080)
