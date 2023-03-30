ES_MAPPINGS = {
    "ID_PATIENT": "id_paciente",
    "DATE": "data",
    "TEXT_CONTENT": "texto",
    "TEXT_ID": "id_texto",
    "TEXT_TYPE": "tipo_texto",
    "VISITATION_ID": "id_atendimento",
    "HIDDEN_ENTRY": "hidden",
}
"""Mapping of the elastic serach fields names"""

ES_INDEX = "patients-texts"
"""Elasticserach index to load patient data"""

ES_SERVER_FILE = "server_credentials.json"
"""Elasticsearch server credentials file"""

CALENDAR_LANGUAGE = {
    "months": [
        "Janeiro",
        "Fevereiro",
        "Março",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro",
    ],
    "monthsShort": [
        "Jan",
        "Fev",
        "Mar",
        "Abr",
        "Mai",
        "Jun",
        "Jul",
        "Ago",
        "Set",
        "Out",
        "Nov",
        "Dez",
    ],
    "weekdays": ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sabado"],
    "weekdaysShort": ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"],
    "weekdaysAbbrev": ["D", "S", "T", "Q", "Q", "S", "S"],
    "cancel": "Cancelar",
    "clear": "Limpar",
}

YEAR_RANGE = "[2019, 2023]"
