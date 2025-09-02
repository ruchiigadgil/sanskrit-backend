import sys
import os
from pathlib import Path
import logging
from dotenv import load_dotenv
import random
import re
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from bson.json_util import dumps
from bson.objectid import ObjectId
import bcrypt
import jwt
from datetime import datetime, timedelta
import time

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
        "origins": ["http://localhost:5173", "https://sanskrit-frontend-plum.vercel.app", "https://sanskrit-learning-system.vercel.app","https://sanskrit-frontend-sanskrit-learning.vercel.app"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type"],
        "max_age": 86400,
        "supports_credentials": False
    },
    r"/health": {
        "origins": ["http://localhost:5173", "https://sanskrit-frontend-plum.vercel.app", "https://sanskrit-learning-system.vercel.app","https://sanskrit-frontend-sanskrit-learning.vercel.app"],
        "methods": ["GET"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": False
    }
})

# Configuration
MAIN_PORT = int(os.environ.get('PORT', 10000))  # Match Render's port
MONGODB_URI = os.environ.get('MONGODB_URI')
if not MONGODB_URI:
    logger.error("MONGODB_URI environment variable not set")
    MONGODB_URI = 'mongodb://localhost:27017/sanskrit_learning'  # Fallback
JWT_SECRET = os.environ.get('JWT_SECRET', 'your_jwt_secret_here')

# Global variables for data
sentences = []
conjugations = {}
verbs = []

# Lazy MongoDB connection
db = None
sentences_collection = None
conjugations_collection = None
verbs_collection = None
matching_game_collection = None
users_collection = None

def init_db():
    global db, sentences_collection, conjugations_collection, verbs_collection, matching_game_collection, users_collection, sentences, conjugations, verbs
    if db is None:
        try:
            client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            db = client.get_database()
            sentences_collection = db["sentences"]
            conjugations_collection = db["conjugations"]
            verbs_collection = db["verbs"]
            matching_game_collection = db["matching_game"]
            users_collection = db["users"]
            logger.info("Connected to MongoDB")
            # Load data after connection
            sentences = load_sentences()
            conjugations = load_conjugations()
            verbs = load_verbs()
            if not sentences:
                logger.warning("No sentences found in MongoDB collection")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            db = None

# Initialize database on first request
@app.before_request
def before_request():
    init_db()

# Load data from MongoDB
def load_sentences():
    try:
        if sentences_collection is None:
            raise Exception("No MongoDB connection")
        sentences = list(sentences_collection.find({
            "sentence": {"$exists": True},
            "verb.form": {"$exists": True},
            "verb.root": {"$exists": True},
            "verb.class": {"$exists": True},
            "tense": {"$in": ["present", "past", "future"]},
            "subject.form": {"$exists": True},
            "subject.person": {"$exists": True},
            "subject.number": {"$exists": True}
        }))
        logger.info(f"Loaded {len(sentences)} sentences from MongoDB")
        return sentences
    except Exception as e:
        logger.error(f"Error loading sentences from MongoDB: {str(e)}")
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
            "/api/get-number-games",
            "/api/tense-question",
            "/api/get-tense-questions",
            "/api/get-matching-game",
            "/api/get-sentence-game",
            "/api/register",
            "/api/login",
            "/api/profile",
            "/api/update-score",
            "/api/status",
            "/api/test"
        ]
    })

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
        return jsonify({'status': 'ok'}), 200
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

