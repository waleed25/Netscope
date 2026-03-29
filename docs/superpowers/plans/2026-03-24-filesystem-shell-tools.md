# Filesystem + Shell Agent Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenClaw-style system access to the Netscope agent — filesystem tools (read_file, write_file, list_dir, find_files) and an unrestricted shell tool (run_shell), gated behind a per-session toggle.

**Architecture:** Two new tool modules in `backend/agent/tools/` following the existing `ToolDef` + `register()` pattern. A module-level `_shell_tool_enabled` flag (mirroring `_thinking_enabled` in `llm_client.py`) gates the `dangerous`-safety shell tool. The flag is read in `chat.py` when calling `dispatch()`. A frontend toggle in the chat header uses Zustand store state (mirroring `thinkingEnabled`).

**Security note:** `write_file` has `safety="write"` which is always permitted — it is NOT gated by the `allow_dangerous` flag. Only `run_shell` (safety=dangerous) requires the shell toggle. This is intentional: filesystem reads/writes use the backend process's existing OS permissions; shell execution is a broader escalation.

**Tech Stack:** Python 3.12, FastAPI, React 18 + Zustand + Tailwind (existing), `pathlib` for path handling, `subprocess` for shell execution.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `backend/agent/tools/filesystem.py` | read_file, write_file, list_dir, find_files tools |
| Create | `backend/agent/tools/shell.py` | run_shell tool (safety=dangerous) |
| Modify | `backend/agent/tools/__init__.py` | Add "filesystem" and "shell" to _CATEGORY_MODULES + CATEGORY_KEYWORDS |
| Modify | `backend/agent/tools/registry.py` | Add "filesystem" and "shell" to _CATEGORY_ORDER |
| Modify | `backend/config.py` | Add `allow_shell_tool: bool = False` as startup default only |
| Modify | `backend/agent/chat.py` | Add `_shell_tool_enabled` flag + accessors; pass to dispatch() |
| Modify | `backend/api/routes.py` | Add GET/POST `/agent/shell-tool` toggle endpoints |
| Modify | `frontend/src/store/useStore.ts` | Add `shellToolEnabled` + `setShellToolEnabled` |
| Modify | `frontend/src/lib/api.ts` | Add getShellTool() / setShellTool() |
| Modify | `frontend/src/components/ChatBox.tsx` | Add shell toggle button + restart re-sync |
| Modify | `backend/tests/test_tools.py` | Tests for all new tools |

---

## Task 1: Filesystem Tools

**Files:**
- Create: `backend/agent/tools/filesystem.py`
- Test: `backend/tests/test_tools.py` (append)

- [ ] **Step 1: Write failing tests for filesystem tools**

Append to `backend/tests/test_tools.py`:

```python
# ── filesystem tools ──────────────────────────────────────────────────────────

class TestFilesystemTools:

    @pytest.mark.asyncio
    async def test_read_file_existing(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        from agent.tools.filesystem import run_read_file
        result = await run_read_file(str(f))
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_read_file_missing(self, tmp_path):
        from agent.tools.filesystem import run_read_file
        result = await run_read_file(str(tmp_path / "nope.txt"))
        assert "[tool error]" in result

    @pytest.mark.asyncio
    async def test_write_file_creates(self, tmp_path):
        # Use a path guaranteed to have no spaces (avoid split-on-whitespace ambiguity)
        f = tmp_path / "out.txt"
        path_str = str(f).replace(" ", "_")  # paranoia: strip spaces if tmp_path has them
        from agent.tools.filesystem import run_write_file
        # Format: first line = path, rest = content
        result = await run_write_file(f"{path_str}\nhello world")
        assert "written" in result.lower()
        from pathlib import Path
        assert Path(path_str).read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_list_dir(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        from agent.tools.filesystem import run_list_dir
        result = await run_list_dir(str(tmp_path))
        assert "a.txt" in result and "b.txt" in result

    @pytest.mark.asyncio
    async def test_find_files(self, tmp_path):
        (tmp_path / "foo.py").write_text("")
        (tmp_path / "bar.txt").write_text("")
        from agent.tools.filesystem import run_find_files
        result = await run_find_files(f"{tmp_path} *.py")
        assert "foo.py" in result
        assert "bar.txt" not in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_tools.py::TestFilesystemTools -v 2>&1 | tail -15
```
Expected: `ImportError: cannot import name 'run_read_file'`

