# Plan: OpenClaw-Style Exec + Autonomous Agent Mode

## Context

Netscope's agent has 39 tools across 11 categories but **no shell/exec tool** and is limited to **4 tool rounds per chat turn**. The user wants OpenClaw-style `exec` (arbitrary command execution) and `autonomy` (extended agentic loops for multi-step goal pursuit).

---

## Critical Files

| File | Role |
|------|------|
| `backend/agent/tools/exec.py` | **NEW** — exec tool |
| `backend/agent/tasks.py` | **NEW** — background task manager |
| `backend/agent/tools/__init__.py` | Add exec to lazy-load map |
| `backend/agent/tools/registry.py` | Add exec to category order |
| `backend/agent/chat.py` | Autonomous mode state + dynamic max rounds + allow_dangerous passthrough |
| `backend/config.py` | `exec_timeout`, `autonomous_max_rounds` settings |
| `backend/api/routes.py` | Autonomous toggle + task CRUD endpoints |
| `frontend/src/components/ChatBox.tsx` | Autonomous toggle button |
| `frontend/src/store/useStore.ts` | `autonomousEnabled` state |
| `frontend/src/lib/api.ts` | API helpers |

---

## Phase 1: exec tool

**New file: `backend/agent/tools/exec.py`**

- Category: `exec`, safety: `dangerous`
- Runner: `asyncio.create_subprocess_shell(command, stdout=PIPE, stderr=PIPE)`
- Timeout: `config.exec_timeout` (default 30s)
- Output truncation: use registry's `MAX_OUTPUT` (3000 chars)
- Blocked patterns: `rm -rf /`, `format`, `del /s`, `rd /s`, `shutdown`, `reg delete`, `diskpart`, `mkfs`, `dd if=`
- Audit log: append to `data/exec_audit.jsonl`
- Keywords: `exec, run, command, shell, cmd, powershell, terminal, execute`
- `always_available=True` so it's always in the prompt

**Modify `backend/agent/tools/__init__.py`:**
- Add `"exec": "agent.tools.exec"` to `_CATEGORY_MODULES` (line 30)
- Add exec keywords to `CATEGORY_KEYWORDS` (line 46)

**Modify `backend/agent/tools/registry.py`:**
- Add `"exec"` to `_CATEGORY_ORDER` list

**Modify `backend/config.py`:**
- Add `exec_timeout: int = 30`

---

## Phase 2: Autonomous mode

**Modify `backend/config.py`:**
- Add `autonomous_max_rounds: int = 20`

**Modify `backend/agent/chat.py`:**

1. Add module-level state (following `_thinking_enabled` pattern in `llm_client.py`):
```python
_autonomous_mode: bool = False
def get_autonomous_mode() -> bool: return _autonomous_mode
def set_autonomous_mode(v: bool): global _autonomous_mode; _autonomous_mode = v
```

2. In `answer_question()` line 360 and `answer_question_stream()` line 420:
```python
# Before: for _round in range(MAX_TOOL_ROUNDS + 1):
max_rounds = settings.autonomous_max_rounds if _autonomous_mode else MAX_TOOL_ROUNDS
for _round in range(max_rounds + 1):
```

3. In `_base_messages()`, append autonomous prompt when active:
```python
if _autonomous_mode:
    parts.append("\n[AUTONOMOUS MODE]\nChain multiple tools to achieve the goal. Up to 20 rounds available. Report complete findings when done.")
```

4. Pass `allow_dangerous=_autonomous_mode` to `dispatch()` calls at lines 379 and 489:
```python
result = await dispatch(name, args, allow_dangerous=_autonomous_mode)
```

**Modify `backend/api/routes.py`:**
```python
@router.get("/agent/autonomous")    # → {"enabled": bool}
@router.post("/agent/autonomous")   # ← {"enabled": bool}
```

**Modify `frontend/src/store/useStore.ts`:**
- Add `autonomousEnabled: boolean` + setter

**Modify `frontend/src/lib/api.ts`:**
- Add `getAutonomous()` and `setAutonomous(enabled)`

**Modify `frontend/src/components/ChatBox.tsx`:**
- Add Autonomous toggle pill (Zap icon, green active state) after Think button
- Sync from backend on mount
- Pulsing dot when active

---

## Phase 3: Background autonomous tasks

**New file: `backend/agent/tasks.py`**
- `AgentTask` dataclass: `task_id, goal, status, progress[], final_answer, timestamps`
- `OrderedDict` of last 20 tasks
- `run_task()` — reimplements the agent loop using `_base_messages`, `chat_completion`, `_find_tool_call`, `dispatch` but records each tool call into `progress[]`
- Runs via `FastAPI.BackgroundTasks`

**Modify `backend/api/routes.py`:**
```
POST /api/agent/task        → create + start background task → {task_id}
GET  /api/agent/task/{id}   → {status, progress, final_answer}
GET  /api/agent/tasks       → list all tasks
```

**Modify `frontend/src/lib/api.ts`:**
- `createAgentTask(goal, maxRounds)`, `getAgentTask(id)`, `listAgentTasks()`

**Frontend UI (minimal v1):**
- Small "Tasks" indicator in chat header showing active count
- Dropdown showing task list with status badges

---

## Implementation Order

1. Phase 1 (exec tool) — backend only, test via chat
2. Phase 2 (autonomous mode) — backend + frontend toggle
3. Phase 3 (background tasks) — backend + minimal UI

---

## Verification

1. `GET /api/tools` lists `exec` with `safety: dangerous`
2. Chat: "run ipconfig" → exec tool fires, returns output
3. Chat: "run rm -rf /" → blocked pattern error
4. Toggle autonomous ON → `GET /agent/autonomous` → `{enabled: true}`
5. Autonomous chat: "ping 8.8.8.8 then check system status and summarize" → agent chains 2+ tools
6. `POST /agent/task {goal: "check system health"}` → returns task_id
7. `GET /agent/task/{id}` → shows progress and final answer
8. Frontend: Autonomous pill toggles, syncs on reload
