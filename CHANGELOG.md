# Changelog

## 2.2.0 — Cost Analytics & SQLite History

### Features

- **Analytics Database**: Local SQLite database (`.scenetrace/analytics.db`) for tracking historical run metrics across scenarios.
- **`--track` Flag**: Opt-in analytics tracking on `scenetrace run`. Automatically ingests run metadata after execution.
- **`scenetrace analytics init`**: Initialize the analytics database and schema.
- **`scenetrace analytics track <trace>`**: Manually ingest existing trace files into the analytics database.
- **`scenetrace analytics report <scenario_id>`**: Rich terminal dashboard showing efficiency scores, cost/latency trends, agent cost breakdown, and recent run history.
- **Efficiency Scoring**: Composite 0-100 score based on check pass rate (40%), cost stability (30%), latency stability (20%), and token optimization (10%).
- **Agent-Level Metrics**: Per-agent breakdown of turn count, token usage, average latency, and cost share percentage.
- **Cost Alerts**: Warns when latest run cost exceeds the historical average by >20%.

### Architecture

- Uses built-in `sqlite3` — no external database dependencies
- Opt-in only (`--track` flag) to preserve lightweight default CLI behavior
- Indexed on `scenario_id`, `timestamp`, and `status` for fast queries
- Agent metrics stored per-run for granular cost attribution

---

## 2.1.0 — Plugin Discovery

### Features

- **Plugin Discovery**: Discover external providers and check types via standard Python entry points (`scenetrace.providers` and `scenetrace.checks` groups).
- **CLI Command**: `scenetrace plugin list` shows discovered plugins with name, type, package, version, and load status.
- **Provider Integration**: Plugin-provided providers are automatically available via `--provider <name>` alongside built-in `mock` and `openai`.
- **Check Integration**: Plugin-provided check types are automatically available in scenario `checks` definitions alongside built-in types.
- **Graceful Failure**: Import errors in plugins trigger warnings without crashing the CLI or runner.

### Architecture

- Uses `importlib.metadata.entry_points()` for standard Python package discovery
- Lazy loading — plugins are only imported when actually used
- No `plugin install` command — users manage packages with `pip`/`uv` directly (security-first approach)

---

## 2.0.0 — Baseline Management & Drift Detection

### Features

- **Baseline Registry**: Local SQLite-backed baseline management in `.scenetrace/baselines.db`. Save "golden" traces, tag them, and compare new runs against them.
- **Drift Detection**: Automatically detects cost spikes (>15% default), latency regressions (>200ms default), token count changes, status changes, and check flips (PASS→FAIL).
- **CLI Commands**: `scenetrace baseline init`, `save`, `compare`, `list`, `rm` — full lifecycle management with Rich-styled output.
- **Configurable Thresholds**: `--cost-threshold` and `--latency-threshold` flags on `compare` for project-specific tolerances.
- **CI/CD Integration**: `baseline compare` exits `1` on regression, making it a drop-in CI gate.

### CLI Changes

- New `baseline` command group with 5 subcommands
- `baseline compare` shows color-coded drift summary panel and detailed comparison table
- `baseline list` shows all saved baselines in a formatted table

### Architecture

- Hybrid storage: JSON trace files for data (git-friendly), SQLite for metadata indexing
- Trace hashing for content-based comparison (SHA-256 of prompt/response pairs)
- Tag-based baseline versioning with collision safety (`--force` to overwrite)

---

## 1.2.0 — Markdown Reports & Docker Support

### Features

- **Markdown Report Export**: `scenetrace report <trace> --format md` generates GitHub-compatible Markdown reports with collapsible `<details>` sections for turns, summary tables, and check badges.
- **Dockerfile**: Lightweight `python:3.11-slim` image running as non-root user. `docker build -t scenetrace .` and `docker run scenetrace --version`.
- **`.dockerignore`**: Excludes traces, cache, venv, tests, and secrets from the Docker build context.

### CLI Changes

- `scenetrace report` now accepts `--format html` (default) or `--format md`
- Default output filename uses the correct extension based on format

---

## 1.1.0 — Custom Python Checks & Cross-Platform Fixes

### Features

- **Custom Python Checks**: New `type: python` check executes local scripts via subprocess isolation. Scripts export `check(response, context) -> bool`. Strict 5-second timeout prevents runner hangs. Supports absolute and relative paths (resolved against scenario file directory).
- **Cross-Platform Regex Timeout**: Replaced `signal.SIGALRM` (Linux/macOS only) with `concurrent.futures.ThreadPoolExecutor` timeout. Regex checks now work correctly on Windows.

### Example

```yaml
checks:
  - id: custom_check
    type: python
    params:
      script_path: checks/my_check.py
      timeout: 5
```

### Security

- Python checks run in isolated subprocesses — no shared memory, no namespace pollution
- Subprocess timeout kills runaway scripts automatically
- Script errors are caught and reported without crashing the runner

---

## 1.0.0 — Initial Release

ScenTrace V1: local-first scenario-based regression testing for multi-agent AI workflows.

### Features

- **Scenario Schema** (Phase 2): YAML-based scenario definition with Pydantic v2 validation. Supports agents, turns, model config, variable injection (`{{var}}`), and typed checks.
- **Runner Engine** (Phase 3): Sequential turn execution with variable resolution, trace capture, and configurable error handling (`--stop-on-error`, `--stop-on-fail`).
- **Provider Adapters** (Phase 4): Pluggable provider system with lazy loading. MockProvider included in core; OpenAI available via `pip install scen-trace[openai]`. Mock returns realistic token estimates.
- **Trace Capture** (Phase 5): Per-turn latency (`duration_ms`), token counts, and estimated cost. Supports `.json` and `.jsonl` output formats.
- **Checks Engine** (Phase 6): Four check types — `contains` (case-insensitive), `forbidden` (case-insensitive), `regex` (5s timeout), `json_valid` (markdown-aware). Checks run after each turn with live CLI feedback.
- **HTML Reports** (Phase 7): Self-contained HTML report with dark mode toggle, collapsible turns, color-coded check results, and cost/timing summaries. Zero external dependencies.
- **CLI** (Phase 8): `scenetrace init`, `validate`, `run`, `report`, and `sync` (V2 teaser). Rich-styled terminal output with live progress and summary panels.
- **CI/CD** (Phase 8): Drop-in GitHub Actions workflow with mock provider execution and failure-only artifact upload.
- **Project Scaffolding** (Phase 8): `scenetrace init` creates `.scenetrace/` with example scenario, `.env.example`, and `.gitignore` — ready to run in under 3 minutes.

### Architecture

- Optional provider SDKs via `pyproject.toml` extras (`[openai]`, `[anthropic]`, `[all]`)
- Lazy provider loading — core install has no heavy SDK dependencies
- XSS-safe HTML report generation with `html.escape()`
- Graceful `KeyboardInterrupt` handling in CLI

### Known Limitations

- ~~Regex timeout uses `signal.SIGALRM` (Linux/macOS only)~~ — Fixed in V1.1 with cross-platform `ThreadPoolExecutor`
- Cost estimation uses flat `$0.000001/token` default; provider-specific pricing deferred
- JSONL trace loading reconstructs scenario metadata from turn data
- No streaming provider support (synchronous completions only)
- Anthropic provider declared as extra but not yet implemented

### Not in V1

- SaaS dashboard or hosted execution
- Cloud trace syncing (placeholder `scenetrace sync` hints at V2)
- Marketplace, plugin ecosystem, or scenario packs
- Enterprise SSO, billing, or team workspaces
- Visual workflow builder
- Semantic similarity checks
- Custom Python assertion scripts (moved to V1.1)
