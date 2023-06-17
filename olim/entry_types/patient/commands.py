from...functions import get_es_conn, es_update, now_ISO
from . import ES_INDEX, ES_TO_HIDE_INDEX

def update_hidden(txt_id, entry_id, hide):
    body = {
        "script": {
            "source": "def targets = ctx._source.texts.findAll(texts -> texts.text_id == params.text_id); for(text in targets) { text.is_hidden = params.is_hidden }",
            "params": {"text_id": txt_id, "is_hidden": hide},
        }
    }

    return es_update(id=entry_id, body=body, refresh=True, index=ES_INDEX)


def remove_from_hidden(text_id):
    client = get_es_conn()
    query = {"query": {"bool": {"must": [{"match": {"text_id": text_id}}]}}}
    return client.delete_by_query(index=ES_TO_HIDE_INDEX, body=query, refresh=True)


def add_text_to_hide(text, text_id, entry_id):
    label_doc = {
        "text": text,
        "text_id": text_id,
        "entry_id": entry_id,
        "date": now_ISO(),
    }

    client = get_es_conn()
    return client.index(index=ES_TO_HIDE_INDEX, document=label_doc)


def hide_one(**args):
    txt_id = args.get("txt_id", None)
    entry_id = int(args.get("entry_id", None))

    try:
        update_hidden(txt_id, entry_id, True)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if txt_id == None:
        return {
            "type": "error",
            "text": "No ID passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Ocultado texto {txt_id}",
        }


def show(**args):
    txt_id = args.get("txt_id", None)
    entry_id = int(args.get("entry_id", None))

    try:
        update_hidden(txt_id, entry_id, False)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if txt_id == None:
        return {
            "type": "error",
            "text": "No ID passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Desocultado texto {txt_id}",
        }


def hide_all(**args):
    entry_id = args.get("entry_id", None)
    text = args.get("text", None)
    text_id = args.get("text_id", None)

    try:
        add_text_to_hide(text, text_id, entry_id)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if entry_id == None or text == None or text_id == None:
        return {
            "type": "error",
            "text": f"Missing data: {entry_id}, {text_id}, {text}",
        }
    else:
        return {
            "type": "OK",
            "text": f"Sempre esconderá texto {text}",
        }


def remove_hidden(**args):
    text_id = args.get("text_id", None)

    try:
        remove_from_hidden(text_id)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if text_id == None:
        return {
            "type": "error",
            "text": "Missing data: text_id",
        }
    else:
        return {
            "type": "OK",
            "text": f"Texto {text_id} removido da lista de escondidos",
        }


COMMANDS = {
    "hide-one": hide_one,
    "hide-all": hide_all,
    "show": show,
    "remove-hidden": remove_hidden,
}