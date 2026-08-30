import sys
import time
from pathlib import Path
import numpy as np
import chromadb

# Add src/ to path
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

import config
from resume_rag import ResumeRAGPipeline
from job_matcher import JobMatcher
from fs_tools import list_files, read_file
from eval_config import GROUND_TRUTH, BENCHMARK_DATA


def calculate_precision_recall_at_k(retrieved: list, ground_truth: set, k: int):
    top_k = retrieved[:k]
    hits = [candidate for candidate in top_k if candidate in ground_truth]
    precision = len(hits) / k
    recall = len(hits) / len(ground_truth) if len(ground_truth) > 0 else 0.0
    return precision, recall


def calculate_ap(retrieved: list, ground_truth: set):
    if not ground_truth:
        return 0.0
    hits = 0
    sum_precisions = 0.0
    for i, candidate in enumerate(retrieved):
        if candidate in ground_truth:
            hits += 1
            precision_at_i = hits / (i + 1)
            sum_precisions += precision_at_i
    return sum_precisions / len(ground_truth)


def calculate_rr(retrieved: list, ground_truth: set):
    for i, candidate in enumerate(retrieved):
        if candidate in ground_truth:
            return 1.0 / (i + 1)
    return 0.0


def main():
    models_to_evaluate = [
        ("sentence-transformers/all-MiniLM-L6-v2", "resumes_all_minilm"),
        ("BAAI/bge-small-en-v1.5", "resumes_bge_small"),
        ("sentence-transformers/paraphrase-MiniLM-L3-v2", "resumes_paraphrase_minilm")
    ]

    print("=" * 70)
    print("RAG Retrieval Accuracy & Performance Evaluation Suite")
    print("=" * 70)

    jds = list_files(config.JOB_DESCRIPTIONS_DIR)
    jds_data = []
    for jd_file in sorted(jds, key=lambda f: f['name']):
        data = read_file(jd_file['path'])
        if data['success']:
            jds_data.append((jd_file['name'], data['content']))

    # To store comparison results
    results_comparison = {}

    for model_name, col_name in models_to_evaluate:
        print(f"\nEvaluating Model: {model_name}")
        print(f"Collection: {col_name}")
        print("-" * 50)

        # 1. Clean slate database ingestion
        client = chromadb.PersistentClient(path=config.VECTOR_DB_PATH)
        try:
            client.delete_collection(col_name)
            print(f"Deleted existing collection '{col_name}' for clean start.")
        except Exception:
            pass

        print("Ingesting resumes...")
        t0 = time.time()
        pipeline = ResumeRAGPipeline(model_name=model_name, collection_name=col_name)
        pipeline.ingest_directory(config.RESUMES_DIR)
        ingest_time = time.time() - t0
        print(f"Ingestion completed in {ingest_time:.2f} seconds.")

        # 2. Evaluate matching
        matcher = JobMatcher(model_name=model_name, collection_name=col_name)

        model_metrics = {
            "filtered": {"p1": [], "p3": [], "p5": [], "r3": [], "r5": [], "map": [], "mrr": [], "latency": []},
            "unfiltered": {"p1": [], "p3": [], "p5": [], "r3": [], "r5": [], "map": [], "mrr": [], "latency": []}
        }

        for jd_name, jd_content in jds_data:
            ground_truth = set(GROUND_TRUTH.get(jd_name, []))
            if not ground_truth:
                continue

            for mode in ["filtered", "unfiltered"]:
                apply_filters = (mode == "filtered")
                
                t_start = time.time()
                # Retrieve top candidates
                matches_res = matcher.match(jd_content, k=10, apply_filters=apply_filters)
                t_latency = (time.time() - t_start) * 1000  # in ms
                
                retrieved_candidates = [m['candidate_name'] for m in matches_res.get('top_matches', [])]
                
                # Compute metrics
                p1, _ = calculate_precision_recall_at_k(retrieved_candidates, ground_truth, k=1)
                p3, r3 = calculate_precision_recall_at_k(retrieved_candidates, ground_truth, k=3)
                p5, r5 = calculate_precision_recall_at_k(retrieved_candidates, ground_truth, k=5)
                ap = calculate_ap(retrieved_candidates, ground_truth)
                rr = calculate_rr(retrieved_candidates, ground_truth)

                model_metrics[mode]["p1"].append(p1)
                model_metrics[mode]["p3"].append(p3)
                model_metrics[mode]["p5"].append(p5)
                model_metrics[mode]["r3"].append(r3)
                model_metrics[mode]["r5"].append(r5)
                model_metrics[mode]["map"].append(ap)
                model_metrics[mode]["mrr"].append(rr)
                model_metrics[mode]["latency"].append(t_latency)

        # Store mean values for comparison
        results_comparison[model_name] = {
            "ingest_time_s": ingest_time,
            "filtered": {metric: np.mean(vals) for metric, vals in model_metrics["filtered"].items()},
            "unfiltered": {metric: np.mean(vals) for metric, vals in model_metrics["unfiltered"].items()}
        }

        # Print quick summary for the model
        for mode in ["filtered", "unfiltered"]:
            m = results_comparison[model_name][mode]
            print(f"  [{mode.upper()} MODE] Avg Latency: {m['latency']:.2f} ms | P@1: {m['p1']:.2f} | P@3: {m['p3']:.2f} | R@3: {m['r3']:.2f} | MAP: {m['map']:.2f}")

    # Generate complete report
    print("\n" + "=" * 70)
    print("SUMMARY COMPARISON OF LOCAL EMBEDDING MODELS")
    print("=" * 70)
    
    # 1. LIVE COMPARISON TABLE
    print("\nLive Evaluation Results:")
    headers = ["Model", "Mode", "Ingest (s)", "Avg Latency (ms)", "P@1", "P@3", "R@3", "P@5", "R@5", "MAP", "MRR"]
    row_fmt = "{:<45} | {:<10} | {:<10} | {:<16} | {:<5} | {:<5} | {:<5} | {:<5} | {:<5} | {:<5} | {:<5}"
    print("-" * 135)
    print(row_fmt.format(*headers))
    print("-" * 135)
    
    for model_name, info in results_comparison.items():
        short_name = model_name.split("/")[-1]
        for mode in ["filtered", "unfiltered"]:
            m = info[mode]
            print(row_fmt.format(
                short_name,
                mode,
                f"{info['ingest_time_s']:.2f}",
                f"{m['latency']:.2f}",
                f"{m['p1']:.2f}",
                f"{m['p3']:.2f}",
                f"{m['r3']:.2f}",
                f"{m['p5']:.2f}",
                f"{m['r5']:.2f}",
                f"{m['map']:.2f}",
                f"{m['mrr']:.2f}"
            ))
    print("-" * 135)

    # 2. BENCHMARK COMPARISON TABLE
    print("\nPublic MTEB Benchmarks comparison with Proprietary Providers:")
    benchmark_headers = ["Model Name", "Provider", "Dimension", "Cost per 1M Tokens", "MTEB Retrieval Avg", "Deployment", "License"]
    benchmark_fmt = "{:<25} | {:<30} | {:<9} | {:<19} | {:<18} | {:<11} | {:<11}"
    print("-" * 140)
    print(benchmark_fmt.format(*benchmark_headers))
    print("-" * 140)
    for b in BENCHMARK_DATA:
        print(benchmark_fmt.format(
            b["Model Name"],
            b["Provider"],
            b["Dimension"],
            b["Cost per 1M Tokens"],
            b["MTEB Retrieval Avg"],
            b["Deployment Type"],
            b["License"]
        ))
    print("-" * 140)


if __name__ == "__main__":
    main()
