import os
import sqlite3
from flask import Flask, redirect, render_template, request, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date as dt_date

app = Flask(__name__)

IS_PRODUCTION = os.environ.get("APP_ENV") == "production"

# 本番では SECRET_KEY が無いと起動しない（初期値のまま公開する事故を防ぐ）
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError("SECRET_KEY が設定されていません")
    SECRET_KEY = "dev-secret-key-for-local-only"
app.secret_key = SECRET_KEY

# セッションCookieの設定（本番はHTTPS限定）
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# DBはこのファイルと同じ場所の絶対パスにする（サーバー上で作業場所が変わっても迷子にならない）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "mood_journal.db")


# データベースの初期化（テーブルがなければ作成）
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. ユーザー管理テーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # 2. 日記データテーブル（user_idを追加）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            condition INTEGER NOT NULL,
            memo TEXT,
            sleep_hours REAL DEFAULT 0.0,
            rating INTEGER DEFAULT 3,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
        # 3. 薬テーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            dose TEXT,
            status TEXT NOT NULL DEFAULT '服用中',
            note TEXT,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    conn.commit()
    conn.close()


# アプリ起動時にデータベースを初期化
init_db()


# トップページ（入力フォームと過去の記録一覧を表示）
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    username = session.get("username", "ゲスト")
    month = request.args.get("month", "").strip()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if month:
        cursor.execute(
            "SELECT id, date, condition, memo, sleep_hours, rating FROM logs "
            "WHERE user_id = ? AND strftime('%Y-%m', date) = ? ORDER BY date DESC",
            (user_id, month),
        )
    else:
        cursor.execute(
            "SELECT id, date, condition, memo, sleep_hours, rating FROM logs "
            "WHERE user_id = ? ORDER BY date DESC",
            (user_id,),
        )
    logs = cursor.fetchall()

    # 現在のお薬（中止以外）
    cursor.execute(
        """
        SELECT name, dose, status FROM medications
        WHERE user_id = ? AND status != '中止'
        ORDER BY CASE status WHEN '服用中' THEN 0 ELSE 1 END, name
        """,
        (user_id,),
    )
    current_meds = cursor.fetchall()
    conn.close()

    return render_template(
        "journal.html",
        username=username,
        logs=logs,
        month=month,
        current_meds=current_meds,
    )

# データの保存処理
@app.route("/save", methods=["POST"])
def save():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    date = request.form.get("date")
    condition = request.form.get("condition")
    memo = request.form.get("memo")
    
    # 型のズレが出ないように明示的に float に変換
    raw_sleep_hours = request.form.get("sleep_hours", "0")
    try:
        sleep_hours = float(raw_sleep_hours)
    except (ValueError, TypeError):
        sleep_hours = 0.0

    rating = request.form.get("rating", 3)
    try:
        rating = int(rating)
    except (ValueError,TypeError):
        rating = 3

    if date and condition:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO logs (user_id, date, condition, memo, sleep_hours, rating) VALUES (?, ?, ?, ?, ?,?)",
            (user_id, date, condition, memo, sleep_hours, rating),
        )
        conn.commit()
        conn.close()
        flash("記録を保存しました！", "success")

    return redirect(url_for("index"))


