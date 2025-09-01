import sys
from pathlib import Path
import os
import logging
from dotenv import load_dotenv
import threading
import time
import requests
import json
from bson.json_util import dumps

# Import Flask apps from game server modules
from servers.mtcGame import app as mtc_app
from servers.tense_game import app as tense_app
from servers.verb_game import app as verb_app
from servers.number_game import app as number_app
from servers.sans_sent_game import app as sans_sent_app

# Add root directory to Python path
root_path = str(Path(__file__).resolve().parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)
print("Python path:", sys.path)
print("Root directory:", root_path)
print("Current working directory:", os.getcwd())
print("Files in root directory:", os.listdir(root_path))
print("Files in Database directory:", os.listdir(os.path.join(root_path, 'Database')))

try:
    from Database.db import get_db_connection
    print("Database module imported successfully")
except Exception as e:
    print("Failed to import Database.db:", str(e))
    raise

from flask import Flask, jsonify, request
from flask_cors import CORS

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {
    "origins": ["http://localhost:5173"],  # Update with frontend URL after deployment
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

# Configuration
SANS_SENT_PORT = 5001
VERB_GAME_PORT = 5002
TENSE_GAME_PORT = 5003
NUMBER_GAME_PORT = 5004
MTC_GAME_PORT = 5005
DATABASE_URL = os.environ.get('DATABASE_URL', 'https://sanskrit-database.onrender.com')
MAIN_PORT = int(os.environ.get('PORT', 5000))

# Function to check server health
def check_server_health(port, name):
    try:
        response = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Health check failed for {name}: {str(e)}")
        return False

# Function to start a Flask app in a thread
def start_flask_thread(flask_app, port, name):
    def run_app():
        logger.info(f"Starting {name} on internal port {port}...")
        flask_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
    
    thread = threading.Thread(target=run_app, daemon=True)
    thread.start()
    logger.info(f"Started {name} thread on port {port}")
    return thread

# Start background servers
def start_background_servers():
    sans_sent_thread = start_flask_thread(sans_sent_app, SANS_SENT_PORT, "Sentence Game Server")
    verb_game_thread = start_flask_thread(verb_app, VERB_GAME_PORT, "Verb Game Server")
    tense_game_thread = start_flask_thread(tense_app, TENSE_GAME_PORT, "Tense Game Server")
    number_game_thread = start_flask_thread(number_app, NUMBER_GAME_PORT, "Number Game Server")
    mtc_game_thread = start_flask_thread(mtc_app, MTC_GAME_PORT, "Matching Game Server")
    
    for port, name in [
        (SANS_SENT_PORT, "Sentence Game"),
        (VERB_GAME_PORT, "Verb Game"),
        (TENSE_GAME_PORT, "Tense Game"),
        (NUMBER_GAME_PORT, "Number Game"),
        (MTC_GAME_PORT, "Matching Game"),
    ]:
        for _ in range(10):
            if check_server_health(port, name):
                logger.info(f"✓ {name} Server is running")
                break
            logger.warning(f"Waiting for {name} Server...")
            time.sleep(1)
        else:
            logger.error(f"✗ {name} Server failed to start")

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
            "/api/get-matching-game",
            "/api/register",
            "/api/login",
            "/api/profile",
            "/api/update-score",
            "/api/status"
        ]
    })

