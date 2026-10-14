# ResearchPilot AI

**Multi-Agent Research & Intelligence Workspace** — a full-stack portfolio project that coordinates specialist AI roles to investigate a question, collect public web evidence, compare findings, review claims, and produce a traceable Markdown research brief.

> ResearchPilot is a learning and research-assistance tool. Search snippets may be incomplete and LLM-based verification is not proof of correctness. Independently verify important claims.

## Features

- **Multi-agent orchestration:** Planner → Search Agent → Research Agent → Analyst Agent → Verifier Agent → Writer Agent.
- **Live execution trace:** Server-Sent Events (SSE) stream real stage updates and elapsed timings to the frontend.
- **Evidence collection:** DuckDuckGo search results with source title, URL, domain, and bounded snippets.
- **Evidence-aware synthesis:** prompts require source labels (`[S1]`, `[S2]`), uncertainty, limitations, and no invented sources.
- **Source metrics:** source count, distinct domains, usable-snippet coverage, depth, and duration. These are heuristic metrics, not source-truth scores.
- **Research memory:** recent saved investigations provide a short contextual hint to the planner.
- **Authentication:** account registration/login, salted PBKDF2 password hashes, signed expiring HS256 bearer tokens.
- **Workspaces:** create and select workspaces; delete a workspace without deleting its saved research.
- **Persistent reports:** PostgreSQL stores reports, plans, evidence, agent events, analysis, verifier review, metrics, and private notes.
- **Research history:** search and filter saved investigations, reopen complete reports, and delete reports.
- **Report tools:** export Markdown, copy report, edit/save private research notes.
- **Token-conscious prompts:** limited search results, clipped snippets and intermediate outputs, bounded completion lengths, and friendly Groq rate-limit errors.
- **Responsive UI:** React + TypeScript workspace with mobile layout, live progress, history, report details, and source links.

## Stack

- Frontend: React 18, Vite, TypeScript, React Markdown, Lucide
- Backend: Python 3.11+, FastAPI, Pydantic
- LLM: Groq API (select a model enabled for your account)
- Web search: `ddgs`
- Persistence: PostgreSQL + SQLAlchemy
- Auth: PBKDF2-HMAC-SHA256 password hashing and signed HS256 session tokens using Python standard library

## Prerequisites

1. Python 3.11 or newer
2. Node.js 20 or newer and npm
3. PostgreSQL running locally or a PostgreSQL connection URL
4. A Groq API key from <https://console.groq.com/keys>
5. A Groq model available to your account: <https://console.groq.com/docs/models>

## 1. PostgreSQL setup

Open SQL Shell (`psql`) or pgAdmin's query tool and run the following, changing the password:

```sql
CREATE USER researchpilot WITH PASSWORD 'replace_with_a_strong_local_password';
CREATE DATABASE researchpilot OWNER researchpilot;
```

If the role or database already exists, skip the corresponding `CREATE` statement. Do not put angle brackets around the password. The database URL must use the same password.

## 2. Backend setup (Windows PowerShell)

Open PowerShell in the extracted `ResearchPilot-AI` directory:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `backend/.env` and set the values:

```dotenv
GROQ_API_KEY=your_actual_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
DATABASE_URL=postgresql+psycopg://researchpilot:YOUR_PASSWORD@localhost:5432/researchpilot
JWT_SECRET=replace_with_a_random_secret_at_least_32_characters_long
JWT_EXPIRE_HOURS=72
FRONTEND_ORIGIN=http://localhost:5173
MAX_SEARCH_RESULTS=4
```

- Replace `YOUR_PASSWORD` with the PostgreSQL role password. URL-encode special characters in a database password (or use a simple strong local development password).
- Keep `GROQ_MODEL` set to a model available in your Groq console. If this model is unavailable to your account, choose another active model from the catalog.
- Generate a strong `JWT_SECRET` in PowerShell with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the output into `.env`.
- Never commit `.env` or share the Groq key.

Start the API:

```powershell
uvicorn app.main:app --reload
```

Verify:

- Health: <http://127.0.0.1:8000/api/health>
- Swagger API docs: <http://127.0.0.1:8000/docs>

The backend attempts to create tables on startup and includes an additive migration for the original MVP's `research_runs` table.

## 3. Frontend setup (second terminal)

From the project root:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open the local URL printed by Vite, normally <http://localhost:5173>. Create an account and sign in. Research reports are scoped to the signed-in user.

If the frontend and API are on different hosts, set `VITE_API_URL` in `frontend/.env` and set `FRONTEND_ORIGIN` in `backend/.env` to the frontend origin, then restart both services.

## Suggested demo question

> Compare multi-agent AI architectures for scientific research. Evaluate orchestration approaches, agent evaluation methods, limitations, and open research challenges.

Try `Quick scan` first on a low Groq tokens-per-minute limit. The deep-dive option runs the same sequence with more search queries, so the total usage will be higher. If Groq reports a TPM limit, wait for the provider's rate window to reset and retry; prompt clipping reduces request sizes but cannot increase your account's quota.

## API overview

All endpoints below except health, register, and login require `Authorization: Bearer <token>`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | API, database and configured model status |
| POST | `/api/auth/register` | Create account and first workspace |
| POST | `/api/auth/login` | Sign in and receive session token |
| GET | `/api/auth/me` | Current user |
| GET / POST | `/api/workspaces` | List or create workspaces |
| DELETE | `/api/workspaces/{id}` | Delete workspace, preserve reports |
| POST | `/api/research` | Run research and return final JSON result |
| POST | `/api/research/stream` | Run research with live SSE progress events |
| GET | `/api/research/history` | Search/filter saved research |
| GET | `/api/research/{id}` | Fetch complete saved report |
| PATCH | `/api/research/{id}/notes` | Save private report notes |
| DELETE | `/api/research/{id}` | Delete a saved report |

## Architecture

```text
React + TypeScript
   │ Bearer session / JSON / SSE
   ▼
FastAPI API ─── Auth + workspace ownership checks
   │
   ├─ Planner Agent ──► focused web queries
   ├─ Search Agent ───► public search snippets
   ├─ Research Agent ─► evidence synthesis with [S#] references
   ├─ Analyst Agent ──► themes, limitations, evidence gaps
   ├─ Verifier Agent ─► heuristic claim review against snippets
   └─ Writer Agent ───► Markdown research report
   │
   └─ SQLAlchemy ─────► PostgreSQL users, workspaces, research runs
```

## Portfolio-ready talking points

- Designed an auditable multi-agent orchestration pipeline with typed API contracts and real-time SSE progress.
- Implemented per-user report isolation, workspace ownership checks, signed expiring tokens, and salted password hashing.
- Built a token-conscious LLM pipeline using bounded evidence snippets, output limits, and graceful provider rate-limit errors.
- Persisted source evidence, execution trace, verifier output, metrics, and analyst notes for reproducibility.
- Developed a responsive TypeScript interface for research, history search, evidence inspection, report export, and note-taking.

## Known limitations and next production steps

- The verifier is another LLM pass, not an independent truth oracle. Source quality metrics are intentionally heuristic.
- Search uses public search snippets rather than crawling and extracting full pages. Availability and results can change.
- Research memory currently uses short excerpts from recent reports; it is not a vector database or long-term semantic memory.
- For a public production deployment, add email verification/password reset, refresh-token rotation, rate limiting, CSRF-aware deployment policy, structured logging/monitoring, migrations with Alembic, automated integration tests, and secret management.
- The token budget depends on the selected Groq model and account tier. Avoid running several investigations at once on a low TPM limit.
