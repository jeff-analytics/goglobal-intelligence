# Changelog

## v5.4.1 — Advanced Algorithms + AI Provider Reliability

Build: `v541-20260901-algorithms-ai-config-r4`

- HS ranking cross-platform stability: deterministic dense feature-hash embeddings, deterministic pairwise LTR, explicit direct-support calibration, stable tie-breaking, and pinned analytical dependencies.

- Keeps the full V5.4 advanced analytics stack: Pareto non-dominated sorting, Monte Carlo/LHS/Sobol uncertainty analysis, MILP + Bertsimas-Sim robust allocation, hybrid HS BM25 + dense embedding + pairwise learning-to-rank, and global trade-network risk analysis.
- DeepSeek preset now uses the official Responses API with `https://api.deepseek.com` and canonical model ID `deepseek-v4-flash`.
- DeepSeek display-style model names such as `DeepSeek-V4-Flash` are normalized before model-list validation and persistence, preventing false “model not available” failures caused by capitalization or separator differences.
- Retains the hardened macOS startup path introduced after V5.4.0.

## v5.4.0 — Advanced Decision Analytics

Build: `v540-20260831-advanced-decision-analytics-r2`

### Advanced analytics
- Added NSGA-II-style non-dominated sorting, Pareto fronts, crowding distance and dominance explanations to Market Scan.
- Added Monte Carlo and Latin Hypercube profit simulation with quantiles, loss probability, target-margin probability, CVaR and Sobol first-order / total-effect sensitivity.
- Added multi-product / multi-market MILP resource allocation with budget, concentration, mandatory/prohibited and high-risk constraints.
- Added Bertsimas-Sim budgeted-uncertainty robust-profit mode with configurable Gamma.
- Added graph-based global supply-risk analysis using supplier concentration, market reach, weighted betweenness and supplier-removal stress tests.

### HS ranking
- Upgraded HS candidate ranking to BM25 + deterministic local dense embedding + pairwise logistic Learning-to-Rank.
- Confirmed HS selections are stored as pairwise ranking feedback.
- Added general negation-aware nomenclature features so phrases such as `not knitted` do not incorrectly improve a positive `knitted` query match.
- Added word/bigram and character semantic features while keeping the ranker local-first and model-download free.

### Product and runtime
- Kept the V5.3.8 Decision Research workbench, bilingual report enforcement, tariff scan layout, numeric input normalization and eBay layout fixes.
- Unified public runtime branding as GoGlobal Intelligence.
- Updated Windows/macOS launchers to validate the exact V5.4.0 build and use V5.4-specific dependency/build markers.
- Added SciPy, NumPy, scikit-learn and NetworkX analytics dependencies.

## v5.3.8 — Decision Research and UI finalization
- Rebuilt Decision Research into an interactive bilingual workbench.
- Added AI/web-research provider separation, evidence views and source-aware actions.
- Refined tariff scan, eBay configuration, supplier layout and numeric input behavior.
- Added Windows/macOS cross-platform launch and self-check flows.

## V5.4.0 macOS startup reliability fix
- macOS localhost health checks now bypass HTTP/VPN proxies explicitly.
- Broken/stale virtual environments are rebuilt when their base Python was removed.
- Backend dependency cache invalidates automatically when `requirements.txt` changes.
- Backend startup uses an absolute interpreter path and persists a readable startup log.
- Readiness checks parse health JSON and wait up to 90 seconds for scientific-Python imports.
- Backend startup failures now print the actual traceback instead of only a generic readiness error.

## v5.4.1 CI determinism final fix (R4)
- Removed the remaining NumPy/BLAS matrix-vector operations from the HS ranking path; dense and LTR dot products now use fixed-order `math.fsum` reductions.
- Added a hard generic invariant: when both BM25 and exact positive-token coverage are zero, the dense embedding contribution is capped at 0.04.
- Added a regression test for that invariant so an unsupported dense collision cannot reappear as a CI-only failure.
- GitHub Actions now pins Python `3.12.10` exactly and prints the analytical dependency versions before tests.
- Full backend regression after the change: 129/129 passed; HS ranker regression: 9/9 passed across multiple `PYTHONHASHSEED` values.
