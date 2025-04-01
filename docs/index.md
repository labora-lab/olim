# OLIM
### Open Labeller for Iterative Machine learning

OLIM is a simple labelling interface aimed to be used by personal without data science specific knowledge. Currently OLIM supports the labelling of patients from medical texts relative to that patient. In future versions we expect to expand the possibilities of the data shape.

## Requirements

To run the Docker version you must have Docker Compose installed, the latest versions of Docker shoud have everything nedded.

To run the standalone version see `requirements.txt` for the needed Python packages and the elasticsearch documentation on how to install your own server.

## Instalation

1. Clone the repository:

    `git clone https://gitlab.com/nanogennari/olim.git`

2. Enter the directory:

    `cd olim`

3. Copy your data to the `data/data.csv` (see the [`data`](./data) folder on details on how to format it)

4. Build and start the containers:

    `docker compose up -d`

5. Wait for two minutes for the elasticsearch server to fully start.

6. Initialize OLIM database:

    `docker compose exec olim python -m flask --app olim init-db`

7. Upload your data:

    * Simple text data:

        `docker compose exec olim python -m flask --app olim upload single_text data/data.csv [text_id_column] [text_column]`

    * Patient sheet data:

        `docker compose exec olim python -m flask --app olim upload patient data/data.csv`

    If you want to use the sample data run instead:



    * Simple text data:

        `docker compose exec olim python -m flask --app olim upload single_text /app/data/sample_data.csv text_id text`

    * Patient sheet data:

        `docker compose exec olim python -m flask --app olim upload patient /app/data/sample_data.csv`

8. Access the labeler on `http://localhost:42000`

