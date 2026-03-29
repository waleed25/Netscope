# Wireshark Expert Analysis — Design Spec
**Date:** 2026-03-24
**Goal:** Make Netscope as good or better than Chris Greer at analyzing Wireshark captures.

---

## Overview

Add two analysis modes to the existing InsightPanel — **Quick** (LLM tool-driven) and **Deep** (Python/tshark pipeline + LLM narrator). Both modes feed into the chat interface so users can ask follow-up questions about any finding. All heavy computation runs in Python and tshark; the LLM is only ever asked to narrate pre-computed results, which makes small local models (qwen2.5:3b etc.) produce expert-level output.

---

## Constraints

- Local LLM only (Ollama / LM Studio). No cloud API.
- tshark and Python do all metric computation. LLM narrates findings only.
- TOON encoding continues to be used wherever packet lists are passed to the LLM (Quick mode tools).
- No new tabs. Quick/Deep are added as mode buttons inside the existing InsightPanel alongside General / Security / ICS (the frontend `MODES` array in `InsightPanel.tsx`).

---

## Architecture

```
InsightPanel  [General][Security][ICS][⚡ Quick][🔬 Deep]
                                          │              │
                                  LLM tool-driven   Python pipeline first
                                  (new tools added  then LLM narrates
                                   to agent registry)
                                          │              │
                                          └──────┬───────┘
                                                 │
                                    Analysis result → useStore
                                                 │
                                    ChatBox — analysis_context field
                                    sent with every chat message
```

---

## Backend

### 1. Packet Schema Extension

`tcp_health()` and `latency_breakdown()` both require fields that are not in the current packet dict schema. Rather than extend the live packet parser (which would increase parsing cost for every packet), both functions fall back to a **tshark subprocess approach** when operating on a pcap file. For live captures (no pcap path), only the fields already present in memory are used and metrics degrade gracefully (e.g. RTT computed from timestamps only, retransmission count estimated from duplicate seq numbers).

The following tshark fields are read via subprocess when a pcap path is available:

| Field | tshark name | Used by |
|---|---|---|
| Retransmission flag | `tcp.analysis.retransmission` | `tcp_health` |
| Zero window flag | `tcp.analysis.zero_window` | `tcp_health` |
| Duplicate ACK flag | `tcp.analysis.duplicate_ack` | `tcp_health` |
| Out of order flag | `tcp.analysis.out_of_order` | `tcp_health` |
| Stream index | `tcp.stream` | `latency_breakdown`, `stream_inventory` |
| SYN flag | `tcp.flags.syn` | `latency_breakdown` (RTT) |
| ACK flag | `tcp.flags.ack` | `latency_breakdown` (RTT) |

tshark invocation for these fields:
```bash
tshark -r <pcap> -T fields \
  -e frame.number -e frame.time_relative \
  -e ip.src -e ip.dst -e tcp.stream \
  -e tcp.flags.syn -e tcp.flags.ack \
  -e tcp.analysis.retransmission \
  -e tcp.analysis.zero_window \
  -e tcp.analysis.duplicate_ack \
  -e tcp.analysis.out_of_order \
  -E header=y -E separator=, -E quote=d
```

This is called once per deep analysis run and the result cached for the session.

### 2. Analysis Pipeline — `backend/agent/tools/analysis_pipeline.py` (new)

Pure Python/tshark. No LLM calls. Returns structured JSON. Each function is independently callable.

