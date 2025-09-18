<img src="olim/static/olim.svg" alt="OLIM Logo" align="left" height="100" hspace="30" />

# OLIM
### Open Labeller for Iterative Machine learning

OLIM is a simple labelling interface aimed to be used by personal without data science specific knowledge. Currently OLIM supports the labelling of patients from medical texts relative to that patient. In future versions we expect to expand the possibilities of the data shape.


## Installation

1. Clone the repository:

    `git clone https://gitlab.com/nanogennari/olim.git`

2. Enter the directory:

    `cd olim`

3. Configure environment:

    `cp .env.template .env`

    Edit `.env` file according to your needs.

4. Build and start the containers:

    `docker compose up -d`

5. Go to `http://localhost:42000` and complete the initial setup via the web interface.

## Distributed Workers Deployment

For scalable deployments, you can separate workers (previously called learner) from the main application. **Important: Start workers first, then the main application.**

### Step 0: Common Configuration

Generate a common `.env` file as in the normal setup above. Use this as the base configuration for both main server and worker machines.

### Step 1: Configure and Start Workers First

On workers machine, edit `.env` to change only these variables from the common configuration:
```bash
# Worker-specific changes to .env:
DB_HOST=192.168.1.100  # IP of main server
ES_SERVER=http://192.168.1.100:9200  # Elasticsearch on main server
```

Start workers:
```bash
# On worker machines (start these FIRST)
docker-compose -f docker-compose.workers-only.yml up -d
```

### Step 2: Configure and Start Main Application

On main server, edit `.env` to change only this variable from the common configuration:
```bash
# Main server-specific changes to .env:
REDIS_HOST=192.168.1.200  # IP of worker machine
```

Start main application:
```bash
# On main server (start AFTER workers are running)
docker-compose -f docker-compose.remote-workers.yml up -d
```