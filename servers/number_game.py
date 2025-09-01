import sys
import os
# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
# Verify sys.path for debugging (optional, can be removed in production)
print("sys.path:", sys.path)

from flask import Flask, jsonify
from flask_cors import CORS
from Database.db import get_db_connection
import random
import argparse
import logging
from flask import Response
from bson.json_util import dumps

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5173"],
        "methods": ["GET"],
        "allow_headers": ["Content-Type"]
    }
})

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
try:
    db = get_db_connection()
    logger.info("Connected to MongoDB")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    db = None

# Load sentences at startup
logger.info("Loading sentences from MongoDB")
try:
    if db is None:
        raise Exception("No MongoDB connection")
    all_sentences = list(db.sentences.find({
        "object": None,
        "subject.person": {"$in": ["1", "2", "3"]},
        "subject.number": {"$in": ["sg", "du", "pl"]}
    })) 
    logger.info(f"Loaded {len(all_sentences)} sentences without requires_object")
except Exception as e:
    logger.error(f"Error loading sentences: {str(e)}")
    all_sentences = []

@app.route("/api/get-number-game", methods=["GET"])
def get_sentence():
    logger.info("Received request for /api/get-number-game")
    if not all_sentences:
        logger.warning("No sentences available")
        return jsonify({"error": "No sentences available"}), 404
    sentence = random.choice(all_sentences)
    if not (sentence.get("subject") and sentence.get("subject").get("person") and sentence.get("subject").get("number")):
        logger.warning(f"Invalid sentence data: {sentence}")
        return jsonify({"error": "Invalid sentence data"}), 400
    logger.info(f"Returning sentence: {sentence.get('sentence')}")
    return Response(dumps(sentence), mimetype="application/json")

@app.route("/health", methods=["GET"])
def health():
    logger.info("Health check requested")
    try:
        if not all_sentences:
            logger.error("No sentences available in database")
            return jsonify({"status": "unhealthy", "error": "No sentences available"}), 500
        return jsonify({"status": "healthy", "server": "number_game"}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5004)
    args = parser.parse_args()
    logger.info(f"Starting Number Game Server on port {args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=True)