- [ ] **Step 3: Implement filesystem.py**

Create `backend/agent/tools/filesystem.py`:

```python
"""
Filesystem tools: read_file, write_file, list_dir, find_files.

Safety levels:
  read_file, list_dir, find_files  — safety="read"   (always permitted)
  write_file                        — safety="write"  (always permitted, uses OS permissions)

Note: write_file is NOT gated by allow_dangerous. It uses the backend process's
existing OS user permissions. Only run_shell (in shell.py) requires the
dangerous flag because it can escalate beyond filesystem boundaries.
"""
from __future__ import annotations
import asyncio
import fnmatch
import os
from pathlib import Path

from agent.tools.registry import register, ToolDef, MAX_OUTPUT


def _read_file(path_str: str) -> str:
    p = Path(path_str.strip()).expanduser()
    if not p.exists():
        return f"[tool error] File not found: {p}"
    if not p.is_file():
        return f"[tool error] Not a file: {p}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return f"[tool error] Permission denied: {p}"
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n...[truncated — {len(text)} chars total]"
    return text or "[tool] File is empty."


def _write_file(args: str) -> str:
    # Format: first line = path, remaining lines = content
    # Using newline separator avoids ambiguity when paths contain spaces.
    lines = args.split("\n", 1)
    if len(lines) < 2:
        return "[tool error] Usage: write_file <path>\\n<content>"
    p = Path(lines[0].strip()).expanduser()
    content = lines[1]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {p}"
    except PermissionError:
        return f"[tool error] Permission denied: {p}"
    except Exception as e:
        return f"[tool error] {e}"


def _list_dir(path_str: str) -> str:
    p = Path(path_str.strip() or ".").expanduser()
    if not p.exists():
        return f"[tool error] Path not found: {p}"
    if not p.is_dir():
        return f"[tool error] Not a directory: {p}"
    try:
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
    except PermissionError:
        return f"[tool error] Permission denied: {p}"
    lines = [f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries]
    result = "\n".join(lines[:200])
    if len(entries) > 200:
        result += f"\n...[{len(entries) - 200} more entries]"
    return result or "[tool] Directory is empty."


def _find_files(args: str) -> str:
    # Format: "<directory> <pattern>"  (pattern may contain spaces — we split on first space)
    parts = args.strip().split(None, 1)
    directory = Path(parts[0]).expanduser() if parts else Path(".")
    pattern = parts[1] if len(parts) > 1 else "*"
    matches: list[str] = []
    try:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if fnmatch.fnmatch(fname, pattern):
                    matches.append(os.path.join(root, fname))
                    if len(matches) >= 500:
                        break
            if len(matches) >= 500:
                break
    except PermissionError as e:
        return f"[tool error] {e}"
    if not matches:
        return f"[tool] No files matching '{pattern}' found under {directory}"
    return "\n".join(matches[:500])


async def run_read_file(args: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _read_file, args)


async def run_write_file(args: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _write_file, args)


async def run_list_dir(args: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _list_dir, args)


async def run_find_files(args: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _find_files, args)


# ── Registration ──────────────────────────────────────────────────────────────

register(ToolDef(
    name="read_file",
    category="filesystem",
    description="Read the contents of a file",
    args_spec="<path>",
    runner=run_read_file,
    safety="read",
    keywords={"read file", "open file", "file contents", "show file", "cat", "view file"},
))

register(ToolDef(
    name="write_file",
    category="filesystem",
    description="Write content to a file (path on first line, content on subsequent lines)",
    args_spec="<path>\\n<content>",
    runner=run_write_file,
    safety="write",
    keywords={"write file", "save file", "create file", "output file"},
))

register(ToolDef(
    name="list_dir",
    category="filesystem",
    description="List files and directories at a path",
    args_spec="[path]",
    runner=run_list_dir,
    safety="read",
    keywords={"list directory", "list files", "ls", "dir", "folder contents"},
))

register(ToolDef(
    name="find_files",
    category="filesystem",
    description="Find files matching a glob pattern under a directory",
    args_spec="<dir> <pattern>",
    runner=run_find_files,
    safety="read",
    keywords={"find files", "search files", "glob", "locate file", "find *.py"},
))
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd backend && python -m pytest tests/test_tools.py::TestFilesystemTools -v 2>&1 | tail -10
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools/filesystem.py backend/tests/test_tools.py
git commit -m "feat: add filesystem agent tools (read_file, write_file, list_dir, find_files)"
```

