import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
# Verify sys.path for debugging
print("sys.path:", sys.path)

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import random
from Database.db import get_db_connection
from bson.json_util import dumps
import logging
import argparse

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
try:
    db = get_db_connection()
    sentences_collection = db["sentences"]
    logger.info("Connected to MongoDB")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    sentences_collection = None

# Load sentences data
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

@app.route('/')
def home():
    return send_from_directory('../games', 'sent_game.html')

@app.route('/get_random_sentence')
def get_random_sentence():
    if not sentences:
        logger.warning("No sentences available")
        return jsonify({"error": "No sentences available"}), 404
    
    sentence_data = random.choice(sentences)
    
    # Create hint data
    hint = {
        "subject": sentence_data["subject"] if sentence_data.get("subject") else None,
        "object": sentence_data["object"] if sentence_data.get("object") else None,
        "verb": sentence_data["verb"]
    }
    
    logger.info(f"Returning sentence: {sentence_data.get('sentence')}")
    return jsonify({
        "sentence": sentence_data["sentence"],
        "subject": sentence_data["subject"],
        "object": sentence_data["object"],
        "verb": sentence_data["verb"],
        "tense": sentence_data["tense"],
        "hint": hint
    })

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001)
    args = parser.parse_args()
    
    logger.info(f"Starting Sentence Game Server on port {args.port}")
    app.run(debug=True, host='0.0.0.0', port=args.port)