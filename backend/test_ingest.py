"""
Quick end-to-end test of the Qwen3-Embedding-0.6B ingest + retrieval pipeline.
Run from backend/: python test_ingest.py
"""
import sys, os, asyncio, time, warnings, logging
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.path.insert(0, ".")

import torch
from rag.ingest import ingest_url, list_sources, total_chunk_count, get_embedder
from rag.retriever import retrieve_for_query

TEST_URL    = "https://wiki.wireshark.org/DisplayFilters"
SOURCE_NAME = "wireshark-wiki"
TEST_QUERY  = "how do I filter traffic by IP address in Wireshark?"

def sep(title=""):
    print(f"\n{'─'*55}")
    if title:
        print(f"  {title}")
        print(f"{'─'*55}")

async def main():
    sep("Environment")
    embedder = get_embedder()
    device = embedder.device
    print(f"  Model  : Qwen/Qwen3-Embedding-0.6B")
    print(f"  Device : {device}")
    print(f"  VRAM   : {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")

    sep("Ingest")
    print(f"  URL    : {TEST_URL}")
    t0 = time.monotonic()
    result = await ingest_url(TEST_URL, SOURCE_NAME)
    elapsed = time.monotonic() - t0

    if result.error:
        print(f"  ERROR  : {result.error}")
        return

    total = total_chunk_count()
    print(f"  Chunks stored  : {result.chunk_count}")
    print(f"  Chunks skipped : {result.skipped}")
    print(f"  Duration       : {elapsed:.2f}s")
    print(f"  Throughput     : {result.chunk_count / elapsed:.0f} chunks/s")
    print(f"  Total in DB    : {total}")

    sep("Retrieval")
    print(f"  Query : {TEST_QUERY}")
    t1 = time.monotonic()
    context, chunks, best_score = await retrieve_for_query(TEST_QUERY, n_results=3)
    query_ms = (time.monotonic() - t1) * 1000
    print(f"  Results        : {len(chunks)}")
    print(f"  Best similarity: {best_score:.3f}")
    print(f"  Query latency  : {query_ms:.0f}ms")

    for i, c in enumerate(chunks, 1):
        print(f"\n  [{i}] score={c.similarity:.3f}  rerank={c.rerank_score:.3f}")
        print(f"      {c.window_text[:200].strip()}...")

    sep("PASS" if chunks else "WARN — no results")

asyncio.run(main())
