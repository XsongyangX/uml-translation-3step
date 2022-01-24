"""
Extract features for one class
"""
from typing import Callable
from utils import uml
import spacy
from spacy.matcher import PhraseMatcher

# Helper class to get the uml result
class BuiltUML:

    def __init__(self, sentence: str) -> None:
        # load spacy
        self.nlp_model = spacy.load("en_core_web_sm")
        self.sentence = sentence
        self.spacy_doc = self.nlp_model(sentence)

        # Start parsing
        self.matcher = spacy.matcher.DependencyMatcher(self.nlp_model.vocab)

        # resulting UML
        self.uml_result: uml.UML = None

    def add_rule(self, pattern_name: str, pattern: list[list[dict]], matched_action: Callable[[dict, "BuiltUML"], uml.UML]):

        def store_uml_callback(matcher, doc, i, matches):

            _, token_ids = matches[i]

            current_semantics = BuiltUML.get_semantics(doc, token_ids, pattern[0])

            self.uml_result = matched_action(current_semantics, self)

        self.matcher.add(pattern_name, pattern, on_match=store_uml_callback)

    def parse(self, verbose: bool = True):
        matched_results = self.matcher(self.spacy_doc)
        
        if verbose:
            # Number of matches
            print(f"Matches: {len(matched_results)}")
        
        return self.uml_result

    def set_sentence(self, sentence: str):
        self.spacy_doc = self.nlp_model(sentence)

    def clear_rules(self):
        self.matcher = spacy.matcher.DependencyMatcher(self.nlp_model.vocab)

    def clear_result(self):
        self.uml_result = None

    @staticmethod
    def get_semantics(doc, token_ids, pattern):
        current_semantics = {}

        current_positions = {}

        for i in range(len(token_ids)):
            matched_token = doc[token_ids[i]].text
            matched_rule = pattern[i]["RIGHT_ID"]

            current_semantics[matched_rule] = matched_token

            current_positions[matched_token] = token_ids[i]

        current_semantics["positions"] = current_positions
        return current_semantics

# ------------------------------------------
# Class pattern

# copula: The ... is ...
copula_class = [
    # Pattern is: "The (subject) is a class ..."
    # Extracted info: A class with no attribute
    # anchor token: verb "to be"
    {"RIGHT_ID": "copula", "RIGHT_ATTRS": {"LEMMA": "be"}},
    # subject of the verb
    {
        "LEFT_ID": "copula",
        "REL_OP": ">",
        "RIGHT_ID": "subject",
        "RIGHT_ATTRS": {"DEP": "nsubj"},
    },
    # object of the verb
    {
        "LEFT_ID": "copula",
        "REL_OP": ">",
        "RIGHT_ID": "object",
        "RIGHT_ATTRS": {"DEP": "attr", "LEMMA": "class"},
    },
]

# Process a copula match
def process_copula_class(current_semantics: dict, build_in_progress: BuiltUML):

    eclass = uml.UMLClass(current_semantics["subject"].capitalize(), "class")

    package = uml.UML(eclass.name)
    package.classes.append(eclass)
    return package

# ----------------------------------------------

# Relationship pattern
relationship_pattern = [
    # Pattern is: A (noun for class A) has (numerical multiplicity) (noun for class B)
    # Extracted info: Class A has a relationship of a certain multiplicity with Class B
    # Procedure:
    # 1. use the dependency matcher for general syntax
    # 2. use the phrase matcher for multiplicities
    {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LEMMA": "have"}},
    {
        "LEFT_ID": "verb",
        "REL_OP": ">",
        "RIGHT_ID": "subject",
        "RIGHT_ATTRS": {"DEP": "nsubj"},
    },
    {
        "LEFT_ID": "verb",
        "REL_OP": ">",
        "RIGHT_ID": "object",
        "RIGHT_ATTRS": {"DEP": "dobj"},
    },
    {
        "LEFT_ID": "object",
        "REL_OP": ">",
        "RIGHT_ID": "number",
        "RIGHT_ATTRS": {"POS": "NUM"},
    },
]

# Multiplicity pattern
multiplicity_terms = [
    "0 or several",
    "one and only one",
    "one or more",
    "zero or more",
    "zero or one",
    "at least one",
]

def process_relationship_pattern(current_semantics: dict, build_in_progress: BuiltUML):
    
    # Get classes
    source = uml.UMLClass(current_semantics["subject"].capitalize(), "rel")
    destination = uml.UMLClass(current_semantics["object"].capitalize(), "rel")

    # Get multiplicity
    matcher = PhraseMatcher(build_in_progress.nlp_model.vocab)
    # Only run nlp.make_doc to speed things up
    patterns = [build_in_progress.nlp_model.make_doc(text) for text in multiplicity_terms]
    matcher.add("Multiplicities", patterns)

    # found multiplicity
    found_multiplicity = ""

    matches = matcher(build_in_progress.spacy_doc)
    for match_id, start, end in matches:
        span = build_in_progress.spacy_doc[start:end]
        
        # # This would trigger if there are many matches for the multiplicity term in the sentence
        # if start != current_semantics["positions"][build_in_progress.spacy_doc[start].text]:
        #     raise Exception("Index of multiplicity does not match with dependency parse results")

        found_multiplicity = span.text

        break

    # Build UML
    multiplicity_conversion = {
        "0 or several": "0..*",
        "one and only one": "1..1",
        "one or more": "1..*",
        "zero or more": "0..*",
        "zero or one": "0..1",
        "at least one": "1..*",
    }

    source.association(destination, multiplicity_conversion[found_multiplicity])

    package = uml.UML(source.name)
    package.classes.extend([source, destination])
    return package
