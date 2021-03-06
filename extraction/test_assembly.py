import pickle
import re
import shutil
import subprocess
from .utils import inquire, uml
from . import assemble
from .parse import LazyLoadedExtractor

import os, pandas

# Initialize the test suite
CURRENT_SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
ZOO_DIR = "C:\\Users\\songy\\Documents\\My Documents\\UDEM\\master thesis\\uml data\\database\\analysis\\zoo\\"
SOURCE_DIR = "C:\\Users\\songy\\Documents\\My Documents\\UDEM\\master thesis\\uml data\\database\\analysis\\"

TEMP_FOLDER = os.path.join(CURRENT_SCRIPT_DIR, "temp")
os.makedirs(TEMP_FOLDER, exist_ok=True)

LABELS = pandas.read_csv(os.path.join(SOURCE_DIR, "labels.csv"))
FRAGMENTS = pandas.read_csv(os.path.join(SOURCE_DIR, "fragments.csv"))

PICKLED_DIR = os.path.join(TEMP_FOLDER, "pickled")
os.makedirs(PICKLED_DIR, exist_ok=True)
PREPROCESSED_PICKLED_DIR = os.path.join(PICKLED_DIR, "preprocessed")
os.makedirs(PREPROCESSED_PICKLED_DIR, exist_ok=True)

PLANTUML_PARSER = os.path.join(
    SOURCE_DIR, "three-step", "extraction", "plantuml-parser.js"
)


def test_assembly_ground_truth(selective: str = ""):
    """
    Checks the assembly algorithm using the dataset's original fragments and models.

    The fragments are ground truth. The models are ground truth.
    """

    # Read the ground truth fragments from the dataset

    # Group the fragments according to their models
    models: dict[str, uml.UML] = {}
    grouped: dict[str, list[uml.UML]] = {}

    for index, row in LABELS.iterrows():

        fragment = FRAGMENTS.loc[FRAGMENTS["unique_id"] == row["fragment_id"]]

        # get the model's uml
        model_name = fragment["model"].values[0]

        # selective runs
        if selective != "" and model_name != selective:
            continue

        model = inquire.get_json_uml(os.path.join(ZOO_DIR, model_name + ".json"))
        models[model_name] = model

        # get the fragment's uml
        label_id: str = row["id"]
        # WATCH OUT FOR ECORE OR JSON
        fragment_uml = inquire.get_json_uml_fragment(int(label_id))
        if model_name in grouped:
            grouped[model_name].append(fragment_uml)
        else:
            grouped[model_name] = [fragment_uml]

    # Apply the algorithm to groups of fragments
    assembled_models: dict[str, uml.UML] = {}
    for model_name, fragments in grouped.items():
        # selective runs
        if selective != "" and selective != model_name:
            continue
        assembled = assemble.assemble(fragments=fragments)
        assembled_models[model_name] = assembled

    # Compare the results with the ground truth model
    passed = 0
    passed_models = []
    failed = 0
    failed_models = []

    passed_predictions: list[uml.UML] = []
    failed_predictions: list[uml.UML] = []

    # print predictions and ground truths
    results_folder = os.path.join(TEMP_FOLDER, "assembly")
    os.makedirs(results_folder, exist_ok=True)
    shutil.rmtree(results_folder)
    os.makedirs(results_folder, exist_ok=True)

    # if len(assembled_models) != len(models):
    #     raise Exception("There are different amounts of assembled models than models.")

    for predicted, ground_truth in zip(assembled_models.items(), models.items()):
        model_name, prediction = predicted
        _, original = ground_truth

        if prediction == original:
            passed += 1
            passed_models.append(model_name)
            passed_predictions.append(prediction)

            prediction.save(
                os.path.join(results_folder, model_name + "_prediction_passed.plantuml")
            )
            original.save(
                os.path.join(results_folder, model_name + "_original_passed.plantuml")
            )
        else:
            failed += 1
            failed_models.append(model_name)
            failed_predictions.append(prediction)

            prediction.save(
                os.path.join(results_folder, model_name + "_prediction_failed.plantuml")
            )
            original.save(
                os.path.join(results_folder, model_name + "_original_failed.plantuml")
            )

    print("Passed", passed)
    print("Failed", failed)

    # More detailed metrics for the predictions and the models
    passed_model_class_counts = [len(model.classes) for model in passed_predictions]
    failed_model_class_counts = [len(model.classes) for model in failed_predictions]

    original_model_class_counts = []
    for prediction in failed_models:
        original_model_class_counts.append(len(models[prediction].classes))

    passed_dataframe = pandas.DataFrame(
        data={"model": passed_models, "class count": passed_model_class_counts}
    )
    failed_dataframe = pandas.DataFrame(
        data={
            "model": failed_models,
            "class count": failed_model_class_counts,
            "original class count": original_model_class_counts,
        }
    )

    passed_dataframe.to_csv(os.path.join(TEMP_FOLDER, "assembly_ground_passed.csv"))
    failed_dataframe.to_csv(os.path.join(TEMP_FOLDER, "assembly_ground_failed.csv"))


