---
name: llm-config
version: "1.0"
description: >
  LLM backend configuration and performance tuning: switch between Ollama and
  LM Studio, adjust context window and temperature settings, and monitor token
  consumption for analysis sessions.
triggers:
  - "llm config"
  - "lm studio"
  - "context window"
  - "temperature"
  - "max tokens"
  - "llm backend"
  - "openai compatible"
  - "change model"
  - "switch model"
  - "llm settings"
  - "inference speed"
  - "gpu"
tools:
  - llm_status
  - list_models
  - token_usage
parameters:
  backend_url:
    type: string
    description: "Base URL for the LLM backend (e.g., http://localhost:11434)"
  model_name:
    type: string
    description: "Model identifier as reported by the backend"
output_format: Markdown summary
---

## LLM Configuration Skill

### Supported Backends

Netscope supports any OpenAI-compatible LLM backend:

| Backend | Default URL | Notes |
|---------|-------------|-------|
| **Ollama** | `http://localhost:11434` | Recommended — manages model downloads automatically |
| **LM Studio** | `http://localhost:1234` | GUI-based; load model manually before use |
| **Custom** | Any URL | Any server implementing the OpenAI `/v1/chat/completions` API |

Both backends expose the same API surface. Netscope uses the OpenAI Python SDK
internally, so switching backends only requires changing the base URL and API key.

### How to Configure

1. Open **Settings** in the Netscope sidebar
2. Navigate to the **LLM** tab
3. Set **Backend URL** (e.g., `http://localhost:11434`)
4. Set **API Key** (use any non-empty string for Ollama; LM Studio may require one)
5. Click **Save** — the backend is probed immediately to confirm connectivity

To switch the active model without leaving the chat:
```
TOOL: list_models
TOOL: llm_status
```

Then use the model selector dropdown in the LLM Config panel, or call
`POST /api/llm/model` with `{"model": "qwen3:4b"}`.

### Context Window

The context window is the maximum number of tokens the model can process in a single
request (prompt + response combined):

| Size | Typical Models | Best For |
|------|---------------|----------|
| 4K | Older 7B models | Simple Q&A |
| 8K | Most 3B–7B models | Standard analysis sessions |
| 32K | Newer 7B–14B | Long PCAP analysis, multi-turn context |
| 128K | Large models (Gemma 3 27B+) | Full document analysis |

**Why it matters for Netscope:** packet data and RAG context are injected into the prompt.
A 500-packet capture summary can consume 3–5K tokens before the user's question.
Choose a model with at least 8K context for analysis tasks.

### Temperature

Temperature controls response randomness:

| Value | Behavior | Use When |
|-------|----------|----------|
| `0.0` | Fully deterministic | Reproducible analysis, debugging |
| `0.1` | Near-deterministic | ICS audits, security analysis (recommended) |
| `0.3` | Slight variation | General networking questions |
| `0.7` | Creative | Brainstorming, report writing |
| `1.0` | High randomness | Not recommended for technical analysis |

Netscope defaults to `0.1` for analysis modes. Adjust in Settings → LLM → Temperature.

### Max Tokens

Controls the maximum length of each LLM response:

- **Netscope default:** 768 tokens (~600 words)
- **For detailed reports:** increase to 1500–2000 tokens
- **For fast interactive use:** reduce to 256–512 tokens

Note: max tokens counts against the context window. A 128K context window model
still only produces up to `max_tokens` per response.

### Checking Backend Status

```
TOOL: llm_status
```

Returns: backend URL, active model name, context window size, VRAM allocation,
and whether the model is loaded and responding.

```
TOOL: list_models
```

Returns all models currently available on the connected backend. If the list
is empty, the backend is unreachable or has no models loaded.

```
TOOL: token_usage
```

Shows tokens consumed in the current session — useful for estimating when you
are approaching context window limits.

### GPU vs CPU Inference

| Mode | Speed | VRAM Needed | When It Applies |
|------|-------|-------------|-----------------|
| Full GPU | Fast (50–100 tok/s) | Full model size | All layers fit in VRAM |
| Partial GPU | Moderate (10–30 tok/s) | Partial | Some layers offloaded to CPU |
| CPU only | Slow (1–5 tok/s) | None | No compatible GPU or driver issue |

To confirm GPU is active: `TOOL: llm_status` — check the device field.
For Ollama, GPU usage also appears in `ollama ps` in a terminal.

### When to Switch Models

| Scenario | Action |
|----------|--------|
| Complex ICS audit or multi-hop reasoning | Switch to larger model (7B+) |
| Fast interactive Q&A | Switch to smaller model (3B) |
| Response is truncated or incomplete | Increase max_tokens or use larger context model |
| Inference takes >30 s | Switch to smaller/more quantized model |
| Model gives wrong protocol names | Try a different model family |

### LM Studio Specifics

- Load a model in the LM Studio UI **before** connecting Netscope
- Enable the **Local Server** in LM Studio (port 1234 by default)
- The API key field can be any non-empty string (LM Studio accepts any value)
- LM Studio does not support the `/api/tags` endpoint — `list_models` will
  return only the currently loaded model
