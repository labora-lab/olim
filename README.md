# OLIM
### Open Labeller for Iterative Machine learning

OLIM is a simple labelling interface aimed to be used by personal without data science specific knowledge. Currently OLIM supports the labelling of patients from medical texts relative to that patient. In future versions we expect to expand the possibilities of the data shape.

## Requirements

To run the Docker version you must have Docker Compose installed, the latest versions of Docker shoud have everything nedded.

To run the standalone version see `requirements.txt` for the needed Python packages and the elasticsearch documentation on how to install your own server.

## Instalation

>>> [!important] Configuring with Learner
If planing to use active learner pipeline and model training tasks, you will need to also install [OLIM Learner](https://gitlab.com/nanogennari/olim-learner). After configuring the Learner add the app-key in the `docker-compose.yml` on the `LEARNER_KEY` variable (line 31).

If the OLIM Learner and OLIM are running on docker on the same machine uncomment the `olim-learner_main` network on the `docker-compose.yml` (lines 40, 49 and 50).

**This shoud be done before step 3.**
>>>

>>> [!caution] Larger databases
If you are planing to upload larger database (>~100MB) you can copy (on remote machines use `scp`, `rsync` or similar tools) your data to the `data` and use the comand line interface to upload it (see the [`data`](./data) folder on details on how to format and upload it).

**This shoud be done before step 3.**
>>>

1. Clone the repository:

    `git clone https://gitlab.com/nanogennari/olim.git`

2. Enter the directory:

    `cd olim`

3. Build and start the containers:

    `docker compose up -d`

4. Wait for **two minutes** for the elasticsearch server to fully start.

5. Go to `http://localhost:42000` and do the initial configuration.

## Command line configuration

OLIM can also be initialized via command line, to do this run before accessing the interface:

`docker compose exec olim python -m flask --app olim init-db`

Info on how to upload data via command line is available on [`data`](./data).