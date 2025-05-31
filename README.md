# OLIM
### Open Labeller for Iterative Machine learning

OLIM is a simple labelling interface aimed to be used by personal without data science specific knowledge. Currently OLIM supports the labelling of patients from medical texts relative to that patient. In future versions we expect to expand the possibilities of the data shape.


## Instalation


1. Clone the repository:

    `git clone https://gitlab.com/nanogennari/olim.git`

2. Enter the directory:

    `cd olim`

3. Build and start the containers:

    `docker compose up -d`

4. Wait for **two minutes** for the elasticsearch server to fully start.

5. Go to `http://localhost:42000` and do the initial configuration.
