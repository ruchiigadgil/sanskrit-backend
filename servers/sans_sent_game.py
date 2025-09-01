
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
print("sys.path:", sys.path)

from flask import Flask, jsonify, request
from flask_cors import CORS
import random
from Database.db import get_db_connection
import logging
import argparse

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "http://localhost:5173",          # Local dev
            "https://*.vercel.app"           # Vercel deployed frontend
        ],
        "methods": ["GET", "OPTIONS"],       # Include OPTIONS
        "allow_headers": ["Content-Type", "Authorization"]  # Allow Authorization header
    }
})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    db = get_db_connection()
    sentences_collection = db["sentences"]
    logger.info("Connected to MongoDB")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    sentences_collection = None

def load_sentences():
    try:
        if sentences_collection is None:
            raise Exception("No MongoDB connection")
        sentences = list(sentences_collection.find())
        logger.info(f"Successfully loaded {len(sentences)} sentences from MongoDB")
        return sentences
    except Exception as e:
        logger.error(f"Error loading sentences: {str(e)}")
        return []

sentences = load_sentences()

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "server": "sentence_game"})

@app.route('/api/get-sentence-game', methods=['GET', 'OPTIONS'])
def get_sentence_game():
    if request.method == 'OPTIONS':
        return '', 200  # Handle preflight request
    
    if not sentences:
        logger.warning("No sentences available")
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001)
    args = parser.parse_args()
    logger.info(f"Starting Sentence Game Server on port {args.port}")
    app.run(debug=False, host='0.0.0.0', port=args.port)

