## Put your data here

### ATENTION: The data file must be created before the running `docker compose up`!!!

Create a `data.csv` file with the following columns:

- patient_id
- text_id
- visitation_id
- text
- date (in ISO format)

And after the containers start, run the following command to upload your data to the elasticsearch server:

`docker compose exec rotulador python /app/upload_data.py /app/data/data.csv`

There is also an `sample_data.csv` to upload it to the elasticsearch server run instead:

`docker compose exec rotulador python /app/upload_data.py /app/data/sample_data.csv`