---

## Task 2: Shell Tool

**Files:**
- Create: `backend/agent/tools/shell.py`
- Test: `backend/tests/test_tools.py` (append)

- [ ] **Step 1: Write failing tests for run_shell**

Append to `backend/tests/test_tools.py`:

```python
class TestShellTool:

    @pytest.mark.asyncio
    async def test_shell_echo(self):
        from agent.tools.shell import run_shell
        result = await run_shell("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_shell_timeout(self):
        import sys
        from agent.tools.shell import run_shell
        # Cross-platform sleep that exceeds the 30s timeout
        cmd = f"{sys.executable} -c \"import time; time.sleep(99)\""
        result = await run_shell(cmd)
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_shell_empty_args(self):
        from agent.tools.shell import run_shell
        result = await run_shell("")
        assert "[tool error]" in result

    def test_shell_registered(self):
        # NOTE: This test requires Task 3 Step 1 (_CATEGORY_MODULES update) to pass
        # if run via the module-level ensure_all(). Running the import directly works
        # without Task 3 because registration fires on import.
        from agent.tools.shell import run_shell  # noqa: F401 — triggers registration
        from agent.tools import TOOL_REGISTRY
        assert "run_shell" in TOOL_REGISTRY
        assert TOOL_REGISTRY["run_shell"].safety == "dangerous"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_tools.py::TestShellTool -v 2>&1 | tail -10
```
Expected: `ImportError: cannot import name 'run_shell'`

- [ ] **Step 3: Implement shell.py**

Create `backend/agent/tools/shell.py`:

```python
"""
Shell tool: run_shell — execute arbitrary shell commands.

Safety level: DANGEROUS. Only active when get_shell_tool_enabled() returns True.
The dispatch() function in registry.py enforces this gate — it blocks tools with
safety="dangerous" unless allow_dangerous=True is passed explicitly.
"""
from __future__ import annotations
import asyncio
import subprocess
import sys

from agent.tools.registry import register, ToolDef, MAX_OUTPUT

_SHELL_TIMEOUT = 30  # seconds


def _run_shell_sync(command: str) -> str:
    if not command.strip():
        return "[tool error] No command provided."
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SHELL_TIMEOUT,
        )
        output = (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return f"[tool error] Command timed out after {_SHELL_TIMEOUT}s."
    except Exception as exc:
        return f"[tool error] {exc}"

    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + f"\n...[truncated — {len(output)} chars total]"
    return output or "[tool] Command produced no output."


async def run_shell(args: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_shell_sync, args)


# ── Registration ──────────────────────────────────────────────────────────────

register(ToolDef(
    name="run_shell",
    category="shell",
    description="Run any shell command (requires Shell Tool enabled in chat settings)",
    args_spec="<command>",
    runner=run_shell,
    safety="dangerous",
    keywords={
        "run command", "shell", "execute", "bash", "powershell", "cmd",
        "command line", "terminal", "script", "run script",
    },
))
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd backend && python -m pytest tests/test_tools.py::TestShellTool -v 2>&1 | tail -10
```
Expected: 4 passed
Note: `test_shell_registered` passes because the import triggers registration. It does NOT need `_CATEGORY_MODULES` to be updated first.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools/shell.py backend/tests/test_tools.py
git commit -m "feat: add run_shell agent tool (safety=dangerous, off by default)"
```

---

## Task 3: Register Modules + Shell Gate + Config + Chat Wiring

**Files:**
- Modify: `backend/agent/tools/__init__.py`
- Modify: `backend/agent/tools/registry.py`
- Modify: `backend/config.py`
- Modify: `backend/agent/chat.py`
- Modify: `backend/api/routes.py`

- [ ] **Step 1: Add to _CATEGORY_MODULES and CATEGORY_KEYWORDS in `__init__.py`**

In `backend/agent/tools/__init__.py`, add to `_CATEGORY_MODULES` dict:
```python
"filesystem":  "agent.tools.filesystem",
"shell":       "agent.tools.shell",
```

Add to `CATEGORY_KEYWORDS` dict:
```python
"filesystem": {
    "read file", "write file", "list directory", "find files",
    "open file", "file contents", "save file", "cat", "ls", "dir",
},
"shell": {
    "run command", "shell", "execute", "bash", "powershell",
    "cmd", "terminal", "script", "run script",
},
```

- [ ] **Step 2: Add categories to `_CATEGORY_ORDER` in `registry.py`**

In `backend/agent/tools/registry.py`, change:
```python
_CATEGORY_ORDER = ["network", "system", "analysis", "rag", "modbus", "ics", "workflow", "trafficmap", "meta"]
```
to:
```python
_CATEGORY_ORDER = ["network", "filesystem", "shell", "system", "analysis", "rag", "modbus", "ics", "workflow", "trafficmap", "meta"]
```

- [ ] **Step 3: Add startup default to `config.py`**

In `backend/config.py`, add inside the `Settings` class (startup default only — runtime state lives in chat.py):
```python
allow_shell_tool: bool = Field(default=False, description="Startup default for shell tool enabled state")
```

- [ ] **Step 4: Add shell gate module-level state to `chat.py`**

Follow the exact pattern of `_thinking_enabled` in `llm_client.py`. In `backend/agent/chat.py`, near the top of the file (after imports), add:

```python
# ── Shell tool gate (mirroring _thinking_enabled in llm_client.py) ─────────────
from config import settings as _settings

