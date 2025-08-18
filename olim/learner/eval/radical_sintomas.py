import re
import pandas as pd


def rm_accent(text: str, pattern: str | list[str] = "all") -> str:
    if not isinstance(text, str):
        text = str(text)
    if isinstance(pattern, str):
        pattern = [pattern]
    pattern = list(set(pattern))
    if "Ç" in pattern:
        pattern[pattern.index("Ç")] = "ç"
    symbols = {
        "acute": "áéíóúÁÉÍÓÚýÝ",
        "grave": "àèìòùÀÈÌÒÙ",
        "circunflex": "âêîôûÂÊÎÔÛ",
        "tilde": "ãõÃÕñÑ",
        "umlaut": "äëïöüÄËÏÖÜÿ",
        "cedil": "çÇ",
    }
    nude_symbols = {
        "acute": "aeiouAEIOUyY",
        "grave": "aeiouAEIOU",
        "circunflex": "aeiouAEIOU",
        "tilde": "aoAOnN",
        "umlaut": "aeiouAEIOUy",
        "cedil": "cC",
    }
    accent_types = ["´", "`", "^", "~", "¨", "ç"]
    all_patterns = ["all", "al", "a", "todos", "t", "to", "tod", "todo"]
    if any(p in all_patterns for p in pattern):
        all_symbols = "".join(symbols.values())
        all_nude = "".join(nude_symbols.values())
        return text.translate(str.maketrans(all_symbols, all_nude))
    accent_map = {
        "´": ("acute", "acute"),
        "`": ("grave", "grave"),
        "^": ("circunflex", "circunflex"),
        "~": ("tilde", "tilde"),
        "¨": ("umlaut", "umlaut"),
        "ç": ("cedil", "cedil"),
    }
    for p in pattern:
        if p in accent_map:
            accent = accent_map[p]
            text = text.translate(
                str.maketrans(symbols[accent[0]], nude_symbols[accent[1]])
            )
    return text


sintomas = [
    "artralgia",
    "cefaleia",
    "dor abdominal",
    "dor articular",
    "dor atrás dos olhos",
    "dor de cabeça",
    "dor muscular",
    "dor retro-orbital",
    "eritema",
    "eritematosas",
    "febre",
    "febril",
    "hemorragia",
    "hemorrágica",
    "manifestações hemorrágicas",
    "mialgia",
    "petéquia",
    "retro-orbitária",
    "retroorbitária",
    "sangramento",
    "sufusão hemorrágica",
    "temperatura elevada",
    "choro",
    "dor no corpo",
    "plaqueta",
    "dengue",
    "plaquetopenia",
    "ocular",
]


def identificar_sintomas(texto: str) -> str | None:
    texto_upper = rm_accent(texto.upper())
    sintomas_upper = [rm_accent(s.upper()) for s in sintomas]
    pattern = "|".join(sintomas_upper)
    matches = re.findall(pattern, texto_upper)
    return ", ".join(matches) if matches else None


