import sys
import os
from pathlib import Path
import logging
from dotenv import load_dotenv
import random
import re
import json
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from pymongo import MongoClient
from bson.json_util import dumps

# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5173", "https://*.vercel.app"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    },
    r"/health": {
        "origins": ["http://localhost:5173", "https://*.vercel.app"],
        "methods": ["GET"],
        "allow_headers": ["Content-Type"]
    }
})

# Configuration
MAIN_PORT = int(os.environ.get('PORT', 5000))
DATABASE_URL = os.environ.get('DATABASE_URL', 'https://sanskrit-database.onrender.com')

# MongoDB connection
def get_db_connection():
    try:
        client = MongoClient(DATABASE_URL, serverSelectionTimeoutMS=5000)
        # Test the connection
        client.admin.command('ping')
        db = client.get_database()
        logger.info("Connected to MongoDB")
        return db
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {str(e)}")
        return None

# Initialize database and collections
db = get_db_connection()
sentences_collection = db["sentences"] if db is not None else None
conjugations_collection = db["conjugations"] if db is not None else None
verbs_collection = db["verbs"] if db is not None else None
matching_game_collection = db["matching_game"] if db is not None else None

# Load data
def load_sentences():
    try:
        if sentences_collection is None:
            raise Exception("No MongoDB connection")
        return list(sentences_collection.find({
            "sentence": {"$exists": True},
            "verb.form": {"$exists": True},
            "verb.root": {"$exists": True},
            "verb.class": {"$exists": True},
            "tense": {"$in": ["present", "past", "future"]},
            "subject.form": {"$exists": True},
            "subject.person": {"$exists": True},
            "subject.number": {"$exists": True}
        }))
    except Exception as e:
        logger.error(f"Error loading sentences: {str(e)}")
        return []

def load_conjugations():
    try:
        if conjugations_collection is None:
            raise Exception("No MongoDB connection")
        combined = {}
        for doc in conjugations_collection.find():
            for tense in ["present", "past", "future"]:
                if tense in doc:
                    combined[tense] = {k: v for k, v in doc[tense].items() if k in ["1P", "4P", "6P", "10P"]}
        logger.info(f"Loaded conjugations for {len(combined)} tenses")
        return combined
    except Exception as e:
        logger.error(f"Error loading conjugations: {str(e)}")
        return {}

def load_verbs():
    try:
        if verbs_collection is None:
            raise Exception("No MongoDB connection")
        flat_verbs = []
        for doc in verbs_collection.find():
            for vclass in ["1P", "4P", "6P", "10P"]:
                if vclass in doc and "verbs" in doc[vclass]:
                    for verb in doc[vclass]["verbs"]:
                        flat_verbs.append({
                            "root": verb["root"],
                            "meaning": verb["meaning"],
                            "verb_class": vclass,
                            "past_stem": verb.get("past_stem"),
                            "future_stem": verb.get("future_stem"),
                            "requires_object": verb.get("requires_object", False),
                            "allowed_subject_class": verb.get("allowed_subject_class", []),
                            "allowed_object_class": verb.get("allowed_object_class", [])
                        })
        logger.info(f"Loaded {len(flat_verbs)} verbs")
        return flat_verbs
    except Exception as e:
        logger.error(f"Error loading verbs: {str(e)}")
        return []

sentences = load_sentences()
conjugations = load_conjugations()
verbs = load_verbs()

# Helper Functions
def label(person, number):
    person_map = {"1": "First person", "2": "Second person", "3": "Third person"}
    number_map = {"sg": "singular", "du": "dual", "pl": "plural"}
    return f"{person_map.get(person, 'Unknown')} {number_map.get(number, 'Unknown')}"

def replace_verb_with_blank(text, form):
    try:
        if not form:
            logger.error("No verb form provided for replacement")
            return text
        words = text.split()
        if form in words:
            words[words.index(form)] = "_____"
        else:
            logger.warning(f"Verb form '{form}' not found in sentence: {text}")
            words[-1] = "_____"
        return " ".join(words)
    except Exception as e:
        logger.error(f"Error in replace_verb_with_blank: {str(e)}")
        return text

