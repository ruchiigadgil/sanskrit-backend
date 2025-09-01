import json
from declensions import (
    a_stem_masc_declension,
    ā_stem_fem_declension,
    a_stem_neut_declension,
    asmad_declension,
    yushmad_declension
)

# Load nouns
with open("nouns.json", "r", encoding="utf-8") as f:
    noun_groups = json.load(f)

nouns = []
for key, roots in noun_groups.items():
    parts = key.split("_")
    gender = None if parts[0] == "none" else parts[0]
    stem = None if parts[1] == "none" else parts[1]
    for root, info in roots.items():
        nouns.append({
            "root": root,
            "gender": gender,
            "stem_type": stem,
            "entity_classes": info["entity_classes"],
            "usable_as_subject": info["usable_as_subject"],
            "usable_as_object": info["usable_as_object"]
        })

# Load conjugations (now supports tenses)
with open("conjugations.json", "r", encoding="utf-8") as f:
    conjugations = json.load(f)

# Load verbs and flatten
with open("verbs.json", "r", encoding="utf-8") as f:
    raw_verbs = json.load(f)

verbs = []
for verb_class, content in raw_verbs.items():
    for verb_entry in content["verbs"]:
        verb_entry["verb_class"] = verb_class
        verbs.append(verb_entry)

# Declensions
declension_map = {
    ("masc", "अ"): a_stem_masc_declension,
    ("fem", "आ"): ā_stem_fem_declension,
    ("neut", "अ"): a_stem_neut_declension
}

role_to_vibhakti = {
    "subject": "प्रथमा",
    "object": "द्वितीया"
}

number_index = {
    "sg": 0,
    "du": 1,
    "pl": 2
}

def inflect_noun(noun, role):
    root = noun["root"]
    number = noun.get("number", "sg")
    index = number_index[number]
    vibhakti = role_to_vibhakti[role]

    if root == "अस्मद्":
        return asmad_declension[vibhakti][index]
    elif root == "युष्मद्":
        return yushmad_declension[vibhakti][index]

    gender = noun.get("gender")
    stem = noun.get("stem_type")
    decl_table = declension_map.get((gender, stem))
    if not decl_table or vibhakti not in decl_table:
        return root

    suffix = decl_table[vibhakti][index]

    if gender == "fem" and stem == "आ":
        return (root[:-1] if root.endswith("ा") else root) + suffix
    else:
        return root + suffix

def get_verb_form(verb, person, number, tense="present"):
    key = f"{person}_{number}"
    verb_class = verb["verb_class"]

    try:
        suffix = conjugations[tense][verb_class][key]
    except KeyError:
        return verb["root"]  # fallback

    # Choose the appropriate stem
    if tense == "future":
        stem = verb.get("future_stem", verb["root"])
    elif tense == "past":
        stem = verb.get("past_stem", verb["root"])
    else:
        stem = verb["root"]

    # Drop halant for all EXCEPT present 4P
    if not (tense == "present" and verb_class == "4P"):
        if stem.endswith("्"):
            stem = stem[:-1]

    return stem + suffix.replace("A", "")

def get_valid_nouns(entity_class, role):
    key = "usable_as_subject" if role == "subject" else "usable_as_object"
    return [
        n.copy() for n in nouns
        if entity_class in n["entity_classes"] and n.get(key, False)
    ]

def generate_subject_verb_pairs(verb, tense="present"):
    pairs = []
    subject_classes = verb["allowed_subject_class"]
    
    for subj_class in subject_classes:
        for subject in get_valid_nouns(subj_class, role="subject"):
            for number in ["sg", "du", "pl"]:
                subject["number"] = number
                person = {"अस्मद्": "1", "युष्मद्": "2"}.get(subject["root"], "3")
                subject_form = inflect_noun(subject, "subject")
                verb_form = get_verb_form(verb, person, number, tense)
                
                pairs.append({
                    "subject": {
                        "root": subject["root"],
                        "form": subject_form,
                        "number": number,
                        "person": person,
                        "gender": subject["gender"],
                        "stem": subject["stem_type"]
                    },
                    "verb": {
                        "root": verb["root"],
                        "form": verb_form,
                        "person": person,
                        "number": number,
                        "class": verb["verb_class"],
                        "meaning": verb.get("meaning", ""),
                        "tense": tense
                    }
                })
    return pairs

def create_matching_game_data(pairs):
    # Organize by subject root and verb root
    game_data = {}
    
    for pair in pairs:
        subj_root = pair["subject"]["root"]
        verb_root = pair["verb"]["root"]
        tense = pair["verb"]["tense"]
        
        key = f"{subj_root}_{verb_root}_{tense}"
        
        if key not in game_data:
            game_data[key] = {
                "subject_root": subj_root,
                "verb_root": verb_root,
                "tense": tense,
                "subject_forms": {"sg": None, "du": None, "pl": None},
                "verb_forms": {"sg": None, "du": None, "pl": None},
                "meaning": pair["verb"]["meaning"]
            }
        
        number = pair["subject"]["number"]
        game_data[key]["subject_forms"][number] = pair["subject"]["form"]
        game_data[key]["verb_forms"][number] = pair["verb"]["form"]
    
    # Convert to list and filter out incomplete entries
    final_data = []
    for entry in game_data.values():
        if all(entry["subject_forms"].values()) and all(entry["verb_forms"].values()):
            final_data.append(entry)
    
    return final_data

if __name__ == "__main__":
    all_pairs = []
    for tense in ["present", "past", "future"]: 
        for verb in verbs:
            if not verb["requires_object"]:  # Only use verbs that don't require objects
                all_pairs.extend(generate_subject_verb_pairs(verb, tense))
    
    matching_game_data = create_matching_game_data(all_pairs)
    
    with open("matching_game.json", "w", encoding="utf-8") as f:
        json.dump(matching_game_data, f, ensure_ascii=False, indent=2)
    
    print(f"{len(matching_game_data)} matching game entries created and saved to 'matching_game.json'.")