def run_nlp_pipeline():
    """
    Runs the NLP pipeline on classified labels to generate prediction fragments
    Save results to disk
    """
    classified_fragments_path = os.path.join(
        SOURCE_DIR, "three-step", "data", "fragment_kinds.csv"
    )
    classified_fragments = pandas.read_csv(
        classified_fragments_path, header=0, index_col=0
    )

    class_extractor = LazyLoadedExtractor("", "class")
    rel_extractor = LazyLoadedExtractor("", "rel")

    for index, row in classified_fragments.iterrows():
        if row["kind"] == "class":
            class_extractor.extractor.set_sentence(row["english"])
            result = class_extractor.handle_class(verbose=False)
        elif row["kind"] == "rel":
            rel_extractor.extractor.set_sentence(row["english"])
            result = rel_extractor.handle_rel(verbose=False)
        else:
            raise Exception("Unexpected kind!")

        if result is not None:
            # get the name of this fragment
            ground_truth_fragment_name = inquire.get_uml_fragment_name(index)
            # pickle the uml under this name
            with open(
                os.path.join(PICKLED_DIR, ground_truth_fragment_name), "wb+"
            ) as pickled_file:
                pickle.dump(result, pickled_file)


def run_nlp_pipeline_preprocessed():
    from preprocess import resolve_coref, LazyLoadedClassifier

    classified_fragments_path = os.path.join(
        SOURCE_DIR, "three-step", "data", "grouped.csv"
    )
    classified_fragments = pandas.read_csv(
        classified_fragments_path, header=0, index_col=0
    )

    class_extractor = LazyLoadedExtractor("", "class")
    rel_extractor = LazyLoadedExtractor("", "rel")
    classifier = LazyLoadedClassifier()

    for row_index, row in classified_fragments.iterrows():
        model_name = row["model"]

        # call preprocessor
        split_sentences = resolve_coref(row["text"])

        for index, sentence in split_sentences.items():

            # call classifier
            kind = classifier.predict(text=sentence)
            if kind == "class":
                class_extractor.extractor.set_sentence(sentence)
                result = class_extractor.handle_class(verbose=False)
            elif kind == "rel":
                rel_extractor.extractor.set_sentence(sentence)
                result = rel_extractor.handle_rel(verbose=False)
            else:
                raise Exception("Unexpected kind!")

            # save the result to disk
            if result is not None:
                # get the name of this fragment
                ground_truth_fragment_name = f"{model_name}_{kind}{index}"
                # pickle the uml under this name
                with open(
                    os.path.join(PREPROCESSED_PICKLED_DIR, ground_truth_fragment_name),
                    "wb+",
                ) as pickled_file:
                    pickle.dump(result, pickled_file)


def test_assembly(used_preprocessed: bool = False):
    """
    Tests the assembly on the fragments generated by the pipeline.

    Two choices. Raw fragments or preprocessed fragments.
    """

    # Use the NLP pipeline and save intermediary results to disk

    # Read raw fragments from the fragment_kinds.csv
    if not used_preprocessed:
        if len(os.listdir(PICKLED_DIR)) == 0:
            run_nlp_pipeline()

        grouped = read_pickles(PICKLED_DIR)

    # Read preprocessed fragments from the split.csv
    else:
        if len(os.listdir(PREPROCESSED_PICKLED_DIR)) == 0:
            run_nlp_pipeline_preprocessed()
        grouped = read_pickles(PREPROCESSED_PICKLED_DIR)

    results = {}

    for model_name, fragments in grouped.items():
        if model_name == "AntScripts":
            continue
        results[model_name] = assemble.assemble(fragments)

    # metric
    passed = 0
    passed_predictions: list[uml.UML] = []
    passed_models: list[uml.UML] = []
    failed = 0
    failed_predictions: list[uml.UML] = []
    failed_models: list[uml.UML] = []

    # Compare the assembled result with ground truth, version "zoo plantuml"
    # This depends on the plantuml parser
    for model_name, assembled in results.items():
        json_file = os.path.join(ZOO_DIR, model_name + ".json")
        if not os.path.isfile(json_file):
            # parse the plantuml with the node package
            exit_code = subprocess.call(
                args=[
                    "node",
                    PLANTUML_PARSER,
                    json_file.removesuffix(".json") + ".plantuml",
                ]
            )

            if exit_code != 0:
                raise Warning("Did not generate json properly: {}", json_file)

        ground_truth = inquire.get_json_uml(json_file)

        if assembled == ground_truth:
            # correct
            passed += 1
            passed_models.append(ground_truth)
            passed_predictions.append(assembled)
        else:
            # incorrect
            failed += 1
            failed_models.append(ground_truth)
            failed_predictions.append(assembled)

    print("Passed", passed)
    print("Failed", failed)

    # More detailed metrics for the predictions and the models
    passed_model_class_counts = [len(model.classes) for model in passed_predictions]
    failed_model_class_counts = [len(model.classes) for model in failed_predictions]

    original_model_class_counts = []
    for prediction, ground_truth in zip(failed_predictions, failed_models):
        original_model_class_counts.append(len(ground_truth.classes))

    passed_dataframe = pandas.DataFrame(
        data={
            "model": [m.package_name for m in passed_models],
            "class count": passed_model_class_counts,
        }
    )
    failed_dataframe = pandas.DataFrame(
        data={
            "model": [m.package_name for m in failed_models],
            "class count": failed_model_class_counts,
            "original class count": original_model_class_counts,
        }
    )

    passed_dataframe.to_csv(os.path.join(TEMP_FOLDER, "assembly_passed.csv"))
    failed_dataframe.to_csv(os.path.join(TEMP_FOLDER, "assembly_failed.csv"))


