# GoGlobal Intelligence v5.4.0

Build: `v540-20260831-advanced-decision-analytics-r2`

## Advanced decision analytics

### 1. Pareto multi-objective market screening
- Fast non-dominated sorting with multiple Pareto fronts.
- User-selectable maximize/minimize objectives.
- Crowding distance and dominance explanations.
- Designed to avoid opaque single-score weighting.

### 2. Profit uncertainty simulation
- Monte Carlo and Latin Hypercube Sampling.
- Uniform, triangular, and normal uncertainty inputs.
- Quantiles, loss probability, target-margin probability, and downside CVaR.
- Scrambled Sobol global sensitivity analysis with first-order and total-effect indices.

### 3. Product-market resource optimization
- MILP allocation across product × market opportunities.
- Budget, product, market, capacity, risk, mandatory-entry, and exclusion constraints.
- Revenue, nominal profit, and robust-profit objectives.
- Bertsimas-Sim budgeted uncertainty with configurable Gamma.

### 4. Hybrid HS candidate ranking
- BM25 lexical retrieval.
- Local dense embedding built from deterministic word/bigram and character n-gram feature hashing.
- Negation-aware classification features and numeric HS-prefix handling.
- Pairwise logistic Learning-to-Rank trained from confirmed HS selections.
- High-recall candidate pool combining sparse, dense, and learned ranking signals.

### 5. Global trade-network supply-risk analytics
- HS6 bilateral trade graph construction.
- Supplier share, CR3, HHI, market reach, and weighted betweenness.
- Systemic supplier exposure and supplier-removal stress tests.
- Interactive supply-network and structural-vulnerability views.

## Validation
- Backend regression suite: 122 passed.
- HS hybrid ranking tests: 4 passed, including cold-start BM25+dense retrieval and pairwise Learning-to-Rank.
- Advanced analytics tests: 4 passed.
- Python compileall: passed.
- Frontend JS/JSX/MJS parse check: 22 files passed.
- Frontend relative-import check: 0 missing.
- macOS shell syntax checks: passed.
- API smoke test: `/api/health` returned 200 with version 5.4.0 and the expected build ID.

The release package intentionally excludes `.env`, user databases, virtual environments, `node_modules`, `dist`, caches, and local validation markers.

## macOS startup reliability patch
- Bypass HTTP/VPN proxies for localhost readiness checks.
- Rebuild broken virtual environments whose base Python was removed.
- Dependency cache marker now follows requirements.txt content.
- Start backend with an absolute interpreter path.
- Parse health JSON instead of matching raw JSON text.
- Extend first-start readiness window to 90 seconds for scientific Python imports.
- Persist backend startup logs and print the traceback immediately on failure.