def process_data(df: pd.DataFrame) -> pd.DataFrame | None:
    df = df.copy()
    df["sintomas_identificados"] = df["sintomas_queixas"].apply(identificar_sintomas)
    df["sintomas_arboviroses"] = df["sintomas_identificados"].apply(
        lambda x: (
            ", ".join(re.findall(r"(\b\w+\b\,\s+)?\bFEBRE\b(\,\s+\b\w+\b)?", x))
            if x
            else None
        )
    )
    df["grafico"] = df["sintomas_arboviroses"]
    df["dengue"] = "0"
    df.loc[df["cod_cid"] == "A90", "dengue"] = "1"
    df["dengue"] = df["dengue"].astype("category")
    symptom_flags = {
        "mancha": ["EXANTEMA", "MANCHA[S] AV", "MANCHA[S] VER", "PETEQ"],
        "febre": [
            "FEBR",
            ("TAX", "37"),
            ("TAX", "38"),
            ("TAX", "39"),
            ("TAX", "40"),
            ("TAX", "41"),
        ],
        "dor_no_corpo_geral": ["DOR.*CORPO", "MIALGIA", "ARTRALGIA", "DORSALGIA"],
        "fadiga": ["FADIGA", "INDISPOSI"],
        "dor_retro_orbital": ["ORBITAL", ("DOR", "OLHO")],
        "vomito": ["VOMITO", "EMESE"],
        "dor_abdominal": [("DOR", "ABDOM")],
        "dispneia": ["FALTA DE AR", "DISPNEIA"],
        "vertigem": ["VERTIGEM"],
        "cefaleia": ["CEFALEIA", "DOR DE CABE"],
        "sangramento": ["SANG", "HEMO", "HEMA"],
        "nausea": ["NAUSEA", "ENJO"],
    }
    for col, patterns in symptom_flags.items():
        df[col] = "0"
        for pattern in patterns:
            if isinstance(pattern, tuple):
                mask = df["sintomas_c"].str.contains(pattern[0], na=False) & df[
                    "sintomas_c"
                ].str.contains(pattern[1], na=False)
            else:
                mask = df["sintomas_c"].str.contains(pattern, na=False)
            df.loc[mask, col] = "1"
    df["suspeita_arbo3"] = "0"
    df.loc[
        (df["febre"] == "1")
        & ((df["mancha"] == "1") | (df["dor_retro_orbital"] == "1")),
        "suspeita_arbo3",
    ] = "1"
    df["suspeita_arbo4"] = "0"
    df.loc[
        (df["febre"] == "1")
        & (
            (df["cefaleia"] == "1")
            | (df["fadiga"] == "1")
            | (df["dor_retro_orbital"] == "1")
            | (df["dor_no_corpo_geral"] == "1")
        ),
        "suspeita_arbo4",
    ] = "1"
    arbovirus_patterns = [
        ("FEBR", "DOR ARTICULAR"),
        ("FEBR", "ARTRALGIA"),
        ("FEBR", "MIALGIA"),
        ("FEBR", "MANCHA VER"),
        ("FEBR", "ORBITAL"),
        ("FEBR", "PETEQ"),
        ("FEBR", "DOR CORPO"),
        ("FEBR", "DOR CABECA"),
        ("FEBR", "CEFALEIA"),
        ("FEBR", "MANCHA AV"),
        ("FEBR", "PLAQUET"),
        ("FEBR", "FADIGA"),
        ("FEBR", "SANG"),
        ("FEBR", "CHORO"),
        ("FEBR", "CANSACO"),
        ("FEBR", "INDISPOS"),
        ("FEBR", "DOR OLHOS"),
        ("FEBR", "OCULAR"),
        ("FEBR", "EXANTEMA"),
        ("FEBR", "RETROORBITAL"),
        ("FEBR", "RETRO ORBITAL"),
        ("FEBR", "RETRO-ORBITAL"),
        "DENGUE",
        "PLAQUET",
    ]
    df["suspeita_arbo"] = "0"
    for pattern in arbovirus_patterns:
        if isinstance(pattern, tuple):
            mask = df["sintomas_c"].str.contains(pattern[0], na=False) & df[
                "sintomas_c"
            ].str.contains(pattern[1], na=False)
        else:
            mask = df["sintomas_c"].str.contains(pattern, na=False)
        df.loc[mask, "suspeita_arbo"] = "1"
    df["suspeita_arbo2"] = "0"
    for pattern in arbovirus_patterns[:23]:
        if isinstance(pattern, tuple):
            mask = df["sintomas_c"].str.contains(pattern[0], na=False) & df[
                "sintomas_c"
            ].str.contains(pattern[1], na=False)
        else:
            mask = df["sintomas_c"].str.contains(pattern, na=False)
        df.loc[mask, "suspeita_arbo2"] = "1"
    respiratory_cols = {
        "resp_sibilo": "SIBILO",
        "resp_tiragem": "TIRAGEM",
        "resp_subcostal": "SUB COSTAL",
        "resp_intercostal": "INTERCOSTAL",
        "resp_batimento_nasal": "BATIMENTO NASAL",
        "resp_cyanose": "CIANOSE",
        "resp_furcula": "FURCULA",
        "resp_saturacao": "BAIXA SATURACAO",
        "resp_tosse": "TOSSE",
    }
    for col, pattern in respiratory_cols.items():
        df[col] = df["sintomas_c"].str.contains(pattern, na=False).astype(int)
    df["resp_sintomas_bronquiolite"] = (
        df[list(respiratory_cols.keys())].sum(axis=1)
        + df["febre"].eq("1").astype(int)
        + df["dispneia"].eq("1").astype(int)
    )
    df["resp_sintomas_bronquiolite"] = df["resp_sintomas_bronquiolite"].apply(
        lambda x: "1" if x >= 3 else "0"
    )
    for col in respiratory_cols.keys():
        df[col] = df[col].astype(str)
    df["resp_sintomas_bronquiolite"] = df["resp_sintomas_bronquiolite"].astype(str)
    df["fx_etariaOPAS"] = df["fx_etariaOPAS"].fillna("NA").astype(str)
    df["idade_65"] = (df["idade"] > 65).astype(str)
    df["tempo_permanencia_7"] = "0"
    df.loc[df["tempo_permanencia"].between(7, 30), "tempo_permanencia_7"] = "1"
    df.loc[df["tempo_permanencia"] < 0, "tempo_permanencia_7"] = "0"
    df["resp"] = "0"
    resp_conditions = [
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & df["sintomas_c"].str.contains("GARGANTA", na=False)
            & (
                df["cefaleia"].eq("1")
                | df["sintomas_c"].str.contains(
                    "DOR ARTICULAR|MIALGIA|ARTRALGIA", na=False
                )
            )
        ),
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & df["sintomas_c"].str.contains("ODINOFAGIA", na=False)
            & (
                df["cefaleia"].eq("1")
                | df["sintomas_c"].str.contains(
                    "DOR ARTICULAR|MIALGIA|ARTRALGIA", na=False
                )
            )
        ),
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & df["sintomas_c"].str.contains("TOSSE", na=False)
            & df["sintomas_c"].str.contains("DOR ARTICULAR|MIALGIA|ARTRALGIA", na=False)
        ),
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & (df["idade"] < 2)
            & df["sintomas_c"].str.contains(
                "TOSSE|CORIZA|OBSTRUCAO NASAL|NARIZ ENTUPIDO", na=False
            )
        ),
    ]
    for condition in resp_conditions:
        df.loc[condition, "resp"] = "1"
    df["resp2"] = "0"
    resp2_conditions = [
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & df["sintomas_c"].str.contains("GARGANTA", na=False)
            & (
                df["cefaleia"].eq("1")
                | df["sintomas_c"].str.contains("MIALGIA", na=False)
            )
        ),
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & df["sintomas_c"].str.contains("ODINOFAGIA", na=False)
            & (
                df["cefaleia"].eq("1")
                | df["sintomas_c"].str.contains("MIALGIA", na=False)
            )
        ),
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & df["sintomas_c"].str.contains("TOSSE", na=False)
            & df["sintomas_c"].str.contains("MIALGIA", na=False)
        ),
        (
            df["sintomas_c"].str.contains("FEBR", na=False)
            & (df["idade"] < 2)
            & df["sintomas_c"].str.contains(
                "TOSSE|CORIZA|OBSTRUCAO NASAL|NARIZ ENTUPIDO", na=False
            )
        ),
    ]
    for condition in resp2_conditions:
        df.loc[condition, "resp2"] = "1"
    df["exantematica"] = "0"
    df.loc[
        (df["febre"].eq("1"))
        & (df["sintomas_c"].str.contains("EXANTEM", na=False))
        & (df["sintomas_c"].str.contains("TOSSE|CORIZA|CONJUNT", na=False)),
        "exantematica",
    ] = "1"
    df["neuro"] = "0"
    df.loc[
        (df["febre"].eq("1"))
        & (
            df["sintomas_c"].str.contains(
                "NERV|FOCAL|CONVUL|EPIL|CONFUS|MENTAL|IRRITA|VOMITOCEFALEIA INTENSA",
                na=False,
            )
        ),
        "neuro",
    ] = "1"
    df["sfi"] = "0"
    df.loc[
        (df["febre"].eq("1"))
        & (
            df["sintomas_c"].str.contains(
                "NERV|FOCAL|CONVUL|EPIL|CONFUS|MENTAL|IRRITA|VOMITO|CEFALEIA INTENSA",
                na=False,
            )
        ),
        "sfi",
    ] = "1"
    df["ict"] = "0"
    df.loc[
        (df["febre"].eq("1"))
        & (df["sintomas_c"].str.contains("ICTER|AMAREL", na=False)),
        "ict",
    ] = "1"
    df["diarreica"] = "0"
    df.loc[
        (df["sintomas_c"].str.contains("DIARR|DESENT|DIARREIA HEMORRAGICA", na=False))
        & (
            df["sintomas_c"].str.contains(
                "ICTER|AMAREL|INTERNA|ANTIBI|ATB|INSUFICIENCIA RENAL|IRA", na=False
            )
        ),
        "diarreica",
    ] = "1"
    return df