def read_pickles(location: str):
    grouped = {}  # model name, list of fragments

    for pickled_path in os.listdir(location):
        potential_file = os.path.join(location, pickled_path)
        if not os.path.isfile(potential_file):
            continue
        with open(potential_file, "rb") as pickled_file:
            pickled: uml.UML = pickle.load(pickled_file)

        model_name = re.split("_(class|rel)\d+", pickled_path)[0]

        if model_name in grouped:
            grouped[model_name].append(pickled)
        else:
            grouped[model_name] = [pickled]
    return grouped


def test_assembly_ground_truth_plantuml(selective: str = ""):
    """
    Tests the program on the ground truth but with the new plantuml fragmentation
    """
    fragments_folder = os.path.join(
        SOURCE_DIR, "three-step", "data", "fragmented_again"
    )
    grouped = pandas.read_csv(
        os.path.join(SOURCE_DIR, "three-step", "data", "grouped.csv")
    )

    results = {}

    for index, row in grouped.iterrows():
        model_name = row["model"]

        if model_name == "AntScripts":
            continue

        if selective != "" and model_name != selective:
            continue

        fragments = [
            os.path.join(fragments_folder, f)
            for f in os.listdir(fragments_folder)
            if f.startswith(model_name) and f.endswith(".plantuml")
        ]

        # create json if it doesn't exist
        for fragment in fragments:
            if not os.path.isfile(fragment.removesuffix(".plantuml") + ".json"):
                exit_code = subprocess.call(args=["node", PLANTUML_PARSER, fragment])
                if exit_code != 0:
                    raise Warning("Did not generate json properly: {}", json_file)

        results[model_name] = assemble.assemble(
            [
                inquire.get_json_uml_fragment(f.removesuffix(".plantuml") + ".json")
                for f in fragments
            ]
        )

    # metric
    passed = 0
    passed_predictions: list[uml.UML] = []
    passed_models: list[uml.UML] = []
    failed = 0
    failed_predictions: list[uml.UML] = []
    failed_models: list[uml.UML] = []

    # Compare the assembled result with ground truth, version "zoo plantuml"
    # This depends on the plantuml parser
    for model_name, assembled in results.items():
        json_file = os.path.join(ZOO_DIR, model_name + ".json")
        if not os.path.isfile(json_file):
            # parse the plantuml with the node package
            exit_code = subprocess.call(
                args=[
                    "node",
                    PLANTUML_PARSER,
                    json_file.removesuffix(".json") + ".plantuml",
                ]
            )

            if exit_code != 0:
                raise Warning("Did not generate json properly: {}", json_file)

        ground_truth = inquire.get_json_uml(json_file)

        if assembled == ground_truth:
            # correct
            passed += 1
            passed_models.append(ground_truth)
            passed_predictions.append(assembled)
        else:
            # incorrect
            failed += 1
            failed_models.append(ground_truth)
            failed_predictions.append(assembled)

    print("Passed", passed)
    print("Failed", failed)

    # More detailed metrics for the predictions and the models
    passed_model_class_counts = [len(model.classes) for model in passed_predictions]
    failed_model_class_counts = [len(model.classes) for model in failed_predictions]

    original_model_class_counts = []
    for prediction, ground_truth in zip(failed_predictions, failed_models):
        original_model_class_counts.append(len(ground_truth.classes))

    passed_dataframe = pandas.DataFrame(
        data={
            "model": [m.package_name for m in passed_models],
            "class count": passed_model_class_counts,
        }
    )
    failed_dataframe = pandas.DataFrame(
        data={
            "model": [m.package_name for m in failed_models],
            "class count": failed_model_class_counts,
            "original class count": original_model_class_counts,
        }
    )

    passed_dataframe.to_csv(
        os.path.join(TEMP_FOLDER, "assembly_ground_plantuml_passed.csv")
    )
    failed_dataframe.to_csv(
        os.path.join(TEMP_FOLDER, "assembly_ground_plantuml_failed.csv")
    )


if __name__ == "__main__":
    # test_assembly(used_preprocessed=True)
    test_assembly_ground_truth_plantuml(selective="CFG")
