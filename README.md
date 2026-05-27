# ScenTrace

**Regression testing for multi-agent AI workflows. Local-first. Zero egress.**

ScenTrace helps you define repeatable scenarios for AI agents, run them locally or in CI/CD, capture full execution traces, detect regressions, compare prompts and models, and generate reports — all without sending a single prompt to a third-party dashboard. Your data stays on your machine.

---

## What is ScenTrace?

ScenTrace is a **developer CLI tool** for testing AI agent workflows the same way you test code: write a scenario, run it, check the results, catch regressions before they ship.

If you're building apps with LLMs (chatbots, support agents, RAG pipelines, multi-agent systems), you've probably noticed:

- **Prompt changes break things silently.** You tweak a system prompt and suddenly the agent hallucinates or forgets to follow instructions.
- **Model upgrades introduce drift.** Swapping `gpt-4o` for `gpt-4o-mini` changes behavior in subtle, hard-to-catch ways.
- **There's no `pytest` for AI agents.** Unit tests verify code logic, but they can't tell you if your agent still behaves correctly after a change.
- **Existing tools are cloud-hosted.** LangSmith, Helicone, and similar platforms require sending your prompts and responses to external servers.

ScenTrace solves this by giving you a **local, repeatable, CI/CD-friendly regression testing workflow** for AI agents.

---

## Who is it for?

- **AI/ML engineers** building and iterating on LLM-powered applications
- **Backend developers** integrating AI agents into products and needing regression safety
- **AI agencies** delivering agent solutions to clients who need proof of correctness
- **Teams in regulated industries** (healthcare, finance, legal) where prompts and responses cannot leave the local environment
- **Open-source contributors** who want to validate AI behavior without paid cloud subscriptions

---

## Why is it needed?

### The problem

Every time you change a prompt, swap a model, or update your agent logic, you're guessing whether it still works correctly. Manual testing doesn't scale. Traditional unit tests can't evaluate natural-language outputs. Cloud observability platforms require you to trust a third party with your data.

### What ScenTrace does differently

| | ScenTrace | LangSmith | Promptfoo |
|---|---|---|---|
| **Runs locally** | Yes | No (cloud) | Yes |
| **Zero data egress** | Yes | No | Partial |
| **Multi-agent traces** | Built-in | Manual | Limited |
| **Cost tracking** | Per-turn, per-agent | Aggregated | Per-eval |
| **Semantic checks** | Local embeddings | Cloud-based | External |
| **Baseline regression** | Built-in drift detection | Manual comparison | Snapshot-based |
| **CI/CD native** | Copy-paste GitHub Actions | SDK integration | Config required |
| **Reports** | Self-contained HTML + Markdown | Cloud dashboard | JSON |
| **Setup time** | < 3 minutes | Account + SDK | Config + eval |
| **Web dashboard** | Local (`scenetrace serve`) | Hosted only | None |

---

## Quick Start (3 minutes)

```bash
# 1. Install
pip install scen-trace

# 2. Scaffold a project
scenetrace init

# 3. Run the example scenario (zero cost, no API key needed)
scenetrace run .scenetrace/example_scenario.yaml --provider mock -o trace.json

# 4. Generate an HTML report
scenetrace report trace.json -o report.html --open
```

That's it. You now have a passing regression test with a full trace and a visual report.

---

## Installation

**Core (mock provider, no API keys needed):**
```bash
pip install scen-trace
```

**With OpenAI support:**
```bash
pip install "scen-trace[openai]"
```

**With semantic checks (local embeddings for fuzzy matching):**
```bash
pip install "scen-trace[semantic]"
```

**With the web dashboard:**
```bash
pip install "scen-trace[web]"
```

**Everything:**
```bash
pip install "scen-trace[all]"
```

Requires Python 3.10+.

---

## How to Use It

### 1. Define a Scenario

Create a YAML file describing your agent, prompts, and expected behavior:

```yaml
scenario_id: customer_support_refund
description: Verify the support bot handles refund requests correctly

variables:
  customer_name: Alice
  order_id: ORD-12345

agents:
  - name: support_bot
    role: assistant
    system_prompt: >
      You are a customer support agent for Acme Corp.
      Be helpful, professional, and always reference the order ID.

model_config:
  provider: openai       # or: mock (for zero-cost testing)
  model_name: gpt-4o-mini
  temperature: 0.0       # Use 0 for deterministic results
  max_tokens: 512

turns:
  - agent_name: support_bot
    prompt: "Hi, I'm {{customer_name}}. I need a refund for order {{order_id}}."
    expected_checks:
      - mentions_order
      - polite_tone
      - no_hallucination

checks:
  - id: mentions_order
    type: contains
    params:
      text: "ORD-12345"

  - id: polite_tone
    type: forbidden
    params:
      text: "that's not my problem"

  - id: no_hallucination
    type: forbidden
    params:
      text: "I don't have access to order information"
```

### 2. Run It

```bash
# With mock provider (free, no API key)
scenetrace run scenario.yaml --provider mock -o trace.json

# With a real provider
OPENAI_API_KEY=sk-... scenetrace run scenario.yaml -o trace.json
```

The CLI shows live progress with color-coded pass/fail checks:

```
Running scenario: customer_support_refund
Provider: openai | Model: gpt-4o-mini

  ✓ Turn 1: support_bot (342ms)
    ✓ mentions_order: PASSED
    ✓ polite_tone: PASSED
    ✓ no_hallucination: PASSED

╭─ customer_support_refund ────────────────────╮
│  Status    PASSED                             │
│  Provider  openai                             │
│  Turns     1                                  │
│  Duration  342ms                              │
│  Tokens    85 in / 142 out                    │
│  Est. Cost $0.000284                          │
│  Checks    3 passed / 0 failed                │
╰──────────────────────────────────────────────╯
```

### 3. Generate Reports

```bash
# Self-contained HTML report (dark mode, collapsible turns, cost cards)
scenetrace report trace.json -o report.html --open

# GitHub-compatible Markdown report
scenetrace report trace.json --format md -o report.md
```

### 4. Track Regressions with Baselines

```bash
# Save a "golden" trace as your baseline
scenetrace baseline init
scenetrace baseline save trace.json --tag v1.0

# After making changes, compare against the baseline
scenetrace run scenario.yaml -o new_trace.json
scenetrace baseline compare new_trace.json --tag v1.0
```

The comparison shows drift in cost, latency, token usage, and check results:

```
╭─ Baseline Comparison ───────────────────────╮
│  Comparison against baseline: v1.0           │
│  Overall: STABLE                             │
│                                              │
│  ✅ Cost: $0.000284 → $0.000291 (+2.5%)     │
│  ✅ Latency: 342ms → 338ms (-4ms)           │
│  ✅ All checks: No flips                     │
╰─────────────────────────────────────────────╯
```

### 5. Track Cost & Efficiency Over Time

```bash
scenetrace analytics init
scenetrace run scenario.yaml --provider mock --track -o trace.json
scenetrace analytics report customer_support_refund
```

Shows efficiency scores, cost trends, agent breakdowns, and alerts for cost spikes.

### 6. Web Dashboard

```bash
pip install "scen-trace[web]"
scenetrace serve
```

Opens a local web dashboard at `http://127.0.0.1:8000` with cost trend charts, efficiency scores, and run history. All data stays local.

---

## Check Types