_shell_tool_enabled: bool = _settings.allow_shell_tool  # initialise from config


def get_shell_tool_enabled() -> bool:
    return _shell_tool_enabled


def set_shell_tool_enabled(value: bool) -> None:
    global _shell_tool_enabled
    _shell_tool_enabled = value
```

Then find the two `dispatch(name, args)` calls (lines ~379 and ~489) and change BOTH to:
```python
result = await dispatch(name, args, allow_dangerous=_shell_tool_enabled)
```
Note: `settings` is already imported at top of `chat.py` — do NOT add a second import. Use `_shell_tool_enabled` directly (the module-level variable, not settings).

- [ ] **Step 5: Add toggle endpoints to `routes.py`**

In `backend/api/routes.py`, add a `ShellToolRequest` model and two endpoints after the existing `/llm/thinking` endpoints. Use the accessor functions from `chat.py` (same as thinking uses `llm_client`):

```python
class ShellToolRequest(BaseModel):
    enabled: bool

@router.get("/agent/shell-tool")
async def get_shell_tool_endpoint():
    """Return current shell tool enabled state."""
    from agent.chat import get_shell_tool_enabled
    return {"enabled": get_shell_tool_enabled()}

@router.post("/agent/shell-tool")
async def set_shell_tool_endpoint(req: ShellToolRequest):
    """Enable or disable the run_shell agent tool for this session."""
    from agent.chat import set_shell_tool_enabled
    set_shell_tool_enabled(req.enabled)
    return {"enabled": req.enabled}
```

- [ ] **Step 6: Verify tools load + appear in LLM prompt**

```bash
cd backend && python -c "
from agent.tools import ensure_all, TOOL_REGISTRY
ensure_all()
# Check registration
fs = [n for n, t in TOOL_REGISTRY.items() if t.category in ('filesystem','shell')]
print('Registered:', sorted(fs))

# Check they appear in L1 prompt (build_tool_names)
from agent.tools.registry import build_tool_names
names_prompt = build_tool_names()
for name in ['read_file', 'write_file', 'list_dir', 'find_files', 'run_shell']:
    status = 'OK' if name in names_prompt else 'MISSING'
    print(f'  L1 prompt: {name} -> {status}')
"
```
Expected output:
```
Registered: ['find_files', 'list_dir', 'read_file', 'run_shell', 'write_file']
  L1 prompt: read_file -> OK
  L1 prompt: write_file -> OK
  L1 prompt: list_dir -> OK
  L1 prompt: find_files -> OK
  L1 prompt: run_shell -> OK
```

- [ ] **Step 7: Run full test suite**

```bash
cd backend && python -m pytest tests/ -q --tb=short 2>&1 | tail -10
```
Expected: all pass (or same failures as baseline — zero new failures)

- [ ] **Step 8: Commit**

```bash
git add backend/agent/tools/__init__.py backend/agent/tools/registry.py \
        backend/config.py backend/agent/chat.py backend/api/routes.py
