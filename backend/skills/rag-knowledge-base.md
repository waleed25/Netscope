---
name: rag-knowledge-base
version: "1.0"
description: >
  RAG knowledge base operations: ingest documents, crawl URLs, search the
  vector store, and configure hybrid BM25 + semantic retrieval for protocol
  references, vendor manuals, and RFC documents.
triggers:
  - "knowledge base"
  - "rag"
  - "ingest"
  - "upload document"
  - "search kb"
  - "vector search"
  - "bm25"
  - "semantic search"
  - "add document"
  - "crawl url"
  - "knowledge"
  - "tshark manual"
  - "wireshark wiki"
tools:
  - rag_status
  - rag_search
parameters:
  query:
    type: string
    description: "Search query for rag_search"
  url:
    type: string
    description: "URL to crawl into the knowledge base"
  file_path:
    type: string
    description: "Path to document file for ingestion"
output_format: Markdown with ranked chunk excerpts
---

## RAG Knowledge Base Skill

### What is RAG

RAG (Retrieval-Augmented Generation) lets the LLM answer questions using content
from documents you provide — protocol specs, vendor manuals, RFCs — rather than
relying solely on its training data.

Netscope uses a **hybrid retrieval** pipeline:
1. **BM25** — keyword-based full-text search (exact term matching)
2. **Semantic vector search** — ChromaDB with sentence-transformer embeddings
3. **Score fusion** — results from both are merged and re-ranked
4. Top-k chunks are appended to the LLM prompt as context

### Supported Document Types

| Format | Extension | Notes |
|--------|-----------|-------|
| PDF | `.pdf` | Text extracted; scanned PDFs need OCR pre-processing |
| Plain text | `.txt` | Ingested as-is |
| Markdown | `.md` | Rendered text only; code blocks preserved |
| Word | `.docx` | Body text extracted; tables supported |
| CSV | `.csv` | Each row treated as a document chunk |

Maximum upload size: **200 MB** per file (enforced by backend).

### How to Ingest Documents

**Via the UI:**
1. Open the **RAG** tab
2. Click **Upload Document** and select a file
3. Wait for the progress indicator — large PDFs may take 30–60 seconds
4. Run `TOOL: rag_status` to confirm the chunk count increased

**Via URL crawl:**
1. Open the **RAG** tab
2. Enter a URL in the **Crawl URL** field and click **Crawl**
3. The crawler fetches the page, strips HTML, and ingests the text
4. SSRF protection blocks private IPs and non-HTTP(S) URLs

Backend endpoints:
- `POST /api/rag/ingest` — multipart file upload
- `POST /api/rag/crawl` — `{"url": "https://..."}` JSON body

### Checking Knowledge Base Health

```
TOOL: rag_status
```

Returns:
- Total documents ingested
- Total chunk count
- Embedding model name and dimension
- ChromaDB collection status
- Last ingestion timestamp

### Searching the Knowledge Base

```
TOOL: rag_search Modbus exception codes
TOOL: rag_search DNP3 object types
TOOL: rag_search TCP three-way handshake RFC
```

Returns top-k chunks with relevance scores. Use this before asking a complex
protocol question to verify relevant content exists in the KB.

### Relevance Score Interpretation

| Score Range | Meaning | Action |
|-------------|---------|--------|
| > 0.7 | Strong match | High confidence — answer will be grounded |
| 0.3 – 0.7 | Partial match | Useful context, but LLM may supplement from training |
| < 0.3 | Weak match | KB likely doesn't have relevant content — ingest first |

### Chunk Size and Overlap

Documents are split into overlapping chunks before embedding:
- **Default chunk size:** 512 tokens
- **Overlap:** 64 tokens (ensures context isn't lost at chunk boundaries)

For dense technical documents (RFCs, protocol specs), smaller chunks (256 tokens)
improve retrieval precision. This is configurable in `backend/config.py`.

### How Context Injection Works

When you ask a question in chat:
1. The query is sent to the hybrid retrieval pipeline
2. Top-k chunks (default: 5) are fetched from ChromaDB
3. Chunks are prepended to the LLM system prompt as `[KB Context]`
4. The LLM generates a response grounded in both retrieved content and training data

The injected context consumes up to **2000 tokens** of the prompt budget (P8 tier).
If the KB is noisy, this can degrade response quality — keep the KB focused.

### Seeding Useful Sources

For networking and ICS work, consider ingesting:

| Source | Content | How to Add |
|--------|---------|-----------|
| Wireshark wiki | Protocol dissector details | Crawl `wiki.wireshark.org` pages |
| RFC 793 | TCP specification | Upload PDF from `rfc-editor.org` |
| Modbus spec | Function codes, exception codes | Upload `modbus.org` PDF |
| DNP3 guide | Object types, data link layer | Upload vendor DNP3 guide PDF |
| Vendor manuals | Device-specific registers | Upload device documentation |

**tshark filter reference** — Netscope provides a seed endpoint:
`POST /api/rag/seed-tshark` — automatically ingests the tshark display filter
reference into the KB. Run this once after setup.

### When RAG Helps Most

- **Protocol-specific questions**: "What does Modbus exception code 3 mean?"
- **RFC references**: "What is the TCP MSS option?"
- **Vendor-specific registers**: "What does register 40001 mean on this inverter?"
- **Filter syntax**: "How do I filter for DNP3 unsolicited responses in tshark?"

RAG adds minimal value for questions about live traffic data — use `query_packets`
and `generate_insight` tools for that instead.

### Troubleshooting

**Search returns no results:**
- Run `TOOL: rag_status` — if chunk count is 0, nothing has been ingested
- Ingest a relevant document first

**Low relevance scores on all results:**
- Rephrase the query using domain-specific terms from the document
- The document may use different terminology — try synonyms

**Ingestion fails:**
- File over 200 MB limit — split the document
- Scanned PDF with no extractable text — use OCR tool first
- URL blocked by SSRF protection — only public HTTP(S) URLs are allowed