def get_radical_predictions(symptom_name: str, texts: list[str]) -> list[int]:
    """
    Get radical classification predictions for a specific symptom/syndrome.

    Args:
        symptom_name: Name of the symptom/syndrome to evaluate (e.g., 'febre', 'cefaleia')
        texts: list of medical texts to analyze

    Returns:
        list of predictions (0 or 1) for each text based on radical classification
    """
    # Create minimal DataFrame with required columns
    df = pd.DataFrame(
        {
            "sintomas_queixas": texts,
            "sintomas_c": texts,
            "cod_cid": [None] * len(texts),
            "idade": [30] * len(texts),
            "tempo_permanencia": [0] * len(texts),
            "fx_etariaOPAS": ["30-40"] * len(texts),
        }
    )

    # Process data using the radical classification system
    df_processed = process_data(df)

    if df_processed is None:
        raise ValueError("Failed to process data.")

    # Verify symptom exists in processed data
    if symptom_name not in df_processed.columns:
        raise ValueError(
            f"Symptom '{symptom_name}' not found in radical classification output. "
            f"Valid symptoms: {', '.join([col for col in df_processed.columns if col not in df.columns])}"
        )

    # Convert predictions to binary integers
    predictions = [1 if x == "1" else 0 for x in df_processed[symptom_name]]
    return predictions