git commit -m "feat: register filesystem+shell tools, shell gate accessors, API toggle endpoints"
```

---

## Task 4: Frontend Shell Toggle

**Files:**
- Modify: `frontend/src/store/useStore.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/ChatBox.tsx`

- [ ] **Step 1: Add shellToolEnabled to Zustand store (`useStore.ts`)**

In `frontend/src/store/useStore.ts`, mirror the `thinkingEnabled` entries:

In the state interface, add alongside `thinkingEnabled`:
```typescript
shellToolEnabled: boolean;
setShellToolEnabled: (v: boolean) => void;
```

In the `create()` initializer, add alongside `thinkingEnabled: false`:
```typescript
shellToolEnabled: false,
setShellToolEnabled: (v) => set({ shellToolEnabled: v }),
```

- [ ] **Step 2: Add API helpers to `api.ts`**

In `frontend/src/lib/api.ts`, after the existing thinking helpers, add:

```typescript
export const getShellTool = () =>
  api.get<{ enabled: boolean }>('/agent/shell-tool').then(r => r.data)

export const setShellTool = (enabled: boolean) =>
  api.post<{ enabled: boolean }>('/agent/shell-tool', { enabled }).then(r => r.data)
```

- [ ] **Step 3: Add shell toggle button to `ChatBox.tsx`**

Find the Thinking toggle button in `ChatBox.tsx`. It uses `thinkingEnabled` from the store and calls `setThinking()`. Add the shell toggle immediately alongside it.

Add imports at the top of the file (with existing imports):
```typescript
import { getShellTool, setShellTool } from '../lib/api'
```

Inside the component, alongside the thinking state:
```typescript
const { shellToolEnabled, setShellToolEnabled } = useStore()

const toggleShellTool = async () => {
  const next = !shellToolEnabled
  try {
    await setShellTool(next)
    setShellToolEnabled(next)
  } catch {
    // backend not ready — ignore
  }
}
```

Add re-sync in the backend restart handler (find the existing `getThinking().then(...)` call and add the shell sync right after it):
```typescript
getShellTool().then(r => setShellToolEnabled(r.enabled)).catch(() => {})
```

Add the button in the header, next to the thinking toggle:
```tsx
<button
  onClick={toggleShellTool}
  title={shellToolEnabled ? "Shell tool ON — agent can run commands (click to disable)" : "Enable shell tool"}
  className={`p-1.5 rounded transition-colors ${
    shellToolEnabled
      ? 'text-orange-400 bg-orange-400/10'
      : 'text-[#8b949e] hover:text-[#c9d1d9]'
  }`}
>
  <TerminalSquare className="w-4 h-4" />
</button>
```

Add `TerminalSquare` to the lucide-react import at the top of the file.

- [ ] **Step 4: Also fetch shell state on mount**

In the same component, in the `useEffect` that fetches initial state (where `getThinking()` is called on mount), add:
```typescript
getShellTool().then(r => setShellToolEnabled(r.enabled)).catch(() => {})
```

- [ ] **Step 5: Build frontend**

```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in X.XXs`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/useStore.ts frontend/src/lib/api.ts \
        frontend/src/components/ChatBox.tsx
git commit -m "feat: shell tool toggle in chat header, wired to Zustand store"
```

---

## Verification

**1. All 5 tools registered and appear in LLM prompt:**
```bash
curl -s http://127.0.0.1:8000/api/tools | python -c "
import sys, json
tools = [t for t in json.load(sys.stdin) if t['category'] in ('filesystem','shell')]
for t in tools:
    print(t['name'], t['safety'])
"
```
Expected:
```
find_files read
list_dir read
read_file read
run_shell dangerous
write_file write
```

**2. Shell blocked by default:**
```bash
curl -s http://127.0.0.1:8000/api/agent/shell-tool
# → {"enabled": false}
```

**3. Shell works when enabled:**
```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/shell-tool \
  -H "Content-Type: application/json" -d '{"enabled":true}'
# → {"enabled": true}
# Then ask agent: "run the command: echo hello from shell"
# Expected in reply: "hello from shell"
```

**4. Filesystem works without enabling shell:**
Ask agent: `"read the file C:/Users/ffd/Documents/netscope-desktop/README.md"`
Expected: agent calls `TOOL: read_file` and returns README contents.

**5. write_file uses newline format:**
Ask agent: `"create a file at C:/tmp/test.txt with the content: hello agent"`
Expected: agent calls `TOOL: write_file C:/tmp/test.txt\nhello agent`
