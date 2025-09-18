# Data Formatting

!!! warning
    This information is out of date!

OLIM supports two types of structured data: **simple text entries** and **patient sheet entries**.  
This page explains how to format your dataset and upload it properly.


!!! warning "Important"
    Your data file must be created **before** running `docker compose up`.


## 📝 Supported Data Types

1. Simple Text Entries

    For basic use cases where each row represents an individual text:

    - Create a file named `data.csv`
    - Include at least two columns:
    - One for **text IDs**
    - One for the **text content** itself

    📤 **To upload your data**, once the containers are running and the database has been initialized, use the following command:

    ```bash
    docker compose exec olim python -m flask --app olim upload single_text data/data.csv [text_id_column] [text_column]
    ```

    ✅ All **additional columns** will be stored as metadata for each entry.

2. Patient Sheet Entries

    For more complex medical use cases where entries are associated with patients and visits:

    Create a `data.csv` file with the following required columns:

    - `patient_id`
    - `text_id`
    - `visitation_id`
    - `text`
    - `text_type`
    - `date` (must be in **ISO format**, e.g., `2024-06-15T14:30:00Z`)

    📤 **To upload your data**, after the containers are running and the database is initialized, run:

    ```bash
    docker compose exec olim python -m flask --app olim upload patient data/data.csv
    ```

    Each row will be stored with its associated patient and visit metadata.

---

Need help formatting your CSV or not sure which format suits your use case?  
Feel free to reach out or check example files in the [`data/`](https://gitlab.com/nanogennari/olim/-/tree/main/data) folder of the repository.

---