#### `tcp_health(packets: list[dict], pcap_path: str | None) → dict`
- When `pcap_path` is provided: runs the tshark subprocess above to get `tcp.analysis.*` flags; counts retransmissions, zero-window packets, duplicate ACKs, RSTs, out-of-order packets; computes RTT from SYN/SYN-ACK timestamp deltas per stream; identifies top offending conversations by retransmission count.
- When `pcap_path` is None (live capture): estimates retransmissions from duplicate sequence numbers in memory; RTT from SYN/SYN-ACK deltas in timestamps; RSTs from existing `tcp_flags` field in packet dict. Clearly marks estimates as approximate.
- Returns:
  ```json
  {
    "retransmissions": 42, "zero_windows": 3, "duplicate_acks": 18,
    "out_of_order": 5, "rsts": 7, "rtt_avg_ms": 4.2,
    "top_offenders": [{"src": "192.168.1.5", "dst": "10.0.0.1", "retransmits": 12}],
    "estimated": false
  }
  ```

#### `stream_inventory(packets: list[dict], pcap_path: str | None) → list[dict]`
- When pcap_path available: uses `tcp.stream` field from tshark subprocess to group packets into streams.
- When not available: groups by `(src_ip, dst_ip, src_port, dst_port)` 4-tuple as proxy for stream.
- Detects application protocol by port heuristics and existing `protocol` field.
- Returns list sorted by byte volume descending:
  ```json
  [
    {"stream_id": 0, "src": "192.168.1.5:54321", "dst": "10.0.0.1:80",
     "protocol": "HTTP", "packets": 142, "bytes": 98432, "duration_s": 4.2}
  ]
  ```

#### `latency_breakdown(packets: list[dict], pcap_path: str | None) → dict`
- Requires tshark subprocess data for accurate stream grouping and SYN/SYN-ACK matching.
- For each TCP stream: measures network RTT (SYN→SYN-ACK delta), client think time (ACK after data → next request), server response time (last request packet → first response packet).
- Flags streams where server response time exceeds network RTT by >10×.
- Returns:
  ```json
  {
    "streams": [
      {"stream_id": 0, "network_rtt_ms": 4.0, "server_ms": 88.0,
       "client_ms": 12.0, "bottleneck": "server"}
    ],
    "aggregate": {"network_rtt_ms": 4.2, "server_ms": 85.0, "client_ms": 11.0,
                  "bottleneck": "server", "server_pct": 85}
  }
  ```

#### `expert_info_summary(pcap_path: str | None) → dict`
- Calls `_run_expert(pcap_path)` from `backend/agent/tools/expert_info.py` (line 60) to get the raw tshark expert text output. **`_run_expert` returns a plain string, not JSON.** `expert_info_summary` must parse that string to produce the structured `counts`/`top` dict.
- **Do not re-implement the parser.** Use `expert_lines_to_toon` from `backend/utils/toon.py` (line 105), which already handles the real tshark `-z expert` output format (section headers like `Errors (N)` / `Warnings (N)`, followed by whitespace-delimited rows `Group Severity Protocol Summary` with `count: N` sub-lines). Call it as `expert_lines_to_toon(raw_output.splitlines())` and then build `counts` and `top` from the structured entries it returns.
- When pcap_path is None: returns `{"available": false, "reason": "live capture — no pcap file"}`.
- Returns:
  ```json
  {
    "available": true,
    "counts": {"error": 2, "warning": 5, "note": 12, "chat": 8},
    "top": [{"severity": "warning", "message": "TCP Retransmission", "count": 42}]
  }
  ```

#### `io_timeline(packets: list[dict]) → list[dict]`
- Bins packets into 1-second intervals based on packet timestamps.
- Rolling average window: **5 seconds**.
- Annotates bins where rate exceeds 2× the 5-second rolling average as bursts.
- Returns:
  ```json
  [
    {"t": 0.0, "packets_per_sec": 12, "bytes_per_sec": 8400, "burst": false},
    {"t": 4.0, "packets_per_sec": 156, "bytes_per_sec": 109200, "burst": true}
  ]
  ```

#### `run_deep_analysis(packets: list[dict], pcap_path: str | None) → dict`
- Orchestrates all five functions above.
- The tshark subprocess (for tcp.analysis.* fields) is called once and shared across `tcp_health`, `stream_inventory`, and `latency_breakdown`.
- Returns:
  ```json
  {
    "tcp_health": { ... },
    "streams": [ ... ],
    "latency": { ... },
    "expert_info": { ... },
    "io_timeline": [ ... ]
  }
  ```

