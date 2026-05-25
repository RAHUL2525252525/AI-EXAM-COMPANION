from flask import Flask, render_template, request, jsonify, abort, redirect, session
import json
import os
import random
from groq import Groq
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= FIREBASE ADMIN =================
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

# ================= BCRYPT =================
import bcrypt

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret")

# 🔥 SESSION FIX
app.config['SESSION_COOKIE_SAMESITE'] = "Lax"
# FIX: Set True in production (HTTPS). Set False only for local dev via env var.
app.config['SESSION_COOKIE_SECURE'] = os.environ.get("DEV_MODE", "false").lower() != "true"

# ================= GROQ CONFIG =================

api_keys = []

try:
    target_file = "api_keys"

    if not os.path.exists(target_file) and os.path.exists("api_keys.txt"):
        target_file = "api_keys.txt"

    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8") as file:
            for line in file:
                cleaned_line = line.strip()

                if cleaned_line:
                    if "=" in cleaned_line:
                        cleaned_line = cleaned_line.split("=", 1)[1].strip()

                    cleaned_line = cleaned_line.strip("'\"")
                    api_keys.append(cleaned_line)

except Exception as file_err:
    print(f"Error loading api_keys file: {file_err}")

# Fallback ENV keys
if not api_keys:
    env_keys = [
        os.environ.get("GROQ_API_KEY_1"),
        os.environ.get("GROQ_API_KEY_2"),
        os.environ.get("GROQ_API_KEY_3")
    ]

    api_keys = [k.strip() for k in env_keys if k and k.strip()]

# --------------------------------------------------
# AI RESPONSE SYSTEM
# --------------------------------------------------

def try_single_key(key, user_message):
    try:
        client = Groq(
            api_key=key,
            timeout=4.0
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": "You are an intelligent exam mentor. Answer clearly and shortly."
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            temperature=0.5,
            max_tokens=150
        )

        return completion.choices[0].message.content.strip()

    except Exception as e:
        return e


def get_ai_response(user_message):

    if not api_keys:
        return "AI configuration error: No API keys found."

    last_error = "All API keys failed."

    with ThreadPoolExecutor(max_workers=len(api_keys)) as executor:

        futures = {
            executor.submit(try_single_key, key, user_message): key
            for key in api_keys
        }

        for future in as_completed(futures):

            result = future.result()

            if not isinstance(result, Exception):
                return result
            else:
                last_error = str(result)

    return f"AI failed on all API keys. Last error: {last_error}"


# --------------------------------------------------
# FIREBASE INIT
# FIX: Load firebase key from env var (JSON string) first,
#      fall back to firebase_key.json for local dev.
# --------------------------------------------------

if not firebase_admin._apps:

    firebase_key_env = os.environ.get("FIREBASE_KEY_JSON")

    if firebase_key_env:
        # Production: key loaded from environment variable
        try:
            key_dict = json.loads(firebase_key_env)
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
            print("Firebase initialized from environment variable.")
        except Exception as e:
            print(f"Firebase env init error: {e}")

    elif os.path.exists("firebase_key.json"):
        # Local dev fallback: key loaded from file
        try:
            cred = credentials.Certificate("firebase_key.json")
            firebase_admin.initialize_app(cred)
            print("Firebase initialized from firebase_key.json (local dev).")
        except Exception as e:
            print(f"Firebase file init error: {e}")

    else:
        print("Firebase: No key found. Set FIREBASE_KEY_JSON env var.")

# --------------------------------------------------
BASE_DIR = os.getcwd()

QUESTION_BANK_DIR = os.path.join(BASE_DIR, "question_bank")

RESULTS_FILE = os.path.join(BASE_DIR, "results.json")

USERS_FILE = os.path.join(BASE_DIR, "users.json")

# --------------------------------------------------
# USERS FILE
# --------------------------------------------------

if not os.path.exists(USERS_FILE):

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

# --------------------------------------------------
# RESULTS FILE
# --------------------------------------------------

if not os.path.exists(RESULTS_FILE):

    initial_structure = {
        "student_name": "Rahul S",
        "total_attempts": 0,
        "overall_performance": {
            "total_questions": 0,
            "total_correct": 0,
            "total_wrong": 0,
            "overall_accuracy": 0
        },
        "attempt_history": [],
        "stage_summary": {
            f"stage{i}": {
                "attempts": 0,
                "best_score": 0,
                "average_accuracy": 0,
                "weak_topics": [],
                "strong_topics": []
            } for i in range(1, 11)
        }
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(initial_structure, f, indent=2)

# --------------------------------------------------
# PASSWORD HELPERS
# FIX: Passwords are now hashed with bcrypt.
#      is_plain_password() handles existing plain-text
#      passwords already stored, migrating them on next login.
# --------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, stored: str) -> bool:
    # Handles both bcrypt hashes and legacy plain-text passwords
    # so existing users aren't locked out
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
    except Exception:
        # Legacy plain-text fallback
        return plain == stored


def migrate_password_if_needed(users: list, username: str, plain: str) -> list:
    """If user still has a plain-text password, hash it and save."""
    for u in users:
        if u["username"] == username:
            stored = u["password"]
            is_bcrypt = stored.startswith("$2b$") or stored.startswith("$2a$")
            if not is_bcrypt:
                u["password"] = hash_password(plain)
            break
    return users

# --------------------------------------------------
# FIREBASE LOGIN
# --------------------------------------------------

@app.route("/firebase-login", methods=["POST"])
def firebase_login():

    try:
        data = request.get_json()

        if not data or "token" not in data:
            return jsonify({
                "status": "error",
                "message": "No token received"
            }), 400

        token = data["token"]

        decoded_token = firebase_auth.verify_id_token(token)

        email = decoded_token.get("email")

        if not email:
            return jsonify({
                "status": "error",
                "message": "No email in token"
            }), 401

        session["user"] = email
        session.permanent = True

        return jsonify({
            "status": "success",
            "user": email
        })

    except Exception as e:

        print("FIREBASE ERROR:", e)

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 401

# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = (
            request.form.get("username")
            or request.form.get("email")
            or ""
        ).strip()

        password = (
            request.form.get("password")
            or ""
        ).strip()

        if not username or not password:

            return render_template(
                "login.html",
                error="PLEASE FILL ALL FIELDS"
            )

        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)

        user = next(
            (u for u in users if u["username"] == username),
            None
        )

        # FIX: Use bcrypt verify instead of plain == plain
        if user and verify_password(password, user["password"]):

            # FIX: Silently migrate legacy plain-text passwords on login
            users = migrate_password_if_needed(users, username, password)
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=2)

            session["user"] = username
            return redirect("/")

        return render_template(
            "login.html",
            error="Invalid username or password"
        )

    return render_template("login.html")

# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.pop("user", None)

    return redirect("/login")

# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = (
            request.form.get("username")
            or request.form.get("email")
            or ""
        ).strip()

        password = (
            request.form.get("password")
            or ""
        ).strip()

        confirm_password = (
            request.form.get("confirm_password")
            or ""
        ).strip()

        if not username or not password or not confirm_password:

            return render_template(
                "register.html",
                error="Please fill all fields"
            )

        if password != confirm_password:

            return render_template(
                "register.html",
                error="Passwords do not match"
            )

        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)

        if any(u["username"] == username for u in users):

            return render_template(
                "register.html",
                error="Username already exists"
            )

        # FIX: Store hashed password instead of plain text
        users.append({
            "username": username,
            "password": hash_password(password)
        })

        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

        return redirect("/login")

    return render_template("register.html")

# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def home():

    if "user" not in session:
        return redirect("/login")

    return render_template("index.html")

# --------------------------------------------------
# MOCKTEST
# --------------------------------------------------

@app.route("/mocktest")
def mocktest():

    if "user" not in session:
        return redirect("/login")

    stages = [
        i for i in range(1, 11)
        if os.path.exists(
            os.path.join(
                QUESTION_BANK_DIR,
                f"stage{i}.json"
            )
        )
    ]

    return render_template(
        "mocktest.html",
        stages=stages
    )

# --------------------------------------------------
# MOCKTEST STAGE
# --------------------------------------------------

@app.route("/mocktest/stage/<int:stage>")
def mocktest_stage(stage):

    if "user" not in session:
        return redirect("/login")

    json_file = os.path.join(
        QUESTION_BANK_DIR,
        f"stage{stage}.json"
    )

    if not os.path.exists(json_file):
        abort(404)

    with open(json_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    for q in questions:

        if "options" in q:
            random.shuffle(q["options"])

    return render_template(
        "mocktest_stage.html",
        stage=stage,
        questions=json.dumps(questions)
    )

# --------------------------------------------------
# RESULT
# --------------------------------------------------

@app.route("/mocktest/<int:stage>/result")
def mocktest_result(stage):

    score = int(request.args.get("score", 0))

    json_file = os.path.join(
        QUESTION_BANK_DIR,
        f"stage{stage}.json"
    )

    if not os.path.exists(json_file):
        abort(404)

    with open(json_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    total_questions = len(questions)

    correct = score

    wrong = total_questions - correct

    accuracy = round(
        (correct / total_questions) * 100,
        2
    ) if total_questions > 0 else 0

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)

    results["total_attempts"] += 1

    results["overall_performance"]["total_questions"] += total_questions

    results["overall_performance"]["total_correct"] += correct

    results["overall_performance"]["total_wrong"] += wrong

    total_q = results["overall_performance"]["total_questions"]

    total_c = results["overall_performance"]["total_correct"]

    if total_q > 0:

        results["overall_performance"]["overall_accuracy"] = round(
            (total_c / total_q) * 100,
            2
        )

    results["attempt_history"].append({
        "stage": stage,
        "score": score,
        "accuracy": accuracy
    })

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return render_template(
        "mocktest_result.html",
        stage=stage,
        score=score
    )

# --------------------------------------------------
# PERFORMANCE
# --------------------------------------------------

@app.route("/performance")
def performance_page():

    if "user" not in session:
        return redirect("/login")

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return render_template(
        "performance.html",
        data=data
    )

# --------------------------------------------------
# MENTOR
# --------------------------------------------------

@app.route("/mentor")
def mentor():

    if "user" not in session:
        return redirect("/login")

    return render_template("mentor.html")

# --------------------------------------------------
# ASK AI
# --------------------------------------------------

@app.route("/ask_ai", methods=["POST"])
def ask_ai():

    if "user" not in session:
        return jsonify({
            "reply": "Please login first."
        })

    user_message = request.json.get("message", "").strip()

    if not user_message:

        return jsonify({
            "reply": "Please ask a valid question."
        })

    try:

        reply = get_ai_response(user_message)

        return jsonify({
            "reply": reply
        })

    except Exception:

        return jsonify({
            "reply": "AI error. Please check API key or internet connection."
        })

# --------------------------------------------------
# MAIN
# FIX: debug=False in production. Use DEV_MODE=true env var locally.
# --------------------------------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    is_dev = os.environ.get("DEV_MODE", "false").lower() == "true"

    app.run(
        host="0.0.0.0",
        port=port,
        debug=is_dev
    )
