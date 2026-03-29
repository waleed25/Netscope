# NetScope Architecture Refactor Handoff

**To the Next Agent / UI Developer:**

The backend architecture transition is strictly completed and tested. We have moved from a legacy monolithic app to a 3-process architecture:
- `gateway/`: Lightweight FastAPI proxy running on port 8000 handling WebSockets and HTTP routes.
- `engine/`: Handles LLM inference and heavy CPU-bound Python analytics.
- `daemon/`: Handles packet capture via Npcap and escalated Modbus tools.

## Key Notes You Must Know:
1. **Frontend Vite Setup:** The vite server `vite.config.ts` was updated to securely proxy `/api` to `localhost:8000`. If you are restarting the UI using `npm run dev -- --host`, this configuration is already applied. Wait for the Electron `node_modules\.bin\electron .` sequence to fully provision the background gateway before polling UI data.
2. **Daemon Privilege Escalation:** When NetScope is packaged (Production mode), the `electron/main.js` correctly triggers Windows UAC prompt for Daemon isolation via `Start-Process -Verb RunAs`. In development, you still need to run Electron from an Admin terminal if you want Npcap to bind raw packets successfully! 
3. **In-Memory State:** `api.routes.py` has been completely stripped of its internal packet variables. It now imports dependencies lazily directly connecting to the Redis Sub stream (`shared/bus.py`). Do not initialize monolithic capture flags globally in the UI anymore, rely entirely on the proxy events.

The multi-process architecture is solid. You can safely proceed with UI React visual upgrades or further functional features.
