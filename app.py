from flask import Flask, render_template, request, jsonify, abort, redirect, session, make_response
import json
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= FIREBASE ADMIN =================
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret")

# File synchronization lock to prevent JSON read/write corruption
file_lock = threading.Lock()

# 🔥 SESSION COOKIE CONFIGURATION
app.config['SESSION_COOKIE_SAMESITE'] = "Lax"
app.config['SESSION_COOKIE_SECURE'] = False  # Change to True when deployed over production HTTPS

# ================= GROQ CONFIG =================
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

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

if not api_keys:
    env_keys = [
        os.environ.get("GROQ_API_KEY_1"),
        os.environ.get("GROQ_API_KEY_2"),
        os.environ.get("GROQ_API_KEY_3")
    ]
    api_keys = [k.strip() for k in env_keys if k and k.strip()]

# ================= ANTHROPIC CONFIG =================
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
except ImportError:
    ANTHROPIC_AVAILABLE = False
    ANTHROPIC_API_KEY = ""


# ── Groq concurrent execution thread ─────────────────────────────────────────
def try_single_key(key, user_message):
    try:
        client = Groq(api_key=key, timeout=4.0)

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": "You are an intelligent exam mentor. Answer clearly and concisely."
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            temperature=0.5,
            max_tokens=300
        )

        return completion.choices[0].message.content.strip()

    except Exception as e:
        return e


# ── Anthropic execution fallback thread ──────────────────────────────────────
def try_anthropic(user_message):

    if not ANTHROPIC_AVAILABLE:
        raise Exception("anthropic package not installed. Run: pip install anthropic")

    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY environment variable not set.")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        system="You are an intelligent exam mentor. Help students understand concepts clearly, solve problems step by step, and prepare effectively for exams. Keep answers concise and educational.",
        messages=[
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    return message.content[0].text.strip()


# ── Main AI dispatcher with context worker optimization ──────────────────────
def get_ai_response(user_message):

    if GROQ_AVAILABLE and api_keys:

        last_error = ""

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

        print(f"All Groq keys exhausted or failed: {last_error} — routing to Anthropic Core.")

    try:
        return try_anthropic(user_message)

    except Exception as e:
        return f"AI dispatch platform currently unavailable. Error: {str(e)}"


# ================= FIREBASE INITIALIZATION =================
if not firebase_admin._apps:
    try:
        # Secure Firebase initialization from Render environment variable
        firebase_credentials = os.environ.get("FIREBASE_CREDENTIALS")

        if not firebase_credentials:
            raise Exception("FIREBASE_CREDENTIALS environment variable not found.")

        firebase_json = json.loads(firebase_credentials)

        cred = credentials.Certificate(firebase_json)

        firebase_admin.initialize_app(cred)

        print("[SUCCESS] Firebase Admin SDK initialized securely from environment variables.")

    except Exception as fb_init_err:
        print(f"Firebase initialization bypassed or failed: {fb_init_err}")


# ── LOCAL PATH CONFIGURATIONS ────────────────────────────────────────────────
BASE_DIR = os.getcwd()

QUESTION_BANK_DIR = os.path.join(BASE_DIR, "question_bank")

RESULTS_FILE = os.path.join(BASE_DIR, "results.json")

USERS_FILE = os.path.join(BASE_DIR, "users.json")


# Ensure structural data files exist safely
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

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
            }

            for i in range(1, 11)
        }
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(initial_structure, f, indent=2)


# ================= ROUTE HANDLERS =================

@app.route("/firebase-login", methods=["POST"])
def firebase_login():

    try:
        data = request.get_json()

        if not data or "token" not in data or not data["token"]:

            return jsonify({
                "status": "error",
                "message": "Payload structure failure: No token received."
            }), 400

        token = data["token"]

        # Verify Firebase token
        decoded_token = firebase_auth.verify_id_token(token)

        email = decoded_token.get("email")

        if not email:

            return jsonify({
                "status": "error",
                "message": "No validation identity email associated with token."
            }), 401

        session["user"] = email
        session.permanent = True

        return jsonify({
            "status": "success",
            "user": email
        }), 200

    except firebase_admin.exceptions.FirebaseError as fb_err:

        return jsonify({
            "status": "error",
            "message": f"Identity Gate Failure: {str(fb_err)}"
        }), 401

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": f"System validation execution fault: {str(e)}"
        }), 401


@app.route("/login", methods=["GET", "POST"])
def login():

    if "user" in session:
        return redirect("/")

    if request.method == "POST":

        username = (request.form.get("username") or request.form.get("email") or "").strip()

        password = (request.form.get("password") or "").strip()

        if not username or not password:
            return render_template("login.html", error="PLEASE FILL ALL FIELDS")

        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)

        user = next(
            (
                u for u in users
                if u["username"] == username and u["password"] == password
            ),
            None
        )

        if user:
            session["user"] = username
            session.permanent = True
            return redirect("/")

        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")


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

        users.append({
            "username": username,
            "password": password
        })

        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

        return redirect("/login")

    return render_template("register.html")


@app.route("/")
def home():

    if "user" not in session:
        return redirect("/login")

    return render_template("index.html")


@app.route("/mocktest")
def mocktest():

    if "user" not in session:
        return redirect("/login")

    stages = [
        i for i in range(1, 11)
        if os.path.exists(os.path.join(QUESTION_BANK_DIR, f"stage{i}.json"))
    ]

    return render_template("mocktest.html", stages=stages)


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

    return render_template(
        "mocktest_stage.html",
        stage=stage,
        questions=json.dumps(questions)
    )


@app.route("/mocktest/<int:stage>/result")
def mocktest_result(stage):

    if "user" not in session:
        return redirect("/login")

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

    # Thread lock acquisition protects local updates from write collisions
    with file_lock:

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

        # Update stage summaries safely
        stage_key = f"stage{stage}"

        if stage_key in results.get("stage_summary", {}):

            results["stage_summary"][stage_key]["attempts"] += 1

            if score > results["stage_summary"][stage_key]["best_score"]:
                results["stage_summary"][stage_key]["best_score"] = score

        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

    return render_template(
        "mocktest_result.html",
        stage=stage,
        score=score
    )


@app.route("/performance")
def performance_page():

    if "user" not in session:
        return redirect("/login")

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return render_template("performance.html", data=data)


@app.route("/mentor")
def mentor():

    if "user" not in session:
        return redirect("/login")

    return render_template("mentor.html")


@app.route("/ask_ai", methods=["POST"])
def ask_ai():

    if "user" not in session:
        return jsonify({"reply": "Please login first."}), 401

    user_message = request.json.get("message", "").strip() if request.json else ""

    if not user_message:
        return jsonify({"reply": "Please ask a valid question."}), 400

    try:
        reply = get_ai_response(user_message)

        return jsonify({"reply": reply}), 200

    except Exception as e:

        print(f"AI Dispatched Exception: {e}")

        return jsonify({
            "reply": "AI error. Please check API key or internet connection."
        }), 500


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True,
        use_reloader=False
    )