def generate_distractors(correct_form, root, vclass, tense, person, number):
    try:
        if tense not in conjugations or vclass not in conjugations[tense]:
            logger.warning(f"No conjugations for tense: {tense}, class: {vclass}")
            return []
        matching = next((v for v in verbs if v.get("root") == root and v.get("verb_class") == vclass), None)
        if not matching:
            logger.warning(f"No verb found for root: {root}, class: {vclass}")
            return []
        if tense == "past":
            stem = matching.get("past_stem", root)
        elif tense == "future":
            stem = matching.get("future_stem", root)
        else:
            stem = root
        if not (tense == "present" and vclass == "4P"):
            if stem.endswith("्"):
                stem = stem[:-1]
        person_numbers = [
            "1_sg", "2_sg", "3_sg",
            "1_du", "2_du", "3_du",
            "1_pl", "2_pl", "3_pl"
        ]
        correct_person_number = f"{person}_{number}"
        available_person_numbers = [pn for pn in person_numbers if pn != correct_person_number]
        distractors = []
        for pn in random.sample(available_person_numbers, len(available_person_numbers)):
            try:
                suffix = conjugations[tense][vclass].get(pn)
                if not suffix:
                    continue
                form = stem + suffix.replace("A", "")
                if (form != correct_form and 
                    form not in distractors and 
                    re.match(r'^[\u0900-\u097F]+$', form)):
                    distractors.append(form)
                if len(distractors) >= 2:
                    break
            except Exception as e:
                logger.warning(f"Error generating distractor for {pn}: {str(e)}")
                continue
        if len(distractors) < 2:
            logger.warning(f"Insufficient distractors for {correct_form}: {distractors}")
            return distractors[:2]
        return distractors[:2]
    except Exception as e:
        logger.error(f"Error in generate_distractors: {str(e)}")
        return []

def generate_explanation(sentence):
    try:
        subject = sentence.get("subject", {})
        verb = sentence.get("verb", {})
        obj = sentence.get("object", {})
        parts = [
            f"Subject '{subject.get('form', '')}' is in {label(subject.get('person'), subject.get('number'))} form.",
            f"Verb root: '{verb.get('root', '')}', class {verb.get('class', '')}, meaning: '{verb.get('meaning', '')}'.",
            f"Tense: {sentence.get('tense', 'unknown')}.",
            f"This verb {'requires' if obj else 'does not require'} an object.",
            f"The correct form is '{verb.get('form', '')}' to match the subject and tense."
        ]
        return " ".join(parts) or "No explanation available."
    except Exception as e:
        logger.error(f"Error generating explanation for {sentence.get('sentence', 'unknown')}: {str(e)}")
        return "Error generating explanation."

# Routes
@app.route('/')
def home():
    logger.info("Accessing root URL /")
    return jsonify({
        "message": "Sanskrit Learning System API",
        "endpoints": [
            "/api/sentences",
            "/api/get-game",
            "/api/get-number-game",
            "/api/tense-question",
            "/api/get-tense-questions",
            "/api/get-matching-game",
            "/api/get-sentence-game",
            "/api/register",
            "/api/login",
            "/api/profile",
            "/api/update-score",
            "/api/status",
            "/api/test",
            "/api/load-sentences"
        ]
    })

