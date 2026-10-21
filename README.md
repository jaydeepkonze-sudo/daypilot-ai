# DayPilot AI — no paid API key required

## Real AI setup (Windows)
1. Install **Ollama** from https://ollama.com/download/windows (third-party software; verify the official site).
2. Open a new terminal and run: `ollama pull qwen2.5:3b` (requires internet once and several GB of disk space; exact size depends on the model).
3. Make sure Ollama is running. On Windows the Ollama desktop app normally starts the local server; alternatively run `ollama serve` if needed.
4. Launch `START_WINDOWS.bat`, open http://localhost:8765, and click **Refresh AI**.
5. When **Local AI ready** appears, **Use real local AI** is enabled. Ask any productivity question, or ask it to use task tools.

Without Ollama, the app still runs in Offline commands mode (rule-based, not real AI). No API key is bundled or needed. AI runs on **your own computer**; slower PCs may respond slowly or lack enough memory. The model itself is **not included in this ZIP**. First downloads require internet. Ollama local API: http://localhost:11434.

This includes a working MCP HTTP endpoint at /mcp. It does **not** mean Alexa+ devices or Amazon-hosted agents are connected. To submit a hosted version, arrange secure hosting and demonstrate your own integration. Do not expose the local MCP interface or SQLite data publicly without adding auth.

# DayPilot AI — Alexa+ Track Hackathon Prototype

A working productivity planner with a polished browser simulator and a **real self-hosted MCP server** using JSON-RPC over Streamable HTTP (`2025-11-25`). The assistant is **deterministic and tool-backed**, not a large-language-model chatbot; there is **no connection to the restricted official Alexa+ toolkit**.

## Quick start (Windows, Mac, Linux)

1. Install Python 3.10+ (no pip dependencies required).
2. Unzip this folder and open a terminal **inside** `DayPilot_AI_Hackathon`.
3. Run `python server.py` (Windows may need `py server.py`).
4. Open **http://localhost:8765** in Chrome or Edge. **Do not double-click index.html**; the server must be running.
5. Press **Load demo scenario**, test the buttons, then ask `Add finish presentation high priority for 45 minutes`, `Plan my day`, `What should I focus on?`, `How am I doing?`.
6. Click **Check MCP connection** to validate JSON-RPC initialize and tools/list via HTTP.

## Features

- Responsive dashboard, task completion/deletion, priorities, durations, focus timeline and breaks.
- Ask DayPilot local natural language parser (specific intents; not general AI Q&A).
- Voice-to-text in supported browsers (requires permission; support varies by OS/browser and may depend on browser services).
- Persistent SQLite database created locally at `daypilot.db`.
- Real `/mcp` JSON-RPC endpoint supporting `initialize`, `ping`, `tools/list`, `tools/call`, and tool change/other notifications with 202 Accepted.
- Tools: `add_task`, `list_tasks`, `complete_task`, `delete_task`, `plan_day`, `get_progress`.

## Example MCP requests

```bash
curl -X POST http://localhost:8765/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-11-25' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"demo","version":"1"}}}'
curl -X POST http://localhost:8765/mcp -H 'Content-Type: application/json' -H 'MCP-Protocol-Version: 2025-11-25' -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

## Tests

Run `python -m unittest discover -s tests -v` from this directory. Test results and limitations are in `TEST_REPORT.md`.

## Hackathon submission is NOT the ZIP alone

The official Devpost rules require the source repository, demo video, project description and product feedback, not merely a ZIP upload. To submit: create a GitHub repository, deploy this server on a publicly accessible HTTPS host **with appropriate access controls**, record a real video showing MCP and UI, and add project feedback. Devpost also requires ongoing availability during judging. This localhost demo is **not itself publicly hosted**.

## Security

This prototype serves unauthenticated task APIs and `/mcp` endpoint, suitable for **localhost demo only**. Do not publicly expose it without authentication, abuse protection, and deployment hardening. It stores only task titles in a local SQLite database. The Google font CDN is optional (falls back to local sans-serif). No API keys required.

## Disclosures

“Alexa+” and “Amazon” refer to the hackathon track, not a live integration or Amazon endorsement. The official Alexa+ add-on developer toolkit is restricted for hackathon participants; self-hosted MCP + web simulator is the supported route.
