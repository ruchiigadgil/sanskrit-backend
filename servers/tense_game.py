from flask import Flask, jsonify, request
from flask_cors import CORS
import random
import logging
from Database.db import get_db_connection
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {
    "origins": ["http://localhost:5173"],
    "methods": ["GET"],
    "allow_headers": ["Content-Type"]
}})

# Load data
def load_questions():
    try:
        db = get_db_connection()
        questions = list(db.sentences.find({"tense": {"$exists": True, "$ne": ""}, "sentence": {"$exists": True}}))
        logger.info(f"Loaded {len(questions)} sentences from MongoDB")
        return questions
    except Exception as e:
        logger.error(f"Error loading sentences: {str(e)}")
        return []

all_questions = load_questions()

# Generate explanation for each sentence
def generate_explanation(q):
    try:
        verb = q.get("verb", {})
        subject = q.get("subject", {})
        obj = q.get("object", {})
        explanation = []

        if verb:
            explanation.append(
                f"Verb root: '{verb.get('root', '')}', form: '{verb.get('form', '')}' "
                f"({q.get('tense', 'unknown')} tense), meaning: '{verb.get('meaning', '')}'."
            )
        if subject:
            explanation.append(
                f"Subject: '{subject.get('form', '')}', number: {subject.get('number', '')}, gender: {subject.get('gender', '')}."
            )
        if obj:
            explanation.append(
                f"Object: '{obj.get('form', '')}', number: {obj.get('number', '')}, gender: {obj.get('gender', '')}."
            )
        return " ".join(explanation) or "No explanation available."
    except Exception as e:
        logger.error(f"Error generating explanation for {q.get('sentence', 'unknown')}: {str(e)}")
        return "Error generating explanation."

# Add explanation to each question
for q in all_questions:
    q["explanation"] = generate_explanation(q)

# Route to serve a single random question
@app.route("/api/get-tense-question", methods=["GET"])
def get_tense_question():
    if not all_questions:
        logger.error("No questions available in database")
        return jsonify({"error": "No questions available"}), 404
    question = random.choice(all_questions)
    logger.info(f"Serving question: {question.get('sentence', 'Unknown')}")
    return jsonify({
        "sentence": question.get("sentence", ""),
        "tense": question.get("tense", ""),
        "explanation": question.get("explanation", ""),
        "verb": question.get("verb", {}),
        "subject": question.get("subject", {}),
        "object": question.get("object", {})
    })

# Route to serve multiple questions
@app.route("/api/get-tense-questions", methods=["GET"])
def get_tense_questions():
    try:
        count = int(request.args.get("count", 5))
        if count < 1 or count > 50:
            logger.error(f"Invalid question count: {count}")
            return jsonify({"error": "Invalid question count (1-50 allowed)"}), 400
        if not all_questions:
            logger.error("No questions available in database")
            return jsonify({"error": "No questions available"}, []), 404
        selected_questions = random.sample(all_questions, min(count, len(all_questions)))
        cleaned_questions = [
            {
                "sentence": q.get("sentence", ""),
                "tense": q.get("tense", ""),
                "explanation": q.get("explanation", ""),
                "verb": q.get("verb", {}),
                "subject": q.get("subject", {}),
                "object": q.get("object", {})
            } for q in selected_questions
        ]
        logger.info(f"Serving {len(cleaned_questions)} questions")
        return jsonify(cleaned_questions)
    except Exception as e:
        logger.error(f"Error serving questions: {str(e)}")
        return jsonify({"error": f"Failed to load questions: {str(e)}", "data": []}), 500

@app.route("/health")
def health():
    try:
        db = get_db_connection()
        db.command('ping')
        return jsonify({"status": "healthy"}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5003)
    args = parser.parse_args()
    logger.info(f"Starting Tense Game Server on port {args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False)