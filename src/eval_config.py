# Evaluation Ground Truth and Embedding Benchmark configurations

GROUND_TRUTH = {
    "jd_python_ml.txt": ["Alex Kumar", "Victor Stone", "Sarah Connor"],
    "jd_java_spring.txt": ["Rahul Mehta"],
    "jd_devops_cloud.txt": ["Michael Lee", "David Bowman", "Hal Jordan", "Sam Wilson", "Bruce Wayne"],
    "jd_frontend_react.txt": ["Jane Doe", "Clint Barton", "Marcus Wright"],
    "jd_fullstack_go.txt": ["Barry Allen"]
}

BENCHMARK_DATA = [
    {
        "Model Name": "text-embedding-3-small",
        "Provider": "OpenAI (Paid API)",
        "Dimension": 1536,
        "Cost per 1M Tokens": "$0.02",
        "MTEB Retrieval Avg": 52.2,
        "Deployment Type": "API-based",
        "License": "Proprietary"
    },
    {
        "Model Name": "text-embedding-ada-002",
        "Provider": "OpenAI (Paid API)",
        "Dimension": 1536,
        "Cost per 1M Tokens": "$0.10",
        "MTEB Retrieval Avg": 49.3,
        "Deployment Type": "API-based",
        "License": "Proprietary"
    },
    {
        "Model Name": "embed-english-v3.0",
        "Provider": "Cohere (Paid API)",
        "Dimension": 1024,
        "Cost per 1M Tokens": "$0.10",
        "MTEB Retrieval Avg": 56.2,
        "Deployment Type": "API-based",
        "License": "Proprietary"
    },
    {
        "Model Name": "bge-small-en-v1.5",
        "Provider": "BAAI (Local/Free)",
        "Dimension": 384,
        "Cost per 1M Tokens": "$0.00 (Local)",
        "MTEB Retrieval Avg": 51.1,
        "Deployment Type": "Local",
        "License": "MIT"
    },
    {
        "Model Name": "all-MiniLM-L6-v2",
        "Provider": "SentenceTransformers (Local/Free)",
        "Dimension": 384,
        "Cost per 1M Tokens": "$0.00 (Local)",
        "MTEB Retrieval Avg": 41.95,
        "Deployment Type": "Local",
        "License": "Apache 2.0"
    },
    {
        "Model Name": "paraphrase-MiniLM-L3-v2",
        "Provider": "SentenceTransformers (Local/Free)",
        "Dimension": 384,
        "Cost per 1M Tokens": "$0.00 (Local)",
        "MTEB Retrieval Avg": 34.0,
        "Deployment Type": "Local",
        "License": "Apache 2.0"
    }
]
