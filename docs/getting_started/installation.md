# Installation

OLIM can be installed and launched using Docker in just a few steps.  
This guide will walk you through the basic setup and highlight optional configurations depending on your use case.


!!! info "Using OLIM with Learner"
    If you plan to use the **active learning pipeline** and model training tasks, you will also need to install [OLIM Learner](https://gitlab.com/nanogennari/olim-learner).

    After configuring OLIM Learner:
    
    - Add the app key to the `LEARNER_KEY` variable in your `docker-compose.yml` file (**line 31**).
    - If both OLIM and OLIM Learner are running on Docker on the same machine, **uncomment** the `olim-learner_main` network on **lines 40, 49, and 50** of the same file.

    ⚠️ **This must be done before Step 3 below.**


!!! warning "Handling large datasets (>100MB)"
    If you plan to upload a **large database**, it's recommended to place your data directly in the `data/` folder before startup.

    On remote machines, you can use tools like `scp` or `rsync` to copy the files.

    For more details on formatting and uploading the data, see the [`data`](https://gitlab.com/nanogennari/olim/-/tree/main/data) folder in the repository.

    ⚠️ **This should also be done before Step 3.**


## 🚀 Basic Installation

1. **Clone the repository**  
    ```bash
    git clone https://gitlab.com/nanogennari/olim.git
    ```

2.	**Enter the project directory**
    ```bash
    cd olim
    ```

3.	**Build and start the Docker containers**
    ```bash
    docker compose up -d
    ```

4.	**Wait for Elasticsearch to fully initialize**
    Please allow up to **2 minutes** for all services to be ready.

5.	**Access the OLIM interface**
    Open your browser and go to: [http://localhost:42000](http://localhost:42000).

---

⚙️ Command-Line Configuration (Optional)

If you prefer to initialize OLIM via the command line before opening the interface:

```bash
docker compose exec olim python -m flask --app olim init-db
```

For information on how to upload data via the command line, refer to the [Data Formatting Tutorial](../tutorials/data_formatting.md).

---