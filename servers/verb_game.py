import sys
import os
# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
# Verify sys.path for debugging
print("sys.path:", sys.path)

import random
import json
import re
from flask import Flask, jsonify, request
from flask_cors import CORS
from Database.db import get_db_connection
from bson.json_util import dumps
import logging
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5173"],
        "methods": ["GET", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# MongoDB connection
try:
    db = get_db_connection()
    sentences_collection = db["sentences"]
    conjugations_collection = db["conjugations"]
    verbs_collection = db["verbs"]
    logger.info("Connected to MongoDB")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    sentences_collection = None
    conjugations_collection = None
    verbs_collection = None

# === Load data ===
def load_sentences():
    try:
        if sentences_collection is None:
            logger.error("No MongoDB connection")
            return []
        sentences = list(sentences_collection.find({
            "sentence": {"$exists": True},
            "verb.form": {"$exists": True},
            "verb.root": {"$exists": True},
            "verb.class": {"$exists": True},
            "tense": {"$exists": True, "$in": ["present", "past", "future"]},
            "subject.form": {"$exists": True},
            "subject.person": {"$exists": True},
            "subject.number": {"$exists": True}
        }))
        logger.info(f"Loaded {len(sentences)} sentences from MongoDB")
        return sentences
    except Exception as e:
        logger.error(f"Error loading sentences: {str(e)}")
        return []

def load_conjugations():
    try:
        if conjugations_collection is None:
            logger.error("No MongoDB connection")
            return {}
        conjugations = {}
        for doc in conjugations_collection.find():
            for tense in ["present", "past", "future"]:
                if tense in doc:
                    conjugations[tense] = {k: v for k, v in doc[tense].items() if k in ["1P", "4P", "6P", "10P"]}
        logger.info(f"Loaded conjugations for {len(conjugations)} tenses")
        return conjugations
    except Exception as e:
        logger.error(f"Error loading conjugations: {str(e)}")
        return {}

def load_verbs():
    try:
        if verbs_collection is None:
            logger.error("No MongoDB connection")
            return []
        verbs = []
        for doc in verbs_collection.find():
            for vclass in ["1P", "4P", "6P", "10P"]:
                if vclass in doc and "verbs" in doc[vclass]:
                    for verb in doc[vclass]["verbs"]:
                        verbs.append({
                            "root": verb["root"],
                            "meaning": verb["meaning"],
                            "verb_class": vclass,
                            "past_stem": verb.get("past_stem"),
                            "future_stem": verb.get("future_stem"),
                            "requires_object": verb.get("requires_object", False),
                            "allowed_subject_class": verb.get("allowed_subject_class", []),
                            "allowed_object_class": verb.get("allowed_object_class", [])
                        })
        logger.info(f"Loaded {len(verbs)} verbs from MongoDB")
        return verbs
    except Exception as e:
        logger.error(f"Error loading verbs: {str(e)}")
        return []

sentences = load_sentences()
conjugations = load_conjugations()
verbs = load_verbs()

# === Helper Functions ===
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
        
        # Select stem per gen.py rules
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
        
        # Preserve halant for present tense, 4P verbs
        if not (tense == "present" and vclass == "4P"):
            if stem.endswith("्"):
                stem = stem[:-1]
        
        # Define all possible person/number combinations
        person_numbers = [
            "1_sg", "2_sg", "3_sg",
            "1_du", "2_du", "3_du",
            "1_pl", "2_pl", "3_pl"
        ]
        # Exclude the correct form's person/number
        correct_person_number = f"{person}_{number}"
        available_person_numbers = [pn for pn in person_numbers if pn != correct_person_number]
        
        distractors = []
        # Generate distractors using same verb root/stem
        for pn in random.sample(available_person_numbers, len(available_person_numbers)):
            try:
                suffix = conjugations[tense][vclass].get(pn)
                if not suffix:
                    logger.warning(f"No suffix for {tense}, {vclass}, {pn}")
                    continue
                form = stem + suffix.replace("A", "")
                if (form != correct_form and 
                    form not in distractors and 
                    re.match(r'^[\u0900-\u097F]+$', form)):
                    distractors.append(form)
                if len(distractors) >= 2:  # Stop when we have 2 distractors
                    break
            except Exception as e:
                logger.warning(f"Error generating distractor for {pn}: {str(e)}")
                continue
        
        # Log warning if insufficient distractors
        if len(distractors) < 2:
            logger.warning(f"Insufficient distractors for {correct_form} (tense: {tense}, class: {vclass}, person: {person}, number: {number}): {distractors}")
            # Return what we have to avoid breaking the game
            return distractors[:2]
        
        logger.info(f"Generated distractors for {correct_form} (tense: {tense}, class: {vclass}, person: {person}, number: {number}): {distractors[:2]}")
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

# === API Route ===
@app.route("/api/get-game", methods=["GET", "OPTIONS"])
def get_game():
    if request.method == "OPTIONS":
        logger.info("Handling OPTIONS request for /api/get-game")
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

# === Health check route ===
@app.route("/health", methods=["GET"])
def health():
    try:
        if sentences_collection is None or sentences_collection.count_documents({}) == 0:
            logger.error("No sentences available in database")
            return jsonify({"status": "unhealthy", "error": "No sentences available"}), 500
        logger.info("Health check successful")
        return jsonify({"status": "healthy", "server": "verb_game"}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# === Start server ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5002)
    args = parser.parse_args()
    logger.info(f"Starting Verb Game Server on port {args.port}")
    logger.info(f"Loaded {len(sentences)} sentences, {len(verbs)} verbs")
    app.run(host="0.0.0.0", port=args.port, debug=True)