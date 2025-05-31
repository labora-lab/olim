import os

CLASSIFICATION_MODEL = os.getenv("CLASSIFICATION_MODEL", "TfidfXGBoostClassifier")

assert CLASSIFICATION_MODEL in ["TfidfXGBoostClassifier", "DebertaV3Wrapper"]

SKIP_AL = False #bool(os.getenv("SKIP_AL", "False"))

assert type(SKIP_AL) is bool

UNCERTAIN_PERC = float(os.getenv("UNCERTAIN_PERC", "0.7"))

assert 0 <= UNCERTAIN_PERC <= 1
