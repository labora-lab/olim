# Welcome to OLIM!

OLIM (Open Labeller for Iterative Machine learning) is a user-friendly labeling interface designed for individuals **without prior data science knowledge**.  
Its primary use case is to assist in **labeling patient-related data** extracted from medical texts. Future versions aim to support a wider range of data formats and domains.

## 🚀 What Can OLIM Do?

- Easily label text data related to patients.
- Designed for medical professionals and annotators.
- Offers an **iterative machine learning** workflow to improve label efficiency over time.

## 🛠 Requirements

!!! tip "Choose your installation method"
    You can run OLIM using Docker or as a standalone Python application.

### 📦 Docker Version

To use OLIM with Docker:

- Make sure you have **Docker Compose** installed.  
  Most recent Docker distributions already include it.

!!! note
    For most users, the Docker version is the simplest way to get started.

### 🐍 Standalone Python Version

If you prefer to run OLIM outside Docker:

- Check the `requirements.txt` file for the necessary Python packages.
- You'll also need to install and configure your own **Elasticsearch server**.  
  See the [Elasticsearch documentation](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html) for help.

## 📚 Next Steps

If you’re ready to get started:

👉 Head over to the [Getting Started](getting_started/installation.md) section to begin your installation.