@app.route('/api/get-number-games', methods=['GET', 'OPTIONS'])
def get_number_games():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        count = int(request.args.get("count", 5))
        if count < 1 or count > 50:
            logger.error(f"Invalid question count: {count}")
            return jsonify({"error": "Invalid question count (1-50 allowed)"}), 400
        all_sentences = list(sentences_collection.find({
            "object": None,
            "subject.person": {"$in": ["1", "2", "3"]},
            "subject.number": {"$in": ["sg", "du", "pl"]}
        }))
        if not all_sentences:
            logger.warning("No sentences available")
            return jsonify({"error": "No sentences available", "data": []}), 404
        selected_sentences = random.sample(all_sentences, min(count, len(all_sentences)))
        cleaned_sentences = [
            {
                "sentence": s.get("sentence", ""),
                "subject": s.get("subject", {}),
                "verb": s.get("verb", {}),
                "tense": s.get("tense", ""),
                "explanation": generate_explanation(s)
            } for s in selected_sentences
        ]
        logger.info(f"Serving {len(cleaned_sentences)} number game sentences")
        return jsonify(cleaned_sentences), 200
    except Exception as e:
        logger.error(f"Error fetching number games: {str(e)}")
        return jsonify({"error": f"Failed to load number games: {str(e)}", "data": []}), 500

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
            logger.error("No sentences available in MongoDB")
            return jsonify({"error": "No sentences available in MongoDB"}), 404
        sentence_data = random.choice(sentences)
        if not all([
            sentence_data.get("sentence"),
            sentence_data.get("verb"),
            sentence_data.get("tense"),
            sentence_data.get("subject")
        ]):
            logger.error(f"Invalid sentence data: {sentence_data.get('sentence', 'unknown')}")
            return jsonify({"error": "Invalid sentence data"}), 400
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

@app.route('/api/tense-question', methods=['GET', 'OPTIONS'])
def get_tense_question():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        questions = list(sentences_collection.find({"tense": {"$exists": True, "$ne": ""}, "sentence": {"$exists": True}}))
        if not questions:
            logger.error("No questions available in MongoDB")
            return jsonify({"error": "No questions available in MongoDB"}), 404
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

@app.route('/api/get-tense-questions', methods=['GET', 'OPTIONS'])
def get_tense_questions():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
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
            logger.error("No questions available in MongoDB")
            return jsonify({"error": "No questions available in MongoDB", "data": []}), 404
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
    try:
        if users_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        data = request.get_json()
        if not data or not isinstance(data, dict):
            logger.error("No JSON data provided or invalid JSON")
            return jsonify({"error": "No data provided or invalid JSON"}), 400
        full_name = data.get('full_name')
        email = data.get('email')
        password = data.get('password')
        if not full_name or not email or not password:
            logger.error(f"Missing required fields: full_name={full_name}, email={email}, password={'***' if password else None}")
            return jsonify({"error": "Missing full_name, email, or password"}), 400
        if users_collection.find_one({"email": email}):
            logger.error(f"User with email {email} already exists")
            return jsonify({"error": "Email already registered"}), 400
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user = {
            "full_name": full_name,
            "email": email,
            "password": hashed_password,
            "score": 0
        }
        result = users_collection.insert_one(user)
        user_id = str(result.inserted_id)
        token = jwt.encode({
            "user_id": user_id,
            "email": email,
            "exp": datetime.utcnow() + timedelta(hours=24)
        }, JWT_SECRET, algorithm="HS256")
        logger.info(f"Registered user: {email}, user_id={user_id}")
        return jsonify({
            "status": "success",
            "message": "User registered successfully",
            "token": token,
            "user": {
                "id": user_id,
                "full_name": full_name,
                "email": email
            }
        }), 201
    except Exception as e:
        logger.error(f"Error registering user: {str(e)}")
        return jsonify({"error": f"Failed to register user: {str(e)}"}), 500

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        if users_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        data = request.get_json()
        if not data or not isinstance(data, dict):
            logger.error("No JSON data provided or invalid JSON")
            return jsonify({"error": "No data provided or invalid JSON"}), 400
        email = data.get('email')
        password = data.get('password')
        if not email or not password:
            logger.error(f"Missing email or password: email={email}, password={'***' if password else None}")
            return jsonify({"error": "Missing email or password"}), 400
        user = users_collection.find_one({"email": email})
        if not user:
            logger.error(f"User not found: {email}")
            return jsonify({"error": "Invalid email or password"}), 401
        if not bcrypt.checkpw(password.encode('utf-8'), user["password"]):
            logger.error(f"Invalid password for user: {email}")
            return jsonify({"error": "Invalid email or password"}), 401
        token = jwt.encode({
            "user_id": str(user["_id"]),
            "email": email,
            "exp": datetime.utcnow() + timedelta(hours=24)
        }, JWT_SECRET, algorithm="HS256")
        logger.info(f"User logged in: {email}")
        return jsonify({
            "status": "success",
            "message": "Login successful",
            "token": token,
            "user": {
                "id": str(user["_id"]),
                "full_name": user.get("full_name"),
                "email": email
            }
        }), 200
    except Exception as e:
        logger.error(f"Error logging in: {str(e)}")
        return jsonify({"error": f"Failed to login: {str(e)}"}), 500