# 削除処理
@app.route("/delete/<int:log_id>", methods=["POST"])
def delete(log_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM logs WHERE id = ? AND user_id = ?", (log_id, session["user_id"]))
    conn.commit()
    conn.close()
    
    flash("記録を削除しました。", "info")
    return redirect(url_for("index"))


# 1. 編集画面を表示するルート (GET)
@app.route("/edit/<int:log_id>", methods=["GET"])
def edit(log_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, date, condition, memo, sleep_hours, rating FROM logs WHERE id = ? AND user_id = ?", (log_id, session["user_id"]))
    log = cursor.fetchone()
    conn.close()

    if not log:
        flash("指定された記録が見つかりませんでした。", "error")
        return redirect(url_for("index"))
    
    return render_template("edit.html", log=log)


# 2. データを更新するルート (POST)
@app.route("/update/<int:log_id>", methods=["POST"])
def update(log_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    date = request.form.get("date")
    condition = request.form.get("condition")
    memo = request.form.get("memo")
    
    # save と同様に明示的に float へ変換（型警告防止）
    raw_sleep_hours = request.form.get("sleep_hours", "0")
    try:
        sleep_hours = float(raw_sleep_hours)
    except (ValueError, TypeError):
        sleep_hours = 0.0

    rating = request.form.get("rating", 3)
    try:
        rating = int(rating)
    except (ValueError,TypeError):
        rating = 3

    if not date or not condition:
        flash("日付と体調と満足度を正しく入力してください。", "error")
        return redirect(url_for("edit", log_id=log_id))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE logs 
        SET date = ?, condition = ?, memo = ?, sleep_hours = ?, rating = ?
        WHERE id = ? AND user_id = ?
    """, (date, condition, memo, sleep_hours, rating, log_id, session["user_id"]))
    
    conn.commit()
    conn.close()

    flash("記録を更新しました！", "success")
    return redirect(url_for("index"))


# ログインルート
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, password FROM users WHERE username = ?", (username,)
        )
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session["user_id"] = user[0]
            session["username"] = username
            flash(f"おかえりなさい、{username}さん！", "success")
            return redirect(url_for("index"))
        else:
            flash("ユーザー名またはパスワードが正しくありません", "error")
            return render_template("login.html")

    return render_template("login.html")


# 新規登録ルート
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("ユーザー名とパスワードを入力してください。", "error")
            return redirect(url_for("signup"))

        if len(password) < 8:
            flash("パスワードは8文字以上にしてください。", "error")
            return redirect(url_for("signup"))

        hashed_password = generate_password_hash(password)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hashed_password)
            )
            conn.commit()
            conn.close()

            flash("アカウントの登録が完了しました！ログインしてください。", "success")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            conn.close()
            flash("そのユーザー名はすでに使われています。", "error")
            return redirect(url_for("signup"))

    return render_template("sign.html")

# ログアウトルート
@app.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました。", "info")
    return redirect(url_for("login"))

MED_STATUSES = ("服用中", "減薬中", "中止")


@app.route("/meds")
def meds():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, dose, status, note, updated_at FROM medications
        WHERE user_id = ?
        ORDER BY CASE status WHEN '服用中' THEN 0 WHEN '減薬中' THEN 1 ELSE 2 END, name
        """,
        (session["user_id"],),
    )
    meds = cursor.fetchall()
    conn.close()
    return render_template("meds.html", meds=meds, statuses=MED_STATUSES)


@app.route("/meds/add", methods=["POST"])
def meds_add():
    if "user_id" not in session:
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    dose = request.form.get("dose", "").strip()
    status = request.form.get("status", "服用中")
    note = request.form.get("note", "").strip()

    if not name or status not in MED_STATUSES:
        flash("薬の名前を入力してください。", "error")
        return redirect(url_for("meds"))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO medications (user_id, name, dose, status, note, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session["user_id"], name, dose, status, note, dt_date.today().isoformat()),
    )
    conn.commit()
    conn.close()
    flash("薬を登録しました。", "success")
    return redirect(url_for("meds"))


@app.route("/meds/update/<int:med_id>", methods=["POST"])
def meds_update(med_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    dose = request.form.get("dose", "").strip()
    status = request.form.get("status", "服用中")
    note = request.form.get("note", "").strip()

    if status not in MED_STATUSES:
        flash("状態が正しくありません。", "error")
        return redirect(url_for("meds"))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE medications SET dose = ?, status = ?, note = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (dose, status, note, dt_date.today().isoformat(), med_id, session["user_id"]),
    )
    conn.commit()
    conn.close()
    flash("薬の情報を更新しました。", "success")
    return redirect(url_for("meds"))


@app.route("/meds/delete/<int:med_id>", methods=["POST"])
def meds_delete(med_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM medications WHERE id = ? AND user_id = ?",
        (med_id, session["user_id"]),
    )
    conn.commit()
    conn.close()
    flash("薬を削除しました。", "info")
    return redirect(url_for("meds"))

if __name__ == "__main__":
    # 手元で「FLASK_DEBUG=1」を付けたときだけデバッグモード
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
#FLASK_DEBUG=1 python app.py
#python -c "import secrets; print(secrets.token_hex(32))"