### 3. Narrative — `backend/agent/tools/narrative.py` (new)

Single function: `generate_narrative(report: dict) → AsyncGenerator[str, None]`

- Accepts the `run_deep_analysis()` output.
- Builds a focused compact prompt with the structured data (total prompt for the report section: ≤400 tokens).
- Streams LLM response token by token via `chat_completion_stream`. Note: `chat_completion_stream` yields `(token: str, is_reasoning: bool)` tuples — unpack and skip `is_reasoning=True` tokens (consistent with how `answer_question_stream` handles them at `chat.py` line ~454).
- Prompt instructs LLM to: lead with the most important finding, identify the bottleneck, flag any ICS/OT concerns, keep it under 200 words.

### 4. New API Endpoints — `backend/api/routes.py`

| Method | Path | Description |
|---|---|---|
| `POST` | `/analysis/deep` | Run full pipeline on current in-memory packets; returns JSON (narrative not included) |
| `GET` | `/analysis/narrative` | Stream narrative for the most recent deep analysis result (`media_type="text/plain"`, matching existing insight/chat streams) |
| `GET` | `/analysis/tcp-health` | TCP health metrics only |
| `GET` | `/analysis/streams` | Stream inventory |
| `GET` | `/analysis/latency` | Latency breakdown |
| `GET` | `/analysis/io-timeline` | IO timeline bins |

**Two-phase approach for Deep mode:**
1. Frontend calls `POST /analysis/deep` → receives structured JSON → renders metric cards.
2. Frontend immediately opens `GET /analysis/narrative` (SSE stream) → streams narrative into the Narrative card.

This avoids the blocking/streaming contradiction: the JSON endpoint is synchronous, the narrative endpoint is a standard SSE stream (same pattern as the existing chat stream in `api/websocket.py`).

**Server-side state bridging the two endpoints:** Add a module-level variable in `backend/api/routes.py`:
```python
_last_deep_analysis: dict | None = None
```
`POST /analysis/deep` stores its result in `_last_deep_analysis` before returning. `GET /analysis/narrative` reads from `_last_deep_analysis` and returns 400 if it is None (i.e. no analysis has been run yet this session).

`POST /analysis/deep` is **not** cancellable (runs to completion, typically <2s for Python/tshark work). The frontend disables the "🔬 Deep" button while the request is in flight. The narrative stream uses `AbortController` on the frontend, consistent with how chat streaming is cancelled today.

All endpoints read from the existing in-memory packet store. `/analysis/deep` and the individual sub-endpoints (`/analysis/tcp-health`, `/analysis/streams`, `/analysis/latency`, `/analysis/io-timeline`) all accept an optional `pcap_path: str = ""` query parameter. When `pcap_path` is empty, the tshark subprocess path degrades gracefully (estimates only, `estimated: true` in response). This degraded behaviour is expected for live captures and is surfaced in the UI as a footnote on affected metric cards.

### 5. ChatRequest Wire Format Extension — Full Call Chain

**Step 1 — `ChatRequest` model** (`backend/api/routes.py` line 229):
```python
class ChatRequest(BaseModel):
    message:          str
    stream:           bool = False
    rag_enabled:      bool = False
    use_hyde:         bool = False
    analysis_context: str | None = None   # ← add this field
```

**Step 2 — chat route handler** (`backend/api/routes.py`, `chat()` function):
Pass `analysis_context` through to both call sites:
```python
# streaming path (answer_question_stream call at line ~596):
async for chunk in chat_agent.answer_question_stream(
    req.message, _packets, _chat_history,
    rag_enabled=req.rag_enabled, use_hyde=req.use_hyde,
    analysis_context=req.analysis_context,   # ← add
):

# non-streaming path (answer_question call):
response = await chat_agent.answer_question(
    req.message, _packets, _chat_history,
    rag_enabled=req.rag_enabled, use_hyde=req.use_hyde,
    analysis_context=req.analysis_context,   # ← add
)
```

