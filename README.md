# Capstone HR — Team 13 agent + harness

Week-2 deliverable: own MCP-driven HR agent and harness for AgentSwitch (Suryodaya).

Week-1 gap report: [gap_report.md](./gap_report.md).

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Fill AS_PASSWORD and GEMINI_API_KEY
```

Credentials stay in `.env` only (never commit). Seat passwords are in your team channel / local `project_breif.txt`.

Model: **Gemini** via Google's OpenAI-compatible API (`gemini-3.1-flash-lite` by default). On 429/503 the loop tries `GEMINI_MODEL_FALLBACKS`.

## Smoke MCP (no LLM)

```bash
python -m agent.cli --whoami
python -m agent.cli --list-tools
python scripts/capture_fixtures.py
```

## Run the agent

```bash
python -m agent.cli "Who is on leave next week, whose attendance does not look right, and who is due for confirmation?"
```

Journals land in `runs/`.

## Run the harness

```bash
python -m harness.runner --list
python -m harness.runner --task bar_suryodaya
python -m harness.runner --task refuse_out_of_seat
python -m harness.runner --all --repeats 1
python -m harness.runner --task write_conflict_abort

```

Order is fixed: **run → write journal to disk → verify via live MCP → score**.

Task catalogue: [harness/tasks/TASKS.md](./harness/tasks/TASKS.md).

## Regression tests

```bash
pytest tests/ -q
```

See [tests/README.md](./tests/README.md). Course grading still wants human-owned tests — review before submitting for points.

## Layout

```
agent/          MCP client, catalogue, hr_rules, loop, CLI
harness/        runner, independent verifiers, tasks
fixtures/       sample + live captures
runs/           journals + scores (gitignored)
tests/          YOUR tests only
```
