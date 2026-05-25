import json
import random
import os
from groq import Groq

# ================= GROQ CONFIG =================
client = Groq(
    api_key=os.getenv("GROQ_API_KEY")  # Set this in environment
)

# ----------------- MOCK TEST GENERATOR -----------------
def generate_mock(stage: str):
    stage_file = f"question_bank/{stage.lower().replace(' ', '')}.json"

    if not os.path.exists(stage_file):
        return []

    try:
        with open(stage_file, "r", encoding="utf-8") as f:
            questions = json.load(f)

        for q in questions:
            if "options" in q:
                random.shuffle(q["options"])

        return questions

    except Exception as e:
        print(f"Error loading stage file: {e}")
        return []


# ----------------- STATIC REVISION NOTES -----------------
def revision_notes(topic: str) -> str:
    notes_file = "revision_notes.json"

    if not os.path.exists(notes_file):
        return "No revision notes available."

    try:
        with open(notes_file, "r", encoding="utf-8") as f:
            notes_data = json.load(f)

        return notes_data.get(topic.lower(), "Notes not found for this topic.")

    except Exception as e:
        return f"Error loading revision notes: {e}"


# ----------------- PERFORMANCE ANALYTICS -----------------
def analyze_performance(user_results):

    if not user_results:
        return {
            "total_tests": 0,
            "average_score": 0,
            "best_score": 0,
            "topic_summary": {},
            "strong_areas": [],
            "weak_areas": [],
            "trend": [],
            "suggestions": []
        }

    total_tests = len(user_results)
    scores = [r.get("score", 0) for r in user_results]
    avg_score = sum(scores) / total_tests
    best_score = max(scores)

    topic_stats = {}
    for r in user_results:
        for topic, acc in r.get("topics", {}).items():
            topic_stats.setdefault(topic, []).append(acc)

    topic_summary = {t: sum(vals)/len(vals) for t, vals in topic_stats.items()}

    strong = [t for t, acc in topic_summary.items() if acc >= 70]
    weak = [t for t, acc in topic_summary.items() if acc < 50]

    trend = [{"test_id": r.get("test_id"), "score": r.get("score", 0)} for r in user_results]

    suggestions = [
        f"Revise {t} and practice more questions." for t in weak
    ]

    return {
        "total_tests": total_tests,
        "average_score": avg_score,
        "best_score": best_score,
        "topic_summary": topic_summary,
        "strong_areas": strong,
        "weak_areas": weak,
        "trend": trend,
        "suggestions": suggestions
    }


# ================= AI MENTOR (GROQ - FREE & FAST) =================
def get_ai_response(user_input: str):

    if not user_input.strip():
        return "Please ask a valid question."

    try:
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {
                    "role": "system",
                    "content": "You are an intelligent exam mentor. Answer clearly and shortly."
                },
                {
                    "role": "user",
                    "content": user_input
                }
            ],
            temperature=0.5,
            max_tokens=150,
        )

        return completion.choices[0].message.content.strip()

    except Exception as e:
        return f"AI error: {str(e)}"