**Step 3 — `answer_question` and `answer_question_stream`** (`backend/agent/chat.py`):
Add parameter to both function signatures and pass to `_base_messages`:
```python
async def answer_question(
    question: str, packets: list[dict], history: list[dict] | None = None,
    rag_enabled: bool = False, use_hyde: bool = False,
    is_channel: bool = False,
    analysis_context: str | None = None,   # ← add
) -> str:
    messages, rag_chunks = await _base_messages(
        packets, history, question, rag_enabled, use_hyde,
        is_channel=is_channel, shell_enabled=_shell_mode,
        analysis_context=analysis_context,  # ← add
    )

async def answer_question_stream(
    question: str, packets: list[dict], history: list[dict] | None = None,
    rag_enabled: bool = False, use_hyde: bool = False,
    analysis_context: str | None = None,   # ← add
) -> AsyncGenerator[str, None]:
    messages, rag_chunks = await _base_messages(
        packets, history, question, rag_enabled, use_hyde,
        shell_enabled=_shell_mode,
        analysis_context=analysis_context,  # ← add
    )
```

**Step 4 — `_base_messages`** (`backend/agent/chat.py` line 199):
Add parameter and inject context section:
```python
async def _base_messages(
    packets, history, question="", rag_enabled=False,
    use_hyde=False, is_channel=False, shell_enabled=False,
    analysis_context: str | None = None,   # ← add
) -> tuple[list[dict], list]:
```
Add `"analysis": 1600` to `_SECTION_BUDGETS` (line ~66):
```python
    "analysis": 1600,  # ~400 tokens — injected when deep analysis has run
```
Inject after the RAG section, before the traffic section. Truncate to fit rather than dropping silently:
```python
if analysis_context:
    ctx = analysis_context[:1600]   # hard truncate before _fits check
    if _fits("analysis", ctx):
        sections.append(f"[Analysis Report]\n{ctx}")
```
The 1600-char budget reliably fits the 5-line compact summary for real captures. The truncation guard prevents silent drops for pathological inputs.

**Frontend compact summary format** (≤800 chars, serialized by `InsightPanel.tsx` before sending):
```
TCP: {retransmissions} retransmit, {zero_windows} zero-win, {rsts} RST, RTT {rtt_avg_ms}ms
Latency: client {client_ms}ms / network {network_rtt_ms}ms / server {server_ms}ms ({bottleneck} bottleneck)
Streams: {tcp_count} TCP, {udp_count} UDP — protocols: {protocol_list}
Expert: {error} errors, {warning} warnings
Bursts: {burst_summary}
```

### 6. Quick Mode — Routing

Quick mode **does not** use `generate_insights_stream` in `analyzer.py` — that function has no tool dispatch loop and cannot call tools. Quick mode routes through the full agentic loop in `chat.py` (`answer_question_stream`) via the existing `/chat` endpoint.

When the user selects Quick mode in InsightPanel, the frontend sends a chat request to `POST /chat` with `stream: true` and a fixed system message:

```
"Run a quick expert analysis of this capture. Use the tcp_health_check, stream_follow, latency_analysis, io_graph, and expert_info tools. Lead with the most significant finding."
```

The result streams into the InsightPanel insight area exactly as the existing chat stream renders in ChatBox. No new backend routing is needed. The new tools (`tcp_health_check`, `stream_follow`, `latency_analysis`, `io_graph`) must be registered in the tool registry so the LLM can call them during this chat turn.

### 7. New Agent Tools — Quick Mode

Registered in `backend/agent/tools/analysis.py` under the `analysis` category. The `deep_analysis` tool is **not** included in Quick mode (it returns too much data for the LLM to reason over within MAX_OUTPUT).