@app.route('/api/sentences')
def get_sentences():
    try:
        db = get_db_connection()
        sentences = list(db.sentences.find())
        return jsonify(dumps(sentences)), 200
    except Exception as e:
        logger.error(f"Error loading sentences: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-game')
def get_verb_game():
    try:
        response = requests.get(f"http://127.0.0.1:{VERB_GAME_PORT}/api/get-game", timeout=10)
        return jsonify(response.json()) if response.ok else jsonify({"error": "Failed to get verb game data"}), response.status_code
    except Exception as e:
        logger.error(f"Error fetching verb game data: {str(e)}")
        return jsonify({"error": str(e)}), 503

@app.route('/api/get-number-game', methods=['GET', 'OPTIONS'])
def get_number_game():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:5173')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response
    try:
        headers = {'Authorization': request.headers.get('Authorization')}
        response = requests.get(f"http://127.0.0.1:{NUMBER_GAME_PORT}/api/get-number-game", headers=headers, timeout=10)
        return jsonify(response.json()) if response.ok else jsonify({"error": "Failed to get number game data"}), response.status_code
    except Exception as e:
        logger.error(f"Error fetching number game data: {str(e)}")
        return jsonify({"error": str(e)}), 503

@app.route('/api/generate-matching-game')
def generate_matching_game():
    try:
        dataset_path = Path(root_path) / "dataset"
        if not dataset_path.exists():
            logger.error("Dataset directory not found")
            return jsonify({"status": "error", "message": "Dataset directory not found"}), 404
        os.chdir(dataset_path)
        result = os.system(f"{sys.executable} mtc_gen.py")
        os.chdir(Path(__file__).parent)
        if result == 0:
            db = get_db_connection()
            with open(dataset_path / 'matching_game.json', 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            db.matching_game.delete_many({})
            db.matching_game.insert_many(data)
            return jsonify({"status": "success", "message": "Matching game data generated and loaded to MongoDB"})
        else:
            logger.error("Failed to generate matching game data")
            return jsonify({"status": "error", "message": "Failed to generate matching game data"}), 500
    except Exception as e:
        logger.error(f"Error running mtc_gen.py: {str(e)}")
        return jsonify({"status": "error", "message": f"Error running mtc_gen.py: {str(e)}"}), 500

@app.route('/api/get-matching-game')
def get_matching_game():
    try:
        db = get_db_connection()
        data = list(db.matching_game.find())
        return jsonify(dumps(data)), 200
    except Exception as e:
        logger.error(f"Error loading matching game data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/tense-question')
def proxy_tense_question():
    try:
        response = requests.get(f"http://127.0.0.1:{TENSE_GAME_PORT}/api/get-tense-question", timeout=10)
        return jsonify(response.json()) if response.ok else jsonify({"error": "Failed to get tense question"}), response.status_code
    except Exception as e:
        logger.error(f"Tense Game server error: {str(e)}")
        return jsonify({"error": f"Tense Game server error: {str(e)}"}), 503

@app.route('/api/status')
def system_status():
    try:
        db_status = requests.get(f"{DATABASE_URL}/api/test", timeout=5).ok
    except Exception:
        db_status = False
    return jsonify({
        "main_server": "online",
        "sentence_game_server": "online" if check_server_health(SANS_SENT_PORT, "Sentence Game") else "offline",
        "verb_game_server": "online" if check_server_health(VERB_GAME_PORT, "Verb Game") else "offline",
        "tense_game_server": "online" if check_server_health(TENSE_GAME_PORT, "Tense Game") else "offline",
        "number_game_server": "online" if check_server_health(NUMBER_GAME_PORT, "Number Game") else "offline",
        "matching_game_server": "online" if check_server_health(MTC_GAME_PORT, "Matching Game") else "offline",
        "database_server": "online" if db_status else "offline",
        "ports": {
            "main": MAIN_PORT,
            "sentence_game": SANS_SENT_PORT,
            "verb_game": VERB_GAME_PORT,
            "tense_game": TENSE_GAME_PORT,
            "number_game": NUMBER_GAME_PORT,
            "matching_game": MTC_GAME_PORT,
        }
    })

@app.route('/api/sentence-status')
def sentence_status():
    status = check_server_health(SANS_SENT_PORT, "Sentence Game")
    return jsonify({"status": "online" if status else "offline", "port": SANS_SENT_PORT})

@app.route('/api/verb-status')
def verb_status():
    status = check_server_health(VERB_GAME_PORT, "Verb Game")
    return jsonify({"status": "online" if status else "offline", "port": VERB_GAME_PORT})

@app.route('/api/tense-status')
def tense_status():
    status = check_server_health(TENSE_GAME_PORT, "Tense Game")
    return jsonify({"status": "online" if status else "offline", "port": TENSE_GAME_PORT})

@app.route('/api/number-status')
def number_status():
    status = check_server_health(NUMBER_GAME_PORT, "Number Game")
    return jsonify({"status": "online" if status else "offline", "port": NUMBER_GAME_PORT})

@app.route('/api/mtc-status')
def mtc_status():
    status = check_server_health(MTC_GAME_PORT, "Matching Game")
    return jsonify({"status": "online" if status else "offline", "port": MTC_GAME_PORT})

@app.route('/api/register', methods=['POST', 'OPTIONS'])
def register_user():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:5173')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response
    try:
        response = requests.post(f"{DATABASE_URL}/api/register", json=request.json, timeout=10)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        logger.error(f"Error proxying register: {str(e)}")
        return jsonify({'error': 'Database server unavailable'}), 503

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:5173')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response
    try:
        response = requests.post(f"{DATABASE_URL}/api/login", json=request.json, timeout=10)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        logger.error(f"Error proxying login: {str(e)}")
        return jsonify({'error': 'Database server unavailable'}), 503

@app.route('/api/profile', methods=['GET', 'OPTIONS'])
def get_profile():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:5173')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response
    try:
        headers = {'Authorization': request.headers.get('Authorization')}
        response = requests.get(f"{DATABASE_URL}/api/profile", headers=headers, timeout=10)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        logger.error(f"Error proxying profile: {str(e)}")
        return jsonify({'error': 'Database server unavailable'}), 503

@app.route('/api/update-score', methods=['POST', 'OPTIONS'])
def update_score():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:5173')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response
    try:
        headers = {'Authorization': request.headers.get('Authorization')}
        response = requests.post(f"{DATABASE_URL}/api/update-score", json=request.json, headers=headers, timeout=10)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        logger.error(f"Error proxying update-score: {str(e)}")
        return jsonify({'error': 'Database server unavailable'}), 503

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    try:
        response = requests.get(f"{DATABASE_URL}/api/test", timeout=10)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        logger.error(f"Error proxying test: {str(e)}")
        return jsonify({'error': 'Database server unavailable'}), 503

if __name__ == '__main__':
    logger.info("🕉️ Starting Sanskrit Learning System...")
    threading.Thread(target=start_background_servers, daemon=True).start()
    app.run(debug=False, host='0.0.0.0', port=MAIN_PORT, use_reloader=False)