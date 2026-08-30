import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
VECTOR_DB_PATH = str(BASE_DIR / "chroma_db")
DATA_DIR = BASE_DIR / "data"
RESUMES_DIR = str(DATA_DIR / "resumes")
JOB_DESCRIPTIONS_DIR = str(DATA_DIR / "job_descriptions")

# Embedding Config
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
TOP_K = 10