| Tool name | Calls | Returns |
|---|---|---|
| `tcp_health_check` | `tcp_health()` | Compact metrics + short LLM commentary |
| `stream_follow` | tshark follow stream | Stream payload excerpt |
| `latency_analysis` | `latency_breakdown()` | Per-stream latency table (TOON-encoded) |
| `io_graph` | `io_timeline()` | Timeline bins as text table |

`stream_follow` specification:
- **Argument:** `stream_index: int` (passed by the LLM as a number; default 0 for first stream)
- **tshark command:** `tshark -r <pcap_path> -q -z follow,tcp,ascii,<stream_index>`
- **Truncation:** Output capped at MAX_OUTPUT (3000 chars); if truncated, append `[output truncated — {total_lines} lines total]`
- **Live capture fallback:** If no pcap path available, return `"Stream follow requires a saved pcap file. Use 'capture to file' mode."`

---

## Frontend

### TypeScript Types — `frontend/src/store/useStore.ts`

```typescript
interface TcpHealthReport {
  retransmissions: number;
  zero_windows: number;
  duplicate_acks: number;
  out_of_order: number;
  rsts: number;
  rtt_avg_ms: number;
  top_offenders: Array<{ src: string; dst: string; retransmits: number }>;
  estimated: boolean;
}

interface StreamRecord {
  stream_id: number;
  src: string;
  dst: string;
  protocol: string;
  packets: number;
  bytes: number;
  duration_s: number;
}

interface LatencyReport {
  streams: Array<{
    stream_id: number;
    network_rtt_ms: number;
    server_ms: number;
    client_ms: number;
    bottleneck: 'client' | 'network' | 'server';
  }>;
  aggregate: {
    network_rtt_ms: number;
    server_ms: number;
    client_ms: number;
    bottleneck: 'client' | 'network' | 'server';
    server_pct: number;
  };
}

interface ExpertInfoReport {
  available: boolean;
  reason?: string;
  counts?: { error: number; warning: number; note: number; chat: number };
  top?: Array<{ severity: string; message: string; count: number }>;
}

interface IoTimelineBin {
  t: number;
  packets_per_sec: number;
  bytes_per_sec: number;
  burst: boolean;
}

export interface DeepAnalysisReport {
  tcp_health: TcpHealthReport;
  streams: StreamRecord[];
  latency: LatencyReport;
  expert_info: ExpertInfoReport;
  io_timeline: IoTimelineBin[];
}
```

Add to store:
```typescript
analysisReport: DeepAnalysisReport | null;
analysisContext: string;           // compact text summary for chat injection
setAnalysisReport: (report: DeepAnalysisReport, context: string) => void;
```

### InsightPanel.tsx

- Add `{ id: 'quick', label: '⚡ Quick' }` and `{ id: 'deep', label: '🔬 Deep' }` to the existing `MODES` array.
- `quick` mode: same behaviour as existing modes — sends chat message with mode context, LLM uses new tools via the existing streaming insight path.
- `deep` mode:
  1. Button click calls `POST /analysis/deep` — "🔬 Deep" button disabled and shows spinner.
  2. On success: render six collapsible cards (see below); button re-enables.
  3. Immediately open SSE stream to `GET /analysis/narrative` — stream text into Narrative card token by token.
  4. Call `store.setAnalysisReport(report, compactSummary)` so chat context is updated.

**Six report cards (all collapsible, expanded by default):**

| Card | Key metrics shown |
|---|---|
| TCP Health | Retransmissions, zero-windows, RSTs, RTT avg; top offenders table |
| Latency Breakdown | Client / Network / Server bar with bottleneck highlight |
| Streams | Sortable table: endpoint pair, protocol, bytes, duration |
| Expert Info | Error/warning/note counts; expandable message list; hidden if `available: false` |
| IO Timeline | Sparkline bar chart (packets/sec per second); burst annotations |
| Narrative | LLM-generated prose, streamed in; "Ask in chat →" button |

