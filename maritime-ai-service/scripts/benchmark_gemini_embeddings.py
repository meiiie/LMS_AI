"""Benchmark Gemini embedding models on a fixed Wiii corpus."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

load_dotenv(SERVICE_ROOT / ".env")
load_dotenv(SERVICE_ROOT / ".env.local")

from app.engine.model_catalog import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_BENCHMARK_CANDIDATE,
    get_embedding_dimensions,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent / "data" / "embedding_benchmark_corpus.json"
DEFAULT_OUTPUT_PATH = (
    REPO_ROOT / ".Codex" / "reports" / "EMBEDDING-2-BENCHMARK-2026-03-11.md"
)
GO_THRESHOLD_RECALL_DELTA = 0.05
GO_THRESHOLD_MRR_DELTA = 0.03
MAX_LATENCY_MULTIPLIER = 2.5


@dataclass
class ModelRun:
    model: str
    output_dimensionality: int | None
    document_vectors: dict[str, np.ndarray]
    doc_latency_seconds: float
    query_latencies_seconds: list[float]
    per_query_rankings: dict[str, list[str]]
    recall_at_k: float
    mean_reciprocal_rank: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--current-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--candidate-model", default=EMBEDDING_BENCHMARK_CANDIDATE)
    parser.add_argument(
        "--current-output-dimensionality",
        type=int,
        default=get_embedding_dimensions(DEFAULT_EMBEDDING_MODEL),
    )
    parser.add_argument(
        "--candidate-output-dimensionality",
        type=int,
        default=get_embedding_dimensions(EMBEDDING_BENCHMARK_CANDIDATE),
    )
    return parser.parse_args()


def load_corpus(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_vector(values: list[float]) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right))


def embed_texts(
    client: genai.Client,
    *,
    model: str,
    texts: list[str],
    task_type: str,
    output_dimensionality: int | None,
) -> tuple[list[np.ndarray], float]:
    started = time.perf_counter()
    response = client.models.embed_content(
        model=model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=output_dimensionality,
        ),
    )
    elapsed = time.perf_counter() - started
    vectors = [normalize_vector(item.values) for item in response.embeddings]
    return vectors, elapsed


def reciprocal_rank(ranking: list[str], relevant_ids: set[str]) -> float:
    for index, doc_id in enumerate(ranking, start=1):
        if doc_id in relevant_ids:
            return 1.0 / index
    return 0.0


def recall_at_k(ranking: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    retrieved = set(ranking[:k])
    return len(retrieved & relevant_ids) / len(relevant_ids)


def top_k_rankings(
    query_vector: np.ndarray,
    document_vectors: dict[str, np.ndarray],
    *,
    k: int,
) -> list[str]:
    scored = [
        (doc_id, cosine_similarity(query_vector, vector))
        for doc_id, vector in document_vectors.items()
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [doc_id for doc_id, _score in scored[:k]]


def run_model(
    client: genai.Client,
    *,
    model: str,
    output_dimensionality: int | None,
    documents: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    top_k: int,
) -> ModelRun:
    doc_vectors, doc_latency = embed_texts(
        client,
        model=model,
        texts=[doc["text"] for doc in documents],
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=output_dimensionality,
    )
    document_map = {
        doc["id"]: vector for doc, vector in zip(documents, doc_vectors, strict=True)
    }

    per_query_rankings: dict[str, list[str]] = {}
    query_latencies: list[float] = []
    recall_scores: list[float] = []
    reciprocal_ranks: list[float] = []

    for query in queries:
        query_vectors, latency = embed_texts(
            client,
            model=model,
            texts=[query["text"]],
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=output_dimensionality,
        )
        ranking = top_k_rankings(query_vectors[0], document_map, k=top_k)
        relevant_ids = set(query["relevant_doc_ids"])
        per_query_rankings[query["id"]] = ranking
        query_latencies.append(latency)
        recall_scores.append(recall_at_k(ranking, relevant_ids, top_k))
        reciprocal_ranks.append(reciprocal_rank(ranking, relevant_ids))

    return ModelRun(
        model=model,
        output_dimensionality=output_dimensionality,
        document_vectors=document_map,
        doc_latency_seconds=doc_latency,
        query_latencies_seconds=query_latencies,
        per_query_rankings=per_query_rankings,
        recall_at_k=statistics.mean(recall_scores),
        mean_reciprocal_rank=statistics.mean(reciprocal_ranks),
    )


def average_top_k_overlap(
    baseline: ModelRun,
    candidate: ModelRun,
    *,
    top_k: int,
) -> float:
    overlaps: list[float] = []
    for query_id, baseline_ranking in baseline.per_query_rankings.items():
        candidate_ranking = candidate.per_query_rankings[query_id]
        left = set(baseline_ranking[:top_k])
        right = set(candidate_ranking[:top_k])
        union = left | right
        overlaps.append(len(left & right) / len(union) if union else 1.0)
    return statistics.mean(overlaps)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((pct / 100) * len(ordered)) - 1))
    return ordered[index]


def estimate_storage_bytes(num_vectors: int, dimensions: int) -> int:
    return num_vectors * dimensions * 4


def recommendation(
    current: ModelRun,
    candidate: ModelRun,
    *,
    top_k: int,
) -> tuple[str, list[str]]:
    recall_delta = candidate.recall_at_k - current.recall_at_k
    mrr_delta = candidate.mean_reciprocal_rank - current.mean_reciprocal_rank
    latency_ratio = (
        statistics.mean(candidate.query_latencies_seconds)
        / max(statistics.mean(current.query_latencies_seconds), 1e-9)
    )
    notes = [
        f"Recall@{top_k} delta: {recall_delta:.3f}",
        f"MRR delta: {mrr_delta:.3f}",
        f"Mean query latency ratio: {latency_ratio:.2f}x",
    ]
    if (
        recall_delta >= GO_THRESHOLD_RECALL_DELTA
        and mrr_delta >= GO_THRESHOLD_MRR_DELTA
        and latency_ratio <= MAX_LATENCY_MULTIPLIER
    ):
        return "GO", notes
    return "NO-GO", notes


def write_report(
    output_path: Path,
    *,
    corpus: dict[str, Any],
    current: ModelRun,
    candidate: ModelRun,
    top_k: int,
) -> None:
    overlap = average_top_k_overlap(current, candidate, top_k=top_k)
    decision, notes = recommendation(current, candidate, top_k=top_k)
    current_dim = next(iter(current.document_vectors.values())).shape[0]
    candidate_dim = next(iter(candidate.document_vectors.values())).shape[0]
    current_storage = estimate_storage_bytes(len(current.document_vectors), current_dim)
    candidate_storage = estimate_storage_bytes(len(candidate.document_vectors), candidate_dim)
    requires_reindex = current_dim != candidate_dim

    lines = [
        "# Embedding 2 Benchmark Report",
        "",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Corpus: `{corpus['metadata']['name']}`",
        f"- Decision: **{decision}**",
        "",
        "## Thresholds",
        "",
        f"- Candidate Recall@{top_k} must improve by at least {GO_THRESHOLD_RECALL_DELTA:.2f}.",
        f"- Candidate MRR must improve by at least {GO_THRESHOLD_MRR_DELTA:.2f}.",
        f"- Mean query latency may not exceed {MAX_LATENCY_MULTIPLIER:.1f}x the current model.",
        "- Any dimension change implies reindex planning and storage review.",
        "",
        "## Summary",
        "",
        "| Metric | Current | Candidate |",
        "|---|---:|---:|",
        f"| Model | `{current.model}` | `{candidate.model}` |",
        f"| Output dimensionality | {current_dim} | {candidate_dim} |",
        f"| Recall@{top_k} | {current.recall_at_k:.3f} | {candidate.recall_at_k:.3f} |",
        f"| Mean reciprocal rank | {current.mean_reciprocal_rank:.3f} | {candidate.mean_reciprocal_rank:.3f} |",
        f"| Avg query latency (s) | {statistics.mean(current.query_latencies_seconds):.3f} | {statistics.mean(candidate.query_latencies_seconds):.3f} |",
        f"| P95 query latency (s) | {percentile(current.query_latencies_seconds, 95):.3f} | {percentile(candidate.query_latencies_seconds, 95):.3f} |",
        f"| Document batch latency (s) | {current.doc_latency_seconds:.3f} | {candidate.doc_latency_seconds:.3f} |",
        f"| Top-{top_k} ranking overlap | n/a | {overlap:.3f} |",
        f"| Estimated vector storage (bytes) | {current_storage} | {candidate_storage} |",
        f"| Requires reindex | {'no' if not requires_reindex else 'yes'} | {'yes' if requires_reindex else 'no'} |",
        "",
        "## Recommendation Notes",
        "",
    ]
    lines.extend(f"- {note}" for note in notes)
    lines.extend(
        [
            "",
            "## Query Rankings",
            "",
            "| Query | Relevant Docs | Current Top-K | Candidate Top-K |",
            "|---|---|---|---|",
        ]
    )
    for query in corpus["queries"]:
        query_id = query["id"]
        relevant = ", ".join(query["relevant_doc_ids"])
        current_ranking = ", ".join(current.per_query_rankings[query_id])
        candidate_ranking = ", ".join(candidate.per_query_rankings[query_id])
        lines.append(
            f"| `{query_id}` | `{relevant}` | `{current_ranking}` | `{candidate_ranking}` |"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is required to run the embedding benchmark.")

    corpus = load_corpus(args.corpus)
    client = genai.Client(api_key=api_key)

    current_run = run_model(
        client,
        model=args.current_model,
        output_dimensionality=args.current_output_dimensionality,
        documents=corpus["documents"],
        queries=corpus["queries"],
        top_k=args.top_k,
    )
    candidate_run = run_model(
        client,
        model=args.candidate_model,
        output_dimensionality=args.candidate_output_dimensionality,
        documents=corpus["documents"],
        queries=corpus["queries"],
        top_k=args.top_k,
    )
    write_report(
        args.output,
        corpus=corpus,
        current=current_run,
        candidate=candidate_run,
        top_k=args.top_k,
    )
    print(f"Benchmark report written to {args.output}")


if __name__ == "__main__":
    main()
