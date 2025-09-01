import sys
import os
# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import random
import re
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from pymongo import MongoClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

try:
    from Database.db import get_db_connection
    db = get_db_connection()
    matching_game_collection = db["matching_game"]
    sentences_collection = db["sentences"]
    conjugations_collection = db["conjugations"]
    verbs_collection = db["verbs"]
    logger.info("Connected to MongoDB")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    matching_game_collection = None
    sentences_collection = None
    conjugations_collection = None
    verbs_collection = None
    print(f"❌ MongoDB connection failed: {e}")
    matching_game_collection = None
    sentences_collection = None
    conjugations_collection = None
    verbs_collection = None
# === Load data from MongoDB ===
def load_sentences():
    try:
        if sentences_collection is None:
            raise Exception("Sentences collection not available")
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
        print(f"❌ Failed to load sentences: {e}")
        return []

def load_conjugations():
    try:
        if conjugations_collection is None:
            raise Exception("Conjugations collection not available")
        combined = {}
        for doc in conjugations_collection.find():
            for tense in ["present", "past", "future"]:
                if tense in doc:
                    combined[tense] = doc[tense]
        return combined
    except Exception as e:
        print(f"❌ Failed to load conjugations: {e}")
        return {}

def load_verbs():
    try:
        if verbs_collection is None:
            raise Exception("Verbs collection not available")
        flat_verbs = []
        for doc in verbs_collection.find():
            for vclass in doc:
                if vclass in ["1P", "4P", "6P", "10P"]:
                    for verb in doc[vclass].get("verbs", []):
                        verb["verb_class"] = vclass
                        flat_verbs.append(verb)
        return flat_verbs
    except Exception as e:
        print(f"❌ Failed to load verbs: {e}")
        return []

# === Load data ===
sentences = load_sentences()
conjugations = load_conjugations()
verbs = load_verbs()

# === Helper Functions ===
def label(person, number):
    person_map = {"1": "First person", "2": "Second person", "3": "Third person"}
    number_map = {"sg": "singular", "du": "dual", "pl": "plural"}
    return f"{person_map.get(person)} {number_map.get(number)}"

def replace_verb_with_blank(text, form):
    words = text.split()
    if form in words:
        words[words.index(form)] = "_____"
    else:
        words[-1] = "_____"
    return " ".join(words)

def generate_distractors(correct_form, root, vclass, tense):
    if tense not in conjugations or vclass not in conjugations[tense]:
        return []

    stem = root
    matching = next((v for v in verbs if v["root"] == root and v["verb_class"] == vclass), None)
    if tense == "past":
        stem = matching.get("past_stem", root)
    elif tense == "future":
        stem = matching.get("future_stem", root)

    distractors = []
    for key, suffix in conjugations[tense][vclass].items():
        try:
            if stem.endswith("्"):
                stem = stem[:-1]
            form = stem + suffix.replace("A", "")
            if form != correct_form:
                distractors.append(form)
        except:
            continue
    return random.sample(distractors, min(3, len(distractors)))

def generate_explanation(sentence):
    subject = sentence.get("subject", {})
    verb = sentence.get("verb", {})
    obj = sentence.get("object", {})

    parts = [
        f"Subject '{subject.get('form', '')}' is in {label(subject.get('person'), subject.get('number'))} form.",
        f"Verb root: '{verb.get('root')}', class {verb.get('class')}, meaning: '{verb.get('meaning', '')}.",
        f"This verb {'requires' if obj else 'does not require'} an object.",
        f"The correct form is '{verb.get('form')}' to match the subject.",
        f"Full sentence: {sentence.get('sentence')}"
    ]
    return " ".join(parts)

# === API Route ===
@app.route('/api/get-matching-game', methods=['GET'])
def get_matching_game():
    try:
        if matching_game_collection is None:
            raise Exception("MongoDB not connected")
        
        # Filter only documents that have the full expected structure
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
        }, {"_id": 0}))  # Optional: Exclude _id
        
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "server": "verb_game"}), 200

if __name__ == "__main__":
    print(f"Loaded {len(sentences)} sentences")
    app.run(debug=True, port=5005)