Each card (except Narrative) has an **"Ask about this in chat →"** button that pre-fills the chat input with a contextual question:
- TCP Health: `"Why are there so many retransmissions?"`
- Latency: `"The server is the bottleneck — what's causing the delay?"`
- Streams: `"Walk me through stream 0"`
- Expert Info: `"What do the TCP warnings mean?"`
- IO Timeline: `"What caused the burst at t={burst_time}s?"`

---

## Data Flow — Deep Mode

```
User clicks 🔬 Deep
        │
        ▼
POST /analysis/deep  (button disabled)
        │
        ▼
run_deep_analysis(packets, pcap_path)
  ├── tshark subprocess (tcp.analysis.* + tcp.stream) — called once, shared
  ├── tcp_health()         ← Python + tshark data
  ├── stream_inventory()   ← Python + tshark data
  ├── latency_breakdown()  ← Python + tshark data
  ├── expert_info_summary()← reuses tshark_expert from expert_info.py
  └── io_timeline()        ← pure Python (timestamps only)
        │
        ▼
JSON report → frontend renders 5 metric cards
        │
        ├── store.setAnalysisReport(report, compactSummary)
        │        │
        │        ▼
        │   chat context updated (analysis_context field)
        │
        ▼
GET /analysis/narrative (SSE)
        │
        ▼
generate_narrative(report) — single focused LLM call
        │
        ▼
Streams token-by-token into Narrative card
```

---

## Data Flow — Quick Mode

```
User clicks ⚡ Quick (or asks in chat)
        │
        ▼
LLM receives: persona + traffic context (TOON) + new tool descriptions
        │
        ▼
LLM calls tool (e.g. tcp_health_check)
        │
        ▼
Tool runs tcp_health() → TOON-encoded compact output → MAX_OUTPUT enforced
        │
        ▼
Tool result injected as TOOL_RESULT message
        │
        ▼
LLM narrates finding → streamed to InsightPanel
```

---

## What This Delivers (Chris Greer Parity)

| Chris Greer Capability | How Netscope Matches It |
|---|---|
| TCP health (retransmissions, zero windows, RSTs) | `tcp_health()` via tshark subprocess; metrics card |
| RTT / latency measurement | `latency_breakdown()` — per-stream client/network/server split |
| Stream reconstruction / follow stream | `stream_follow` tool + Streams card |
| Expert Info analysis | `expert_info_summary()` — reuses existing `tshark_expert` |
| IO Graphs / traffic over time | `io_timeline()` — sparkline chart with burst annotation |
| Structured troubleshooting narrative | `generate_narrative()` — LLM narrates pre-computed findings |
| Follow-up Q&A | Chat integration — analysis_context always injected |

---

## Files Changed / Created

**New:**
- `backend/agent/tools/analysis_pipeline.py`
- `backend/agent/tools/narrative.py`

**Modified:**
- `backend/agent/tools/analysis.py` — register `tcp_health_check`, `stream_follow`, `latency_analysis`, `io_graph`
- `backend/api/routes.py` — add `/analysis/*` endpoints; add `analysis_context` field to `ChatRequest`
- `backend/agent/chat.py` — add `"analysis": 1600` to `_SECTION_BUDGETS`; inject `[Analysis Report]` context section
- `frontend/src/components/InsightPanel.tsx` — add Quick/Deep to `MODES`; Deep report cards; "Ask in chat →" buttons
- `frontend/src/store/useStore.ts` — add `DeepAnalysisReport` interface, `analysisReport`, `analysisContext`, `setAnalysisReport`

---

## Out of Scope

- Cloud LLM APIs
- New tabs or major layout changes
- Wireshark display filter UI builder (separate feature)
- Saving/exporting analysis reports to PDF
