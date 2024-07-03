# Put your data here

### ATENTION: The data file must be created before the running `docker compose up`!!!

# Types of data

### Simple text entries

Simply create a `data.csv` file with a column with the texts ids and a column with the texts, after the containets have started and the database is initialized run the folowing to upload your data:

`docker compose exec olim python -m flask --app olim upload single_text data/data.csv [text_id_column] [text_column]`

All other columns in the csv will be loaded as metadata for each entry.

### Patient sheets entries

Create a `data.csv` file with the following columns:

- patient_id
- text_id
- visitation_id
- text
- text_type
- date (in ISO format)

And after the containers start and the database is initialized, run the following command to upload your data to the elasticsearch server:

`docker compose exec olim python -m flask --app olim upload patient data/data.csv`