def evaluate_symptom_performance(
    symptom_name: str, texts: list[str], model_predictions: list[int]
) -> dict:
    """
    Evaluate model performance against radical classification for a specific symptom/syndrome.

    Args:
        symptom_name: Symptom/syndrome name to evaluate
        texts: list of medical texts
        model_predictions: Model predictions (0 or 1) for each text

    Returns:
        Dictionary with:
        - 'accuracy': Percentage agreement between model and radical
        - 'model_positive_radical_failed': % of model positives missed by radical
        - 'radical_positive_model_failed': % of radical positives missed by model

    Raises:
        ValueError: If input lengths don't match
    """
    # Validate input lengths
    if len(texts) != len(model_predictions):
        raise ValueError("Texts and predictions must have the same length")

    # Get radical predictions
    radical_predictions = get_radical_predictions(symptom_name, texts)

    # Initialize counters
    n = len(texts)
    match_count = 0
    model_pos_radical_neg = 0
    model_neg_radical_pos = 0
    model_pos_count = 0
    radical_pos_count = 0

    # Compare predictions
    for model_pred, radical_pred in zip(model_predictions, radical_predictions):
        # Count matches
        if model_pred == radical_pred:
            match_count += 1

        # Count model positives
        if model_pred == 1:
            model_pos_count += 1
            if radical_pred == 0:
                model_pos_radical_neg += 1

        # Count radical positives
        if radical_pred == 1:
            radical_pos_count += 1
            if model_pred == 0:
                model_neg_radical_pos += 1

    # Calculate metrics
    accuracy = (match_count / n) * 100 if n > 0 else 0.0

    # Percentage of model positives that radical missed
    model_pos_radical_failed = (
        (model_pos_radical_neg / model_pos_count * 100) if model_pos_count > 0 else 0.0
    )

    # Percentage of radical positives that model missed
    radical_pos_model_failed = (
        (model_neg_radical_pos / radical_pos_count * 100)
        if radical_pos_count > 0
        else 0.0
    )

    return {
        "accuracy": accuracy,
        "model_positive_radical_failed": model_pos_radical_failed,
        "radical_positive_model_failed": radical_pos_model_failed,
    }