| Type | Description | Notes |
|------|-------------|-------|
| `contains` | Response includes substring | Case-insensitive, trims whitespace |
| `forbidden` | Response must NOT include substring | Case-insensitive |
| `regex` | Response matches pattern | 5s timeout to prevent catastrophic backtracking |
| `json_valid` | Response is valid JSON | Strips markdown code blocks (`` ```json `` ) automatically |
| `python` | Custom Python script check | Runs in subprocess with timeout for safety |
| `semantic` | Embedding similarity check | Requires `scen-trace[semantic]`; local model, no network |

### Custom Python Checks

Write a script that accepts `response` and `context`, returns `True`/`False`:

```python
# checks/has_greeting.py
import sys, json

def check(response: str, context: dict) -> bool:
    return any(word in response.lower() for word in ["hello", "hi", "hey"])

if __name__ == "__main__":
    result = check(sys.argv[1], json.loads(sys.argv[2]))
    sys.exit(0 if result else 1)
```

Reference it in your scenario:
```yaml
checks:
  - id: has_greeting
    type: python
    params:
      script_path: checks/has_greeting.py
```

### Semantic Checks (Fuzzy Matching)

For when exact string matching is too brittle:

```yaml
checks:
  - id: correct_answer
    type: semantic
    params:
      reference_answer: "Your refund has been processed and will appear in 3-5 business days."
      threshold: 0.75   # cosine similarity (0.0 - 1.0)
```

Requires `pip install "scen-trace[semantic]"`. Uses local embeddings (`all-MiniLM-L6-v2`) — no prompts leave your machine.

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `scenetrace init` | Scaffold a project with example scenario |
| `scenetrace validate <path>` | Validate a scenario YAML file |
| `scenetrace run <path>` | Execute a scenario and capture traces |
| `scenetrace report <trace>` | Generate HTML or Markdown report |
| `scenetrace serve` | Start local web dashboard |
| `scenetrace baseline init` | Initialize baseline registry |
| `scenetrace baseline save <trace> --tag <name>` | Save a golden baseline |
| `scenetrace baseline compare <trace> --tag <name>` | Compare against baseline, detect drift |
| `scenetrace baseline list` | Show saved baselines |
| `scenetrace baseline rm <tag>` | Remove a baseline |
| `scenetrace analytics init` | Initialize local analytics DB |
| `scenetrace analytics track <trace>` | Ingest run metrics |
| `scenetrace analytics report <scenario_id>` | View efficiency dashboard |
| `scenetrace plugin list` | Show discovered plugins |

### Run Options

```bash
scenetrace run scenario.yaml \
  --provider mock          # Provider: mock, openai
  --model gpt-4o           # Override model from scenario
  --max-turns 10           # Limit execution turns
  --stop-on-fail           # Halt on first check failure
  --stop-on-error          # Halt on provider errors
  -o trace.json            # Save trace (.json or .jsonl)
  --track                  # Auto-track in analytics DB
```

---

## GitHub Actions

Copy this into `.github/workflows/scenetrace.yml`:

```yaml
name: ScenTrace Regression Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install ScenTrace
        run: pip install scen-trace

      - name: Run scenarios
        run: scenetrace run .scenetrace/example_scenario.yaml --provider mock -o traces/result.json

      - name: Generate report
        if: always()
        run: scenetrace report traces/result.json -o traces/report.html

      - name: Upload traces on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: scenetrace-traces
          path: traces/
          retention-days: 14
```

For real providers in CI, add `OPENAI_API_KEY` as a repository secret and use `--provider openai`.

---

## Docker

```bash
docker build -t scenetrace .
docker run --rm scenetrace --version
docker run --rm -v $(pwd):/app scenetrace run scenarios/test.yaml --provider mock
```

Runs as non-root. Core image < 150MB.

---

## Plugin System

ScenTrace discovers external providers and checks via standard Python entry points. No plugin marketplace — just `pip install`:

```bash
# Install a community provider
pip install scenetrace-azure

# See what's available
scenetrace plugin list
```

To create a plugin, register entry points under `scenetrace.providers` or `scenetrace.checks` in your package's `pyproject.toml`.

---

## Architecture

ScenTrace is intentionally simple:

```
Scenario YAML → Runner → Provider (Mock/OpenAI) → Trace (JSON/JSONL)
                  ↓                                    ↓
              Checks Engine                     Report Generator
                  ↓                             (HTML / Markdown)
            Pass/Fail/Warning
                  ↓
          Baseline Comparison ←→ SQLite Registry
                  ↓
          Analytics Dashboard ←→ SQLite DB
                  ↓
          Web UI (FastAPI, localhost)
```

All data is stored locally in `.scenetrace/` (SQLite for analytics/baselines, JSON for traces). Nothing is uploaded anywhere.

---

## Development

```bash
git clone https://github.com/SantaAaron/ScenTrace.git
cd ScenTrace
pip install -e ".[dev]"
pytest tests/ -q
```

---

## Roadmap

- [x] Scenario schema & validation
- [x] Runner engine with mock & OpenAI providers
- [x] Trace capture (JSON + JSONL)
- [x] Check engine (contains, forbidden, regex, json_valid, python, semantic)
- [x] HTML & Markdown reports
- [x] Baseline management & drift detection
- [x] Cost analytics & efficiency scoring
- [x] Plugin discovery via entry points
- [x] Local web dashboard
- [ ] `scenetrace diff` — trace comparison CLI
- [ ] `scenetrace sync` — team baseline sharing
- [ ] Anthropic & OpenRouter provider adapters
- [ ] CI/CD PR comment generation

---

## License

MIT
