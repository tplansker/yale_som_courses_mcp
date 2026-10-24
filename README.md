<p align="center">
  <img src="docs/handsome-dan.svg" alt="A row of seven rainbow-colored Handsome Dan bulldogs in Yale-blue bandanas" width="720">
</p>

<h1 align="center">Yale SOM Course Explorer (MCP)</h1>

<p align="center">
  Same Yale SOM course explorer as before — browse courses as cards, chat with the assistant —
  but the catalogue tools now live in a small <strong>FastMCP server</strong> under <code>mcp/</code>.
</p>

---

## What’s the same / what’s new

**Same as the Lecture 8 course explorer**

- Glass course cards for every Yale SOM course
- Search and category filters
- Chat assistant in the bottom-right corner
- React + FastAPI + Portkey (`gpt-5.6-luna` by default)

**New for Lecture 9 (MCP)**

- `mcp/mcp_server.py` — FastMCP server in its own folder (own `requirements.txt` + venv)
- Starter ships with a placeholder tool (`yo`) — add real catalogue tools in class that read `data/yale_som.db`
- The chat agent attaches that server with `MCPToolset` **in-process** (same Python as FastAPI — you do **not** start a second MCP terminal for the web app)
- Local catalogue tools in `backend/tools.py` are empty — course facts come from MCP only

---

## Project layout

```
.
├── .env.example
├── data/
│   ├── yale_som_classes.json
│   └── yale_som.db          # not in git — see Setup
├── mcp/
│   ├── mcp_server.py        # FastMCP catalogue tools
│   └── requirements.txt     # fastmcp (make a venv here for vibe-coder / stdio)
├── backend/
│   ├── main.py
│   ├── agent.py             # MCPToolset → mcp/mcp_server.py (in-process)
│   ├── tools.py             # stub (tools live on MCP)
│   ├── models.py
│   ├── prompts/prompt.md
│   └── requirements.txt
├── frontend/
└── output/audit_trail.json
```

---

## Setup

You need **Python 3.12+**, **Node.js 20+**, and a **Portkey API key**.

**1. API key.** Copy `.env.example` to `.env` and fill in:

```
PORTKEY_API_KEY=your-portkey-api-key-here
```

Never commit the real `.env`.

**2. Course database.** Put `yale_som.db` in `data/` (Lecture 8 `data.zip` if you don’t have it). Cards still load from `yale_som_classes.json`; the MCP tools need the SQLite file.

**3. Backend** (chat app — includes `fastmcp` so in-process MCP works):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**4. MCP folder** (for connecting Claude / Cursor / vibe coder via stdio — own venv):

```powershell
cd mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**5. Frontend:**

```powershell
cd frontend
npm install
```

---

## Running the app

**Terminal 1 — backend** (start first). Do **not** need to run `mcp_server.py` separately — the agent imports it:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --port 8000
```

**Terminal 2 — frontend:**

```powershell
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173**. API docs: **http://127.0.0.1:8000/docs**.

### Connect the MCP to your vibe coder (stdio)

Point the MCP config at the **mcp venv’s Python** and `mcp/mcp_server.py` (full paths on your machine):

```json
{
  "mcpServers": {
    "yale-som-courses": {
      "command": "C:/Users/you/yale_som_courses_mcp/mcp/.venv/Scripts/python.exe",
      "args": [
        "C:/Users/you/yale_som_courses_mcp/mcp/mcp_server.py"
      ]
    }
  }
}
```

Your vibe coder launches that process — it needs the `mcp/.venv` packages (`fastmcp`). That is separate from running the web app.

For **Claude Code**, put that config in `.mcp.json` at the project root. Servers there load for this project only; Claude asks you to approve them the first time.

### Adding another MCP server (e.g. Outlook)

Give each server its own folder and venv under `mcp/`, then add a second entry to `.mcp.json` next to `yale-som-courses`:

```
mcp/
├── mcp_server.py      # yale-som-courses
├── .venv/
└── outlook/
    ├── outlook_server.py
    ├── requirements.txt
    └── .venv/
```

```json
"outlook": {
  "command": "<project>/mcp/outlook/.venv/bin/python",
  "args": ["<project>/mcp/outlook/outlook_server.py"]
}
```

Keep Outlook credentials in `.env`, never in `.mcp.json`.

### Optional: run the MCP server alone

```powershell
cd mcp
.\.venv\Scripts\Activate.ps1
python mcp_server.py
python mcp_server.py --http
```

HTTP URL: `http://127.0.0.1:8001/mcp`

---

## API

| Method | Route | What it does |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/courses?q=...` | All courses, optional text filter |
| `POST` | `/api/chat` | `{"message": "..."}` → reply + `tools_used` |

---

## Notes

- **Budget.** Use `gpt-5.6-luna` via Portkey for class. Override with `MODEL_NAME` in `.env` if needed.
- **Handsome Dan.** If you edit the mascot component, regenerate the README banner:

  ```powershell
  cd frontend
  node render-dan.mjs
  ```
