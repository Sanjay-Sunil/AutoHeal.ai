# AutoHeal.ai — Autonomous API Remediation Middleware

AutoHeal.ai is a self-healing API integration middleware that autonomously detects, diagnoses, and fixes schema drift errors at runtime. When a third-party API changes its schema overnight, AutoHeal.ai intercepts the HTTP 400 error, uses a LangGraph agent powered by Google Gemini to generate a Python transformation patch, tests it in a sandboxed environment, verifies it via dry-run shadow execution, and opens a GitHub Pull Request — all with zero downtime.

---

## Architecture

```mermaid
flowchart TD
    subgraph Consumer Application
        A[User clicks Checkout] --> B[Send old payload to Vendor API]
    end

    subgraph Vendor API - mock_vendor.py
        B -->|POST /pay| C{Schema Valid?}
        C -->|Yes + X-Dry-Run| D[Return 200 - Dry Run Success]
        C -->|Yes - No header| E[Process Payment - Return 200]
        C -->|No| F[Return HTTP 400 - Schema Drift Error]
    end

    subgraph AutoHeal.ai Agent - aegis_agent.py
        F -->|Intercepted| G[Node 0: Fetch Vendor Docs - Mock Tool]
        G --> H[Node 1: LLM Diagnose - Gemini 2.5 Flash]
        H -->|Structured Output| I[Node 2: Sandbox Execution]
        I -->|Success| J[Node 3: Shadow Verification - Dry Run]
        I -->|Failed| H
        J -->|Vendor Accepts| K[Pipeline Healed]
        J -->|Vendor Rejects| H
    end

    subgraph Dashboard - dashboard.html
        K --> L[Stream Split-Pane Diffs via SSE]
        L --> M[User Reviews Schema + Code Diff]
        M --> N[Click Approve and Open PR]
    end

    subgraph GitOps - server.py
        N --> O[Create Branch on GitHub]
        O --> P[Push transform_payload code]
        P --> Q[Open Pull Request]
    end

    subgraph SQLite Audit Log - aegis_db.py
        F -.->|Log| R[(incidents table)]
        H -.->|Log| S[(agent_steps table)]
        Q -.->|Log| T[(pr_history table)]
    end
```

---

## Repository Structure

```
AutoHeal.ai/
├── backend/
│   ├── aegis_agent.py      # LangGraph agent: 4-node state machine (fetch_docs → diagnose → sandbox → verify)
│   ├── aegis_db.py          # SQLite audit log module (incidents, agent_steps, pr_history tables)
│   ├── server.py            # FastAPI dashboard server, SSE telemetry stream, GitOps PR endpoint
│   ├── dashboard.html       # React control plane frontend (split-pane diff viewer, incident log)
│   ├── product_backend.py   # Consumer app simulator — catches 400 errors and delegates to the agent
│   ├── mock_vendor.py       # Mock third-party API with strict schema validation + dry-run support
│   ├── test_llm.py          # Quick Gemini API connectivity check
│   ├── .env.example         # Template for environment secrets
│   └── .env                 # Your local secrets (git-ignored)
├── requirements.txt         # Python dependencies
├── .gitignore
└── README.md
```

---

## Setup Instructions

### Prerequisites

- **Python 3.10+**
- **Git**
- A [Google AI Studio](https://aistudio.google.com/apikey) API key (Gemini)
- A [GitHub Personal Access Token](https://github.com/settings/tokens) (for PR automation)

### 1. Clone and install

```bash
git clone https://github.com/Sanjay-Sunil/AutoHeal.ai.git
cd AutoHeal.ai
```

Create and activate a virtual environment:

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy the example env file and fill in your keys:

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```env
GEMINI_API_KEY="your-gemini-api-key"
GITHUB_TOKEN="your-github-personal-access-token"
GITHUB_REPO_NAME="your-username/your-target-repo"
```

| Variable | Required | Purpose |
|----------|----------|---------|
| `GEMINI_API_KEY` | **Yes** | Powers the LLM diagnosis and code generation |
| `GITHUB_TOKEN` | For PRs | Enables the "Approve & Open PR" GitOps feature |
| `GITHUB_REPO_NAME` | For PRs | Target repository for automated pull requests |

### 3. Run the system

You need **two terminals** running simultaneously:

**Terminal 1 — Mock Vendor API** (port 8000):
```bash
python backend/mock_vendor.py
```

**Terminal 2 — Dashboard Server** (port 8001):
```bash
cd backend
python server.py
```

### 4. Open the dashboard

Navigate to **http://127.0.0.1:8001/** in your browser.

---

## How It Works

### Step-by-step flow

1. **Click "Checkout & Pay"** — triggers a simulated API call with a deprecated payload (`{user_id, amount}`).
2. **HTTP 400 intercepted** — the mock vendor rejects it because it now expects `{transaction: {total_amount, user_uuid}}`.
3. **LangGraph agent activates** — a 4-node state machine runs autonomously:
   - **Node 0 (Tool):** Fetches vendor OpenAPI documentation
   - **Node 1 (LLM):** Gemini 2.5 Flash diagnoses the drift and generates a `transform_payload()` function with structured output (old/new schemas + old/new code)
   - **Node 2 (Sandbox):** Executes the generated code in a restricted Python scope
   - **Node 3 (Verify):** Replays the healed payload to the vendor via dry-run (`X-Dry-Run: true` + `Idempotency-Key`)
4. **Dashboard updates in real-time** via Server-Sent Events (SSE) — split-pane Schema Diff and Code Diff viewers.
5. **Click "Approve & Open PR"** — creates a GitHub branch and opens a Pull Request with the fix.

### Key features

| Feature | Description |
|---------|-------------|
| **Structured LLM Output** | Pydantic-enforced response: `reasoning`, `old_schema`, `new_schema`, `old_code`, `new_code` |
| **Shadow Verification** | Dry-run replay with idempotency headers — zero side effects |
| **Stack Trace Introspection** | Dynamically identifies the source file that initiated the API call via `traceback.extract_stack()` |
| **SQLite Audit Log** | Every incident, agent step, and PR is logged to `aegis_audit.db` |
| **Auto-Retry with Backoff** | Exponential backoff on Gemini 429 rate limits (up to 5 retries) |
| **Split-Pane Diff Dashboard** | Side-by-side schema and code comparison with syntax highlighting |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves the dashboard UI |
| `GET` | `/api/checkout-stream` | SSE stream of the full remediation workflow |
| `POST` | `/api/approve-pr` | Creates a GitHub branch and opens a PR with the generated patch |
| `GET` | `/api/incidents` | Lists recent incidents from the audit log |
| `GET` | `/api/incidents/{id}` | Full detail for a single incident (steps + PR history) |

---

## Tech Stack

- **Agent Framework:** [LangGraph](https://github.com/langchain-ai/langgraph) (state machine orchestration)
- **LLM:** [Google Gemini 2.5 Flash](https://ai.google.dev/) via LangChain
- **Backend:** [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn
- **Frontend:** React 18 (CDN) + Tailwind CSS + Prism.js (syntax highlighting)
- **Database:** SQLite (local audit log)
- **GitOps:** [PyGithub](https://pygithub.readthedocs.io/) for branch/PR creation

---

## License

MIT
