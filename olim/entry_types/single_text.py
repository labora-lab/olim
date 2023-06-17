from ..functions import es_search, es_bulk_upload
from flask import render_template
import click
from tqdm import tqdm
from ..cli import upload

ES_INDEX = "single_text_entries"


def render(entry_id, **pars):
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX)["hits"]["hits"][0]

    return render_template("entry_types/single_text.html", res=res, **pars)


@click.command(
    "single_text",
    help="Upload data of the single_text type."
    "\n\n\tCSV_FILE\tPath to the CSV file to load data."
    "\n\n\tID_COLUMN\tColumn name to use as id for the entries (must be unique with all other entries in OLIM)."
    "\n\n\tTEXT_COLUMN\tColumn name to use as the text.",
)
@click.argument("csv_file", type=click.Path(exists=True))
@click.argument("id_column")
@click.argument("text_column")
def up_single_text(csv_file, id_column, text_column):
    mapping = {"properties": {"texts": {"type": "text"}}}

    def doc_generator(df, index, id_column, text_column):
        for _, row in tqdm(df.iterrows(), total=len(df)):
            data = {
                "_index": index,
                "_id": f"{row[id_column]}",
                "_source": {"text": row[text_column]},
            }
            for col in row.index:
                if col != text_column:
                    data["_source"][col] = row[col]
            yield data

    es_bulk_upload(
        csv_file,
        id_column,
        text_column,
        ES_INDEX,
        mapping,
        doc_generator,
        "single_text",
    )


upload.add_command(up_single_text)
