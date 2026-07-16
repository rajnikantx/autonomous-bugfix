# autonomous-bugfix

Autonomous multi-agent system that discovers, investigates, and fixes Python bugs. Built with LangGraph, OpenAI, and LangSmith.

## How It Works

The system runs a 10-node LangGraph workflow that processes bugs end-to-end in a sandboxed environment:

```
clone repo -> scan bugs (pytest) -> triage -> select bug
  -> investigate (ReAct loop with code tools)
  -> generate fix (plan + patch)
  -> apply fix -> run tests -> review (adversarial LLM)
  -> merge fix -> select next bug (loop)
```

**Agents:**
- **Triage** -- Parses pytest JSON output into structured bug reports with severity and fixability assessment
- **Investigator** -- ReAct loop (up to 10 tool calls) using AST-based code exploration tools to find root cause
- **Fixer** -- Plans edits then generates search-and-replace patches with validation and replanning
- **Reviewer** -- Adversarial LLM review of diffs against the investigation report

**Sandboxed:** All investigation, patching, and testing happen in a temporary copy of the repo. Fixes are only merged back after review approval.

**Bug lifecycle:**
```
pending -> investigating -> patching -> testing -> reviewing -> resolved
              |               |           |            |
              v               v           v            v
         escalated       escalated   escalated    escalated
```

Any failure at any stage escalates the bug and moves to the next pending one.

## Installation

```bash
# Clone the repo
git clone https://github.com/rajnikantx/autonomous-bugfix.git
cd autonomous-bugfix

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

## Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY="sk-..."
REPO_PATH="/path/to/your/python/project"

# Optional: override default models
TRIAGE_MODEL="gpt-4o"
INVESTIGATE_MODEL="gpt-4o"
FIX_MODEL="gpt-4o"
REVIEW_MODEL="gpt-4o"

# Optional: LangSmith tracing
LANGSMITH_TRACING=true
LANGSMITH_API_KEY="lsv2_..."
LANGSMITH_PROJECT="autonomous bugfix"
```

## CLI Usage

```bash
# Basic usage (reads REPO_PATH from .env)
autonomous-bugfix

# Or run as a module
python -m src.main
```

### Options

```
autonomous-bugfix [-h] [-r REPO] [--triage-model MODEL]
                  [--investigate-model MODEL] [--fix-model MODEL]
                  [--review-model MODEL] [-v] [--dry-run]
```

| Flag | Description |
|------|-------------|
| `-r`, `--repo PATH` | Path to the target repository (overrides `REPO_PATH` from `.env`) |
| `--triage-model MODEL` | LLM model for the triage agent (default: `gpt-4o`) |
| `--investigate-model MODEL` | LLM model for the investigator agent (default: `gpt-4o`) |
| `--fix-model MODEL` | LLM model for the fixer agent (default: `gpt-4o`) |
| `--review-model MODEL` | LLM model for the reviewer agent (default: `gpt-4o`) |
| `-v`, `--verbose` | Enable verbose/debug logging |
| `--dry-run` | Run investigation only, do not apply fixes |

### Examples

```bash
# Fix bugs in a specific repo
autonomous-bugfix --repo /path/to/project

# Use a cheaper model for investigation, stronger model for review
autonomous-bugfix --investigate-model gpt-4o-mini --review-model o3

# Dry run: investigate without applying fixes
autonomous-bugfix --repo /path/to/project --dry-run

# Verbose output for debugging
autonomous-bugfix -v
```

## Architecture

```
src/
  main.py                  # CLI entry point
  config.py                # Pydantic Settings (loads from .env)

  agents/
    triage.py              # Triage agent -- structured pytest JSON parsing
    investigate.py         # Investigator -- ReAct loop with code tools
    fix.py                 # Fixer -- plan-then-generate patches
    review.py              # Reviewer -- adversarial diff review

  graph/
    workflow.py            # LangGraph StateGraph (nodes, edges, conditions)
    states.py              # Shared state schema + dataclasses
    nodes/
      clone_project.py     # Clones repo into temp sandbox
      scan_bugs.py         # Runs pytest --json-report
      triage.py            # Wraps Triage agent
      select_bug.py        # Picks next pending bug
      investigate.py       # Wraps Investigator agent
      generate_fix.py      # Wraps Fixer agent
      apply_fix.py         # Applies patches to sandbox
      run_tests.py         # Re-runs failing test to verify fix
      review_agent.py      # Wraps Reviewer agent
      merge_fix.py         # Copies fixed files back to original repo

  tools/
    code_search.py         # 7 AST-based and regex code exploration tools
    file_ops.py            # File read, patch application, syntax validation
```

## Tools (Investigator Agent)

The investigator uses these tools during its ReAct loop:

| Tool | Description |
|------|-------------|
| `extract_snippet` | Show lines around a specific line (default first tool) |
| `read_file` | Full file contents with line numbers |
| `grep_codebase` | Regex search across all `.py` files |
| `get_function_definition` | AST-based function source extraction |
| `get_class_definition` | AST-based class source extraction |
| `get_function_callers` | Find all call sites of a function |
| `get_functions_of_file` | List all functions/classes in a file |
| `get_imports_of_file` | List all imports in a file |

## Roadmap

- [ ] **REST API** -- Deploy as a service with FastAPI for programmatic access
- [ ] **GitHub App / Webhooks** -- Trigger auto-fix on push, PR, or CI failure events (not just local CLI)
- [ ] **Docker sandboxing** -- Run investigation, patching, and tests inside Docker containers for full isolation
- [ ] **Dynamic orchestrator** -- Replace static graph with LLM-driven dynamic routing (design doc in `docs/orchestrator.md`)
- [ ] **Session persistence** -- Save/resume sessions to resume interrupted runs or replay past fixes
- [ ] **Report generation** -- Post-run summary report with per-bug breakdown
- [ ] **Parallel bug fixing** -- Investigate and fix multiple bugs concurrently
- [ ] **Web dashboard** -- UI to monitor active sessions, view bug statuses, and review diffs before merging
- [ ] **Non-Python support** -- Extend to JavaScript/TypeScript, Go, Rust projects
- [ ] **CI/CD integration** -- GitHub Actions / GitLab CI trigger to auto-fix failing tests on PRs
- [ ] **Human-in-the-loop review** -- Optional approval gate before merging fixes (email/Slack notification)
- [ ] **Custom tool plugins** -- Allow users to register project-specific exploration tools for the investigator

## License

MIT
