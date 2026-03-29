---
name: ollama
version: "1.0"
description: >
  Ollama local LLM runtime management: pull models, check VRAM usage,
  select quantization levels, and configure models for network analysis tasks.
triggers:
  - "ollama"
  - "pull model"
  - "model download"
  - "list models"
  - "model size"
  - "quantization"
  - "gguf"
  - "q4"
  - "q8"
  - "download llm"
  - "install model"
  - "remove model"
tools:
  - list_models
  - llm_status
parameters:
  model_name:
    type: string
    description: "Model name in name:tag format (e.g., qwen3:4b)"
output_format: Markdown summary
---

## Ollama Skill

### What is Ollama

Ollama is a local LLM runtime that downloads and serves GGUF model files on your machine.
It exposes an OpenAI-compatible HTTP API at `http://localhost:11434`, which Netscope
connects to automatically. No internet connection is required after a model is pulled.

### Model Naming

Models follow `name:tag` format:

| Model | Tag | Notes |
|-------|-----|-------|
| `qwen3` | `4b` | Fast, good for ICS/networking analysis |
| `gemma3` | `4b` | Google model, strong reasoning |
| `llama3.2` | `3b` | Meta model, lightweight |
| `llama3.1` | `8b` | Balanced capability |
| `deepseek-r1` | `7b` | Reasoning-focused |
| `mistral` | `7b` | General purpose |

Omitting a tag pulls the default (usually the largest recommended variant).

### Quantization Levels

Quantization reduces model size and VRAM usage at a small quality cost:

| Quantization | Size Multiplier | Quality | Speed | Use When |
|--------------|-----------------|---------|-------|----------|
| `Q4_K_M` | ~0.35x F16 | Good | Fastest | Low VRAM, fast response needed |
| `Q5_K_M` | ~0.44x F16 | Better | Fast | Balanced — recommended default |
| `Q8_0` | ~0.78x F16 | Near-lossless | Moderate | High quality analysis |
| `F16` | 1.0x | Lossless | Slowest | Maximum accuracy, large VRAM only |

Example: `qwen3:4b-q4_k_m` specifies a 4B model with Q4_K_M quantization.

### VRAM Requirements

| Model Size | Q4_K_M | Q5_K_M | Q8_0 | F16 |
|------------|--------|--------|------|-----|
| 1–2B | ~1 GB | ~1.2 GB | ~2 GB | ~3 GB |
| 3B | ~2 GB | ~2.5 GB | ~3.5 GB | ~6 GB |
| 7B | ~4 GB | ~5 GB | ~8 GB | ~14 GB |
| 14B | ~8 GB | ~10 GB | ~15 GB | ~28 GB |
| 32B | ~18 GB | ~22 GB | — | — |

Rule of thumb: always leave 1–2 GB VRAM headroom for the OS and other processes.

### Checking Current State

```
TOOL: list_models
TOOL: llm_status
```

`list_models` returns all models currently available on the Ollama backend.
`llm_status` shows the active model name, backend URL, and reported VRAM usage.

### Pulling a Model via the UI

1. Open **LLM Config** tab in Netscope
2. Click the **Download** button (arrow icon) next to the model list
3. Enter the model name in `name:tag` format (e.g., `qwen3:4b`)
4. Click **Pull** — progress streams in real time via SSE
5. Once complete, the model appears in the model selector

Backend endpoint: `POST /api/llm/pull` — streams JSON progress events.

### Model Selection Guidance

- **6 GB or less VRAM**: use `qwen3:4b` or `llama3.2:3b` with Q4_K_M
- **8–12 GB VRAM**: use `gemma3:4b` Q8_0 or `llama3.1:8b` Q4_K_M
- **16 GB+ VRAM**: use `llama3.1:8b` Q8_0 or `deepseek-r1:7b` F16
- **No GPU / CPU only**: use `llama3.2:3b` Q4_K_M — inference will be slow (10–30 s/response)

For ICS and networking analysis tasks, `qwen3:4b` performs well due to its instruction
following and technical knowledge. `gemma3:4b` is a strong alternative.

### Troubleshooting

**Model not found after pull:**
- Run `TOOL: list_models` to confirm it completed
- Check Ollama service is running: `ollama list` in a terminal
- Retry the pull — partial downloads are resumed automatically

**Out of VRAM / model fails to load:**
- Run `TOOL: llm_status` to see current VRAM usage
- Switch to a smaller model or lower quantization (Q4_K_M)
- Close other GPU-heavy applications

**Slow inference (>30 s/token):**
- GPU is not being used — check Ollama CUDA/ROCm setup
- Model too large for VRAM (CPU fallback active)
- Use `TOOL: llm_status` to check reported device
