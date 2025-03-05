from collections.abc import Generator

import click
import pandas as pd
from tqdm import tqdm

from ...cli import upload
from ...upload_utils import es_bulk_upload
from . import ENTRY_TYPE, ES_INDEX, ES_TO_HIDE_INDEX

extra_fields_mapping = {
    "type": "nested",
    "properties": {
        "name": {"type": "text"},
        "value": {"type": "text"},
        "type": {"type": "text"},
        "date": {"type": "date"},
    },
}


patients_mapping = {
    "properties": {
        "texts": {
            "type": "nested",
            "properties": {
                "date": {"type": "date"},
                "text": {"type": "text"},
                "text_id": {"type": "text"},
                "text_type": {"type": "text"},
                "visitation_id": {"type": "text"},
                "is_hidden": {"type": "boolean"},
                "extra_fields": extra_fields_mapping,
            },
        },
        "extra_fields": extra_fields_mapping,
    }
}


to_hide_mapping = {
    "properties": {
        "date": {"type": "date"},
        "text": {"type": "text"},
        "text_id": {"type": "text"},
        "patient_id": {"type": "text"},
    }
}


@click.command(
    ENTRY_TYPE,
    help="Upload data of the patient type.\n\n\tCSV_FILE\tPath to the CSV file to load data.",
)
@click.argument("csv_file", type=click.Path(exists=True))
def up_patients(csv_file: str) -> None:
    """Uploads patient data from a CSV file.

    Args:
        csv_file (str): Path to csv file.
    """

    def get_texts(df_a) -> list[dict]:
        def parse_row(row) -> dict:
            if "visitation_id" in row:
                if row["visitation_id"] == "nan":
                    del row["visitation_id"]
                else:
                    row["visitation_id"] = str(int(row["visitation_id"]))
            row["is_hidden"] = False
            row["date"] = row["date"].isoformat()
            row["labels"] = []
            return row

        df_a["date"] = pd.to_datetime(df_a["date"])
        return [parse_row(row.dropna().to_dict()) for _, row in df_a.iterrows()]

    def doc_generator(df, *_) -> Generator[dict, None, None]:
        for pid, sub_df in tqdm(df.groupby("patient_id")):
            yield {
                "_index": ES_INDEX,
                "_id": f"{pid}",
                "_source": {
                    "texts": get_texts(sub_df),
                    "labels": [],
                },
            }

    es_bulk_upload(
        csv_file,
        "patient_id",
        None,
        ES_INDEX,
        patients_mapping,
        doc_generator,
        ENTRY_TYPE,
        additional_indexes=[(ES_TO_HIDE_INDEX, to_hide_mapping)],
    )


upload.add_command(up_patients)
