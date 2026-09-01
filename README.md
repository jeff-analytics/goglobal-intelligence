# GoGlobal Intelligence

**AI-Powered Market Entry & Profitability Intelligence**

GoGlobal Intelligence is a bilingual decision-intelligence application for evaluating product-market opportunities with structured trade evidence, tariff and tax research, marketplace signals, unit economics, and agentic web research.

The product combines deterministic calculations with source-backed AI research. AI-generated evidence and recommendations remain visibly separated from user-entered assumptions and confirmed data.

**Current release:** `v5.4.1`

[中文说明](README.zh-CN.md) · [Changelog](CHANGELOG.md) · [Documentation](docs/README.md)

## What it does

- **Project setup** — product, origin, HS/customs classification, destination markets and marketplace category.
- **Market scan** — compare selected markets using trade evidence and market readiness signals, then run non-dominated sorting for Pareto multi-objective screening.
- **Trade & supply research** — UN Comtrade demand, origin share, supplier concentration, CR3/CR5/HHI and trade history.
- **Tariff & tax research** — HS6 tariff references, official-source evidence, VAT/GST and reusable tariff matrices.
- **Marketplace research** — eBay taxonomy, listing research, comparable filtering and benchmark observations.
- **Cost & margin** — configurable product economics, reverse pricing, Monte Carlo / Latin Hypercube uncertainty simulation and Sobol sensitivity analysis.
- **Decision cases** — deterministic market-entry cases built from available evidence and economics.
- **Decision Research Agent** — bilingual, source-aware research synthesis with market, pricing, risk, source and action views.
- **Portfolio analysis** — compare multiple product-market opportunities and solve MILP / budgeted robust resource-allocation plans.
- **HS ranking** — hybrid BM25 + local dense embedding candidate retrieval with negation-aware features and pairwise Learning-to-Rank from confirmed selections.
- **Supply network risk** — graph-based supplier concentration, market reach, betweenness and supplier-removal stress tests from observed bilateral trade.

## Decision workflow

```text
Product Setup
    ↓
Market Scan + Pareto Screening
    ↓
Trade & Supply + Network Risk
    ↓
Tariff / Tax / FX
    ↓
Marketplace Research
    ↓
Cost & Margin + LHS / Sobol
    ↓
Decision Case
    ↓
Decision Research Agent
    ↓
Portfolio MILP / Robust Optimization
```

## Design principles

1. **Deterministic first** — margins, pricing, concentration and decision metrics are calculated by application logic.
2. **Evidence provenance** — source-backed external evidence keeps its URL, retrieval context and status.
3. **User data priority** — confirmed classifications, uploaded observations, costs and manual overrides are not silently replaced by AI.
4. **Visible uncertainty** — missing, provisional or conflicting evidence remains visible.
5. **Provider flexibility** — model reasoning and web research are configured separately.
6. **Local-first runtime** — the application runs locally on Windows and macOS with SQLite persistence.

## Data and AI integrations

| Area | Supported source / provider |
| --- | --- |
| Trade | UN Comtrade |
| Tariff reference | UNCTAD TRAINS / WITS and official local sources |
| FX | ECB |
| Marketplace | eBay Taxonomy / Browse APIs |
| AI models | DeepSeek, OpenAI, Anthropic, Gemini, compatible custom endpoints |
| Web research | Provider-native search, Tavily, or offline mode |

External services are optional. Core project storage and deterministic calculations remain available without an AI provider.

## Tech stack

- **Frontend:** React 19, Vite 8, Recharts, Lucide
- **Backend:** FastAPI, Pydantic, Uvicorn
- **Storage:** SQLite
- **Analytics:** NumPy, SciPy/HiGHS, scikit-learn, NetworkX
- **Data processing:** Python, requests, openpyxl
- **Testing:** pytest + production frontend build validation
- **Runtime:** Windows and macOS

## Quick start

### Requirements

- Node.js **22.12+**
- Python **3.11+**; Python 3.12 is recommended
- npm

### Windows

```text
1. Clone or extract the repository.
2. Run run_win.bat.
3. GoGlobal Intelligence opens at http://127.0.0.1:5173.
```

The starter creates the local Python environment, installs dependencies, validates the frontend production build, prepares ports 8000/5173 and launches the API and UI.

### macOS

```bash
chmod +x run_mac.command
./run_mac.command
```

The macOS starter supports both Intel and Apple Silicon. Press `Ctrl+C` once in the starter terminal to stop both services.

### Migrate an existing V5.3.x installation

Windows:

```text
scripts/windows/migrate_from_existing.bat
```

macOS:

```bash
chmod +x scripts/macos/migrate_from_existing.command
./scripts/macos/migrate_from_existing.command
```

Migration copies local configuration, SQLite data and reusable caches. It does not copy virtual environments or `node_modules`.

## Configuration

Copying `.env.example` to `.env` is handled automatically by the local starters. API keys can also be configured from **Data Sources** inside the application.

Do not commit `.env`, local databases, virtual environments, caches or generated build output. These paths are excluded through `.gitignore`.

## Repository structure

```text
GoGlobal Intelligence/
├── backend/                 FastAPI application, engines and tests
├── frontend/                React/Vite application
├── docs/                    Product and methodology documentation
├── scripts/
│   ├── macos/               Migration and self-check tools
│   └── windows/             Migration, repair and runtime helpers
├── .github/workflows/       CI validation
├── .env.example             Configuration template
├── docker-compose.yml       Container entry point
├── run_mac.command          macOS one-command starter
├── run_win.bat              Windows one-command starter
├── CHANGELOG.md
├── SECURITY.md
└── VERSION
```

## Validation

After local dependencies are installed:

Windows:

```text
scripts/windows/self_check.bat
```

macOS:

```bash
./scripts/macos/self_check.command
```

The check runs the backend pytest suite and the frontend production build.

## Security

Secrets belong in `.env` or the local configuration UI. See [SECURITY.md](SECURITY.md) before publishing a fork or sharing logs.

## Versioning

Repository folders stay version-neutral. Releases are tracked with Git tags such as `v5.4.1` and documented in [CHANGELOG.md](CHANGELOG.md).
