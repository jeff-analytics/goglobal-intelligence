# GoGlobal Intelligence v5.4.1

Build: `v541-20260901-algorithms-ai-config-r4`

## Advanced decision algorithms

1. Pareto / non-dominated market screening with fronts, crowding distance and dominance explanations.
2. Monte Carlo and Latin Hypercube profit simulation with Sobol first-order and total-effect sensitivity indices.
3. MILP portfolio allocation with budget, market, product, risk, capacity and entry constraints plus Bertsimas-Sim Γ robust optimization.
4. Hybrid HS candidate ranking using BM25 lexical retrieval, dense latent embedding and pairwise learning-to-rank from confirmed selections.
5. Global trade-network risk analysis with concentration, centrality, supplier reach and node-removal stress tests.

## AI configuration reliability

- DeepSeek preset defaults to Responses API, `https://api.deepseek.com`, and `deepseek-v4-flash`.
- Human-readable variants such as `DeepSeek-V4-Flash` are canonicalized to the provider model ID before validation and storage.

## Platform

- Windows and macOS launchers validate the V5.4.1 build.
- macOS retains proxy-safe local health checks and backend runtime logging.

## Cross-platform HS ranking stability

- Replaces BLAS-sensitive LSA/SVD with a deterministic local dense feature-hash embedding calibrated by direct word/character evidence.
- Removes per-query min-max amplification from the embedding feature.
- Uses deterministic pairwise logistic Learning-to-Rank and deterministic tie-breaking so Linux/macOS/Windows produce the same ordering for identical inputs.
- Pins NumPy, SciPy, scikit-learn and NetworkX versions used by the analytical stack.
- Adds regression coverage for the CI-only dense-similarity outlier observed on Ubuntu.


## CI / HS deterministic ranking hotfix r3

- Replaced fitted TruncatedSVD ranking embeddings with deterministic local feature-hash dense embeddings.
- Added direct evidence calibration so unsupported dense collisions remain bounded.
- Replaced native-solver pairwise LTR with deterministic fixed-iteration pairwise logistic updates.
- Added deterministic code tie-breaking to remove set-order dependence.
- Added repeated cache-rebuild and direct-support regression tests for CI reproducibility.
- Build: `v541-20260901-algorithms-ai-config-r4`.

## R4 — CI determinism final fix

The HS ranker no longer uses BLAS-backed matrix multiplication anywhere in ranking or pairwise LTR scoring. Dense feature-hash similarities and final ranking scores are reduced in a fixed Python order with `math.fsum`. Candidates with zero BM25 and zero exact positive-token support are hard-capped to an embedding contribution of 0.04. This converts the CI regression from a numeric heuristic into an explicit ranking invariant.

GitHub Actions is pinned to Python 3.12.10 and the analytical dependency versions are printed before the test stage for reproducibility.

### FINAL CI R5
The HS candidate ranker now uses a pure-Python deterministic ranking path for BM25, dense feature-hash embedding scoring, and pairwise logistic Learning-to-Rank. CI verifies the source revision and repeats the HS suite under multiple `PYTHONHASHSEED` values before the full backend regression.
