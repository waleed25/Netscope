---
name: system-status
description: >
  Check the health and configuration of the Netscope system: LLM backend status,
  VRAM usage, available models, token consumption, RAG health, and component
  status. Use when user asks about system health, LLM status, which model is
  loaded, token usage, VRAM, or whether components are working.
license: Proprietary
metadata:
  category: system
  triggers:
    - system status
    - health check
    - llm status
    - which model
    - what model
    - token usage
    - vram
    - is the model loaded
    - component status
    - backend status
    - how many tokens
  tool_sequence:
    - system_status
    - llm_status
    - token_usage
    - list_models
    - rag_status
  examples:
    - "What's the system status?"
    - "Is the LLM working?"
    - "How much VRAM is being used?"
    - "Which models are available?"
    - "How many tokens have been used?"
    - "Is the RAG knowledge base ready?"
---

## System Status Workflow

### Quick health check
`system_status` — all components in one call: LLM, capture, RAG, Modbus sessions

### LLM-specific
`llm_status` — model name, backend (Ollama/LM Studio), VRAM usage, context length, reachability
`list_models` — all available models on the current backend
`token_usage` — cumulative tokens used in this session

### RAG health
`rag_status` — collection initialized, chunk count. If 0 chunks → KB is empty

### Interpreting results
| Field | Healthy | Warning |
|---|---|---|
| `reachable` | `true` | `false` → backend not running |
| `vram_used_bytes` | < model_size | ≈ model_size → CPU offload likely |
| `context_length` | 8192+ | < 4096 → limited context |
| RAG `chunks` | > 100 | 0 → no documents uploaded |

If LLM is unreachable, the fix is: start Ollama (`ollama serve`) or LM Studio, then reload the model.
