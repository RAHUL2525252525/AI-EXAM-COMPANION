from flask import Flask, render_template, request, jsonify, abort, redirect, session
import json
import os
import random
from groq import Groq
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= FIREBASE ADMIN =================
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret")

# 🔥 SESSION FIX (IMPORTANT)
app.config['SESSION_COOKIE_SAMESITE'] = "Lax"
app.config['SESSION_COOKIE_SECURE'] = False

# ================= GROQ CONFIG (LOAD FROM CUSTOM FILE) =================

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
    print(f"Error loading your api_keys file: {file_err}")

if not api_keys:
    env_keys = [
        os.environ.get("GROQ_API_KEY_1"),
        os.environ.get("GROQ_API_KEY_2"),
        os.environ.get("GROQ_API_KEY_3")
    ]
    api_keys = [k.strip() for k in env_keys if k and k.strip()]


# 🔥 LIGHTNING FAST PARALLEL AI CALLS
def try_single_key(key, user_message):
    """Worker function to make a single fast API call."""
    try:
        client = Groq(api_key=key, timeout=4.0)
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are an intelligent exam mentor. Answer clearly and shortly."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.5,
            max_tokens=150
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return e


# ✅ FIXED: Returns immediately on first successful result,
#    cancels remaining futures so a late-arriving error can't overwrite success.
def get_ai_response(user_message):
    if not api_keys:
        return "AI configuration error: Your 'api_keys' file could not be read or contains no keys."

    last_error = "All API keys failed to return a response."

    with ThreadPoolExecutor(max_workers=len(api_keys)) as executor:
        futures = {executor.submit(try_single_key, key, user_message): key for key in api_keys}

        for future in as_completed(futures):
            result = future.result()
            # If the result is not an Exception, we got a valid reply — return immediately
            if not isinstance(result, Exception):
                # Cancel all remaining pending futures
                for f in futures:
                    f.cancel()
                return result
            else:
                last_error = str(result)

    return f"AI failed on all API keys. Last encountered error: {last_error}"


# ================= FIREBASE INIT =================
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_key.json")
    firebase_admin.initialize_app(cred)

# --------------------------------------------------
BASE_DIR = os.getcwd()
QUESTION_BANK_DIR = os.path.join(BASE_DIR, "question_bank")
RESULTS_FILE = os.path.join(BASE_DIR, "results.json")
USERS_FILE = os.path.join(BASE_DIR, "users.json")

# --------------------------------------------------
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

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
# FIREBASE LOGIN ROUTE
# --------------------------------------------------
@app.route("/firebase-login", methods=["POST"])
def firebase_login():
    try:
        data = request.get_json()

        if not data or "token" not in data or not data["token"]:
            return jsonify({"status": "error", "message": "No token received"}), 400

        token = data["token"]

        decoded_token = firebase_auth.verify_id_token(token, clock_skew_seconds=60)

        email = decoded_token.get("email")

        if not email:
            return jsonify({"status": "error", "message": "No email in token"}), 401

        session["user"] = email
        session.permanent = True

        return jsonify({"status": "success", "user": email})

    except Exception as e:
        print("FIREBASE ERROR:", e)
        return jsonify({"status": "error", "message": str(e)}), 401

# --------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not username or not password:
            return render_template("login.html", error="PLEASE FILL ALL FIELDS")

        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)

        user = next((u for u in users if u["username"] == username and u["password"] == password), None)

        if user:
            session["user"] = username
            return redirect("/")

        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")

# --------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if not username or not password or not confirm_password:
            return render_template("register.html", error="Please fill all fields")

        if password != confirm_password:
            return render_template("register.html", error="Passwords do not match")

        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)

        if any(u["username"] == username for u in users):
            return render_template("register.html", error="Username already exists")

        users.append({"username": username, "password": password})

        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

        return redirect("/login")

    return render_template("register.html")

# --------------------------------------------------
@app.route("/")
def home():
    if "user" not in session:
        return redirect("/login")
    return render_template("index.html")


# --------------------------------------------------
@app.route("/mocktest")
def mocktest():
    if "user" not in session:
        return redirect("/login")

    stages = [
        i for i in range(1, 11)
        if os.path.exists(os.path.join(QUESTION_BANK_DIR, f"stage{i}.json"))
    ]
    return render_template("mocktest.html", stages=stages)

# --------------------------------------------------
@app.route("/mocktest/stage/<int:stage>")
def mocktest_stage(stage):
    if "user" not in session:
        return redirect("/login")

    json_file = os.path.join(QUESTION_BANK_DIR, f"stage{stage}.json")

    if not os.path.exists(json_file):
        abort(404)

    with open(json_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    for q in questions:
        if "options" in q:
            random.shuffle(q["options"])

    return render_template("mocktest_stage.html", stage=stage, questions=json.dumps(questions))

# --------------------------------------------------
@app.route("/mocktest/<int:stage>/result")
def mocktest_result(stage):
    score = int(request.args.get("score", 0))

    json_file = os.path.join(QUESTION_BANK_DIR, f"stage{stage}.json")

    if not os.path.exists(json_file):
        abort(404)

    with open(json_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    total_questions = len(questions)
    correct = score
    wrong = total_questions - correct
    accuracy = round((correct / total_questions) * 100, 2) if total_questions > 0 else 0

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)

    results["total_attempts"] += 1
    results["overall_performance"]["total_questions"] += total_questions
    results["overall_performance"]["total_correct"] += correct
    results["overall_performance"]["total_wrong"] += wrong

    total_q = results["overall_performance"]["total_questions"]
    total_c = results["overall_performance"]["total_correct"]

    if total_q > 0:
        results["overall_performance"]["overall_accuracy"] = round((total_c / total_q) * 100, 2)

    results["attempt_history"].append({
        "stage": stage,
        "score": score,
        "accuracy": accuracy
    })

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return render_template("mocktest_result.html", stage=stage, score=score)

# --------------------------------------------------
@app.route("/performance")
def performance_page():
    if "user" not in session:
        return redirect("/login")

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return render_template("performance.html", data=data)

# --------------------------------------------------
@app.route("/mentor")
def mentor():
    if "user" not in session:
        return redirect("/login")
    return render_template("mentor.html")

# --------------------------------------------------
@app.route("/ask_ai", methods=["POST"])
def ask_ai():
    if "user" not in session:
        return jsonify({"reply": "Please login first."})

    user_message = request.json.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please ask a valid question."})

    try:
        reply = get_ai_response(user_message)
        return jsonify({"reply": reply})

    except Exception:
        return jsonify({"reply": "AI error. Please check API key or internet connection."})

# --------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