@app.route('/api/profile', methods=['GET', 'OPTIONS'])
def profile():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.error('Missing or invalid Authorization header')
            return jsonify({'error': 'Missing or invalid Authorization header'}), 400
        token = auth_header.split(' ')[1]
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = users_collection.find_one({'_id': ObjectId(decoded['user_id'])})
        if not user:
            logger.error(f'User not found for ID: {decoded["user_id"]}')
            return jsonify({'error': 'User not found'}), 404
        return jsonify({
            'full_name': user.get('full_name', 'User'),
            'score': user.get('score', 0)
        }), 200
    except jwt.InvalidTokenError:
        logger.error('Invalid JWT token')
        return jsonify({'error': 'Invalid token'}), 401
    except Exception as e:
        logger.error(f'Error in profile: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-score', methods=['POST', 'OPTIONS'])
def update_score():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        if users_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"error": "No MongoDB connection"}), 503
        data = request.get_json(force=True)
        if not data or not isinstance(data, dict):
            logger.error(f"Invalid JSON data: {data}")
            return jsonify({"error": "No data provided or invalid JSON"}), 400
        user_id = data.get('user_id')
        score_increment = data.get('score')
        if not user_id or score_increment is None:
            logger.error(f"Missing user_id or score: user_id={user_id}, score={score_increment}")
            return jsonify({"error": "Missing user_id or score"}), 400
        if not isinstance(score_increment, (int, float)) or score_increment < 0:
            logger.error(f"Invalid score value: {score_increment}")
            return jsonify({"error": "Score increment must be a non-negative number"}), 400
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.error("No valid Authorization header provided")
            return jsonify({"error": "Authorization header missing or invalid"}), 401
        token = auth_header.split(' ')[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload["user_id"] != user_id:
            logger.error(f"Token user_id {payload['user_id']} does not match provided user_id {user_id}")
            return jsonify({"error": "Unauthorized score update"}), 403
        result = users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"score": int(score_increment)}},
            upsert=False
        )
        if result.matched_count == 0:
            logger.error(f"User not found: {user_id}")
            return jsonify({"error": "User not found"}), 404
        updated_user = users_collection.find_one({"_id": ObjectId(user_id)})
        new_score = updated_user.get("score", 0)
        logger.info(f"Incremented score for user {user_id} by {score_increment}, new score: {new_score}")
        return jsonify({"status": "success", "score": new_score}), 200
    except jwt.ExpiredSignatureError:
        logger.error("JWT token expired")
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        logger.error("Invalid JWT token")
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        logger.error(f"Error updating score: {str(e)}")
        return jsonify({"error": f"Failed to update score: {str(e)}"}), 500

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

@app.route('/api/health', methods=['GET'])
def health():
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return jsonify({"status": "unhealthy", "error": "No MongoDB connection"}), 503
        if sentences_collection.count_documents({}) == 0:
            logger.error("No sentences available in MongoDB")
            return jsonify({"status": "unhealthy", "error": "No sentences available in MongoDB"}), 500
        return jsonify({"status": "healthy", "server": "sanskrit_learning_system"}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"🕉️ Starting Sanskrit Learning System on port {MAIN_PORT}...")
    app.run(debug=False, host='0.0.0.0', port=MAIN_PORT, use_reloader=False)
