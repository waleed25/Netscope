---
name: token-budget
version: "1.0"
description: >
  Token usage tracking and prompt optimization: understand Netscope's 8000-token
  prompt budget allocation, use TOON compact output format, and apply strategies
  to prevent context window exhaustion during long analysis sessions.
triggers:
  - "token usage"
  - "context limit"
  - "prompt too long"
  - "token budget"
  - "reduce tokens"
  - "context window full"
  - "out of tokens"
  - "toon format"
  - "compact output"
tools:
  - token_usage
parameters:
  format:
    type: enum
    values: [toon, json, markdown]
    description: "Output format preference for analysis results"
output_format: TOON preferred; Markdown for explanations
---

## Token Budget Skill

### Checking Token Usage

```
TOOL: token_usage
```

Returns tokens consumed in the current session: prompt tokens, completion tokens,
total tokens, and an estimate of remaining capacity before hitting the model's
context window limit.

Run this periodically during long sessions to avoid unexpected truncation.

### Netscope's 8000-Token Prompt Budget

Every request to the LLM assembles a prompt from multiple layers. The total
budget is **8000 tokens** distributed across priority tiers:

| Tier | Component | Budget | Description |
|------|-----------|--------|-------------|
| P1 | Persona | 400 tok | System identity, role, and core instructions |
| P2 | Context overlays | 300 tok | Session-specific context (active tools, mode) |
| P3 | Memory | 200 tok | Recent session state and key facts |
| P4 | L1 Skills (list) | 200 tok | Compact skill name + trigger list |
| P5 | L2 Skills (body) | 400 tok | Full skill content for matched skills |
| P6 | Tools | 1000 tok | Tool descriptions and call schemas |
| P7 | Traffic context | 500 tok | Recent packet summary injected automatically |
| P8 | RAG context | 2000 tok | Top-k chunks from the knowledge base |
| — | Chat history | remaining | Previous turns in the conversation |
| — | User message | variable | Current user input |
| — | LLM response | max_tokens | Reserved for the response (default 768) |

**Total fixed overhead:** ~5000 tokens before chat history and the current message.
With an 8K context model, this leaves roughly **3000 tokens** for conversation history.

With a 32K model, history can span many more turns before truncation occurs.

### TOON: Token-Optimized Object Notation

TOON is Netscope's compact output format for structured data. It uses fixed-width
tables instead of JSON objects, saving 40–60% of tokens for equivalent data.

**JSON format (verbose, ~180 tokens for 3 packets):**
```json
[
  {"time": "09:01:01", "src": "192.168.1.10", "dst": "192.168.1.20",
   "proto": "Modbus", "len": 66, "info": "FC3 Read Holding Registers"},
  {"time": "09:01:01", "src": "192.168.1.20", "dst": "192.168.1.10",
   "proto": "Modbus", "len": 60, "info": "FC3 Response 10 regs"}
]
```

**TOON format (~60 tokens for the same data):**
```
PACKETS[2]
time      src            dst            proto   len  info
09:01:01  192.168.1.10  192.168.1.20  Modbus   66  FC3 Read
09:01:01  192.168.1.20  192.168.1.10  Modbus   60  FC3 Resp 10r
```

TOON is used automatically by `query_packets`, `generate_insight`, and
`expert_analyze`. Request it explicitly for chat responses:
> "Show me the results in TOON format"

### Strategies for Tight Context

When approaching context limits, apply these techniques in order:

**1. Pre-filter before analysis**

Instead of analyzing all packets, narrow the dataset first:
```
TOOL: query_packets modbus.func_code == 6
```
This sends only write operations to the LLM rather than thousands of packets.

**2. Use focused questions**

Avoid: "Analyze everything in this capture"
Prefer: "What hosts are sending Modbus write commands?"

Broad questions pull more context, generate longer responses, and fill history faster.

**3. Disable RAG when not needed**

RAG context (P8) consumes up to 2000 tokens per request. If you are asking about
live traffic rather than protocol specs, disable RAG in Settings → LLM → RAG Context.

**4. Request TOON output explicitly**

Ask for TOON tables instead of Markdown lists or JSON. Example:
> "Show the top talkers in TOON format"

**5. Start a fresh session**

Chat history accumulates across turns. For a new investigation, open a new chat
session to reset the history token count.

**6. Use a larger context model**

If a 7B model with 8K context is too constrained, switch to a 7B+ model with
32K or 128K context. The analysis quality is similar; the window is larger.

### Signs of Context Pressure

| Symptom | Likely Cause |
|---------|-------------|
| Response cuts off mid-sentence | `max_tokens` limit reached — increase it |
| LLM ignores earlier instructions | History has pushed system prompt out of window |
| Analysis misses obvious facts | Traffic context truncated to fit budget |
| "I don't have that information" for ingested docs | RAG context not fitting in P8 budget |
| Repeated or incoherent responses | Context window overflow — start new session |

### Token Budget by Model Context Size

| Model Context | Chat History Available | Recommended Use |
|---------------|----------------------|-----------------|
| 4K | ~0 tokens | Not suitable for Netscope |
| 8K | ~3000 tokens | Short focused sessions |
| 16K | ~11000 tokens | Standard analysis sessions |
| 32K | ~27000 tokens | Long multi-step investigations |
| 128K | ~123000 tokens | Full PCAP analysis + long history |

The 8K models (common in 3B–7B quantized) are workable for quick questions.
For extended analysis sessions, use a model with at least 16K context.