@app.route('/api/load-sentences', methods=['GET'])
def load_sentences_json():
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"status": "error", "message": "No MongoDB connection"}), 503
        dataset_path = Path(root_path) / "dataset" / "sentences.json"
        if not dataset_path.exists():
            logger.error("sentences.json not found")
            return jsonify({"status": "error", "message": "sentences.json not found"}), 404
        with open(dataset_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        sentences_collection.delete_many({})
        sentences_collection.insert_many(data)
        global sentences
        sentences = load_sentences()  # Reload sentences into memory
        logger.info(f"Loaded {len(data)} sentences into MongoDB")
        return jsonify({"status": "success", "message": f"Loaded {len(data)} sentences"})
    except Exception as e:
        logger.error(f"Error loading sentences.json: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sentences', methods=['GET'])
def get_sentences():
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        sentences = list(sentences_collection.find())
        return Response(dumps(sentences), mimetype="application/json"), 200
    except Exception as e:
        logger.error(f"Error loading sentences: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-game', methods=['GET', 'OPTIONS'])
def get_verb_game():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        if not sentences:
            logger.error("No sentences available")
            return jsonify({"error": "No sentences available"}), 404
        q = random.choice(sentences)
        if not all([
            q.get("sentence"), 
            q.get("verb"), 
            q["verb"].get("form"), 
            q.get("tense"), 
            q.get("subject"), 
            q["subject"].get("form"), 
            q["subject"].get("person"), 
            q["subject"].get("number")
        ]):
            logger.error(f"Invalid sentence selected: {q.get('sentence', 'unknown')}")
            return jsonify({"error": "Invalid sentence data"}), 404
        if not re.match(r'^[\u0900-\u097F]+$', q["verb"]["form"]):
            logger.error(f"Invalid verb form: {q['verb']['form']}")
            return jsonify({"error": "Invalid verb form"}), 404
        if q.get("tense") not in ["present", "past", "future"]:
            logger.error(f"Invalid tense: {q.get('tense')}")
            return jsonify({"error": "Invalid tense"}), 404
        sentence = replace_verb_with_blank(q["sentence"], q["verb"]["form"])
        distractors = generate_distractors(
            q["verb"]["form"], 
            q["verb"]["root"], 
            q["verb"]["class"], 
            q["tense"],
            q["subject"]["person"],
            q["subject"]["number"]
        )
        options = [q["verb"]["form"]] + distractors
        if len(options) < 3:
            logger.error(f"Insufficient options ({len(options)}) for sentence: {q['sentence']}")
            return jsonify({"error": "Insufficient options available"}), 404
        random.shuffle(options)
        logger.info(f"Serving question: {sentence} with options: {options}")
        return jsonify({
            "sentence": sentence,
            "correct": q["verb"]["form"],
            "options": options,
            "hint": f"Subject '{q['subject']['form']}' is {label(q['subject']['person'], q['subject']['number'])} in {q['tense']} tense.",
            "explanation": generate_explanation(q)
        })
    except Exception as e:
        logger.error(f"Error serving game: {str(e)}")
        return jsonify({"error": f"Failed to load question: {str(e)}"}), 500

@app.route('/api/get-number-game', methods=['GET', 'OPTIONS'])
def get_number_game():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        all_sentences = list(sentences_collection.find({
            "object": None,
            "subject.person": {"$in": ["1", "2", "3"]},
            "subject.number": {"$in": ["sg", "du", "pl"]}
        }))
        if not all_sentences:
            logger.warning("No sentences available")
            return jsonify({"error": "No sentences available"}), 404
        sentence = random.choice(all_sentences)
        if not (sentence.get("subject") and sentence.get("subject").get("person") and sentence.get("subject").get("number")):
            logger.warning(f"Invalid sentence data: {sentence}")
            return jsonify({"error": "Invalid sentence data"}), 400
        logger.info(f"Returning sentence: {sentence.get('sentence')}")
        return Response(dumps(sentence), mimetype="application/json"), 200
    except Exception as e:
        logger.error(f"Error fetching number game data: {str(e)}")
        return jsonify({"error": str(e)}), 503

@app.route('/api/generate-matching-game', methods=['GET'])
def generate_matching_game():
    try:
        if matching_game_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"status": "error", "message": "No MongoDB connection"}), 503
        dataset_path = Path(root_path) / "dataset"
        if not dataset_path.exists():
            logger.error("Dataset directory not found")
            return jsonify({"status": "error", "message": "Dataset directory not found"}), 404
        os.chdir(dataset_path)
        result = os.system(f"{sys.executable} mtc_gen.py")
        os.chdir(Path(__file__).parent)
        if result == 0:
            with open(dataset_path / 'matching_game.json', 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            matching_game_collection.delete_many({})
            matching_game_collection.insert_many(data)
            return jsonify({"status": "success", "message": "Matching game data generated and loaded to MongoDB"})
        else:
            logger.error("Failed to generate matching game data")
            return jsonify({"status": "error", "message": "Failed to generate matching game data"}), 500
    except Exception as e:
        logger.error(f"Error running mtc_gen.py: {str(e)}")
        return jsonify({"status": "error", "message": f"Error running mtc_gen.py: {str(e)}"}), 500

@app.route('/api/get-matching-game', methods=['GET'])
def get_matching_game():
    try:
        if matching_game_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        data = list(matching_game_collection.find({
            "subject_root": {"$exists": True},
            "verb_root": {"$exists": True},
            "subject_forms.sg": {"$exists": True},
            "subject_forms.du": {"$exists": True},
            "subject_forms.pl": {"$exists": True},
            "verb_forms.sg": {"$exists": True},
            "verb_forms.du": {"$exists": True},
            "verb_forms.pl": {"$exists": True},
            "tense": {"$exists": True},
            "meaning": {"$exists": True}
        }, {"_id": 0}))
        return Response(dumps(data), mimetype="application/json"), 200
    except Exception as e:
        logger.error(f"Error loading matching game data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-sentence-game', methods=['GET', 'OPTIONS'])
def get_sentence_game():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        if not sentences:
            logger.error("No sentences available")
            return jsonify({"error": "No sentences available"}), 404
        sentence_data = random.choice(sentences)
        hint = {
            "subject": sentence_data.get("subject"),
            "object": sentence_data.get("object"),
            "verb": sentence_data.get("verb")
        }
        logger.info(f"Returning sentence: {sentence_data.get('sentence')}")
        return jsonify({
            "sentence": sentence_data.get("sentence"),
            "subject": sentence_data.get("subject"),
            "object": sentence_data.get("object"),
            "verb": sentence_data.get("verb"),
            "tense": sentence_data.get("tense"),
            "hint": hint
        })
    except Exception as e:
        logger.error(f"Error fetching sentence game data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get-tense-question', methods=['GET'])
def get_tense_question():
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        questions = list(sentences_collection.find({"tense": {"$exists": True, "$ne": ""}, "sentence": {"$exists": True}}))
        if not questions:
            logger.error("No questions available in database")
            return jsonify({"error": "No questions available"}), 404
        question = random.choice(questions)
        explanation = generate_explanation(question)
        logger.info(f"Serving question: {question.get('sentence', 'Unknown')}")
        return jsonify({
            "sentence": question.get("sentence", ""),
            "tense": question.get("tense", ""),
            "explanation": explanation,
            "verb": question.get("verb", {}),
            "subject": question.get("subject", {}),
            "object": question.get("object", {})
        })
    except Exception as e:
        logger.error(f"Error serving tense question: {str(e)}")
        return jsonify({"error": f"Failed to load question: {str(e)}"}), 500

@app.route('/api/get-tense-questions', methods=['GET'])
def get_tense_questions():
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        count = int(request.args.get("count", 5))
        if count < 1 or count > 50:
            logger.error(f"Invalid question count: {count}")
            return jsonify({"error": "Invalid question count (1-50 allowed)"}), 400
        questions = list(sentences_collection.find({"tense": {"$exists": True, "$ne": ""}, "sentence": {"$exists": True}}))
        if not questions:
            logger.error("No questions available in database")
            return jsonify({"error": "No questions available", "data": []}), 404
        selected_questions = random.sample(questions, min(count, len(questions)))
        cleaned_questions = [
            {
                "sentence": q.get("sentence", ""),
                "tense": q.get("tense", ""),
                "explanation": generate_explanation(q),
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

@app.route('/api/register', methods=['POST', 'OPTIONS'])
def register_user():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    return jsonify({"error": "Registration not implemented in this version"}), 501

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    return jsonify({"error": "Login not implemented in this version"}), 501

@app.route('/api/profile', methods=['GET', 'OPTIONS'])
def get_profile():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    return jsonify({"error": "Profile not implemented in this version"}), 501

@app.route('/api/update-score', methods=['POST', 'OPTIONS'])
def update_score():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    return jsonify({"error": "Score update not implemented in this version"}), 501

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    try:
        if db is None:
            logger.error("No MongoDB connection")
            return jsonify({'error': 'Database server unavailable'}), 503
        db.command('ping')
        return jsonify({"status": "Database connection successful"}), 200
    except Exception as e:
        logger.error(f"Database test failed: {str(e)}")
        return jsonify({'error': 'Database server unavailable'}), 503

@app.route('/api/status', methods=['GET'])
def system_status():
    try:
        db_status = db.command('ping') if db is not None else False
    except Exception:
        db_status = False
    return jsonify({
        "main_server": "online",
        "sentence_game_server": "online",
        "verb_game_server": "online",
        "tense_game_server": "online",
        "number_game_server": "online",
        "matching_game_server": "online",
        "database_server": "online" if db_status else "offline",
        "port": MAIN_PORT
    })

@app.route('/health', methods=['GET'])
def health():
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"status": "unhealthy", "error": "No MongoDB connection"}), 503
        if sentences_collection.count_documents({}) == 0:
            logger.error("No sentences available in database")
            return jsonify({"status": "unhealthy", "error": "No sentences available"}), 500
        return jsonify({"status": "healthy", "server": "sanskrit_learning_system"}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"🕉️ Starting Sanskrit Learning System on port {MAIN_PORT}...")
    app.run(debug=False, host='0.0.0.0', port=MAIN_PORT, use_reloader=False)
