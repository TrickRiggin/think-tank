# Repository Guidelines

## Project Structure & Module Organization
`think_tank.py` is the product: a single-file CLI that runs the multi-model deliberation pipeline. `mcp_server.py` is an optional wrapper around that CLI for MCP-based integrations. `README.md` is the user-facing setup and usage guide; `CLAUDE.md` stores stable architecture notes and operating constraints. Planning and design docs live under `docs/superpowers/plans/` and `docs/superpowers/specs/` with date-prefixed filenames such as `2026-04-05-wisemen.md`.

## Build, Test, and Development Commands
There is no build system here; run scripts directly with Python.

- `pip install requests` installs the CLI runtime dependency.
- `pip install mcp` is only needed if you still use `mcp_server.py`.
- `python think_tank.py --help` shows CLI flags and examples.
- `python think_tank.py "Your question"` runs the default multi-model pipeline.
- `python think_tank.py --no-chairman --json "Quick smoke test"` verifies light mode and JSON output.
- `python think_tank.py --save out.md "Prompt"` saves a full transcript for review.
- `python mcp_server.py` starts the stdio MCP server for local integration testing.

## Coding Style & Naming Conventions
Use Python 3.10+ style, 4-space indentation, and `snake_case` for functions and variables. Match the existing style in `think_tank.py`: explicit control flow, small helpers, and minimal abstraction. Prefer stdlib plus `requests`; do not add frameworks or packaging overhead unless the payoff is clear. For new docs in `docs/superpowers/`, use the existing date-first naming pattern.

## Testing Guidelines
There is no automated test suite yet, so every code change needs manual smoke coverage. Run tests from the repo root so `CLAUDE.md` auto-detection is exercised. At minimum, verify one normal CLI run and one `--json` run. If you touch MCP behavior, test through `python mcp_server.py` as well. When output formatting changes, save a transcript with `--save` and inspect it.

## Commit & Pull Request Guidelines
Recent history uses short conventional prefixes such as `fix:` and `docs:` followed by an imperative summary, for example `fix: handle MCP subprocess timeout`. Keep commits scoped to one change. PRs should explain the behavior change, list the manual test commands you ran, and call out any environment-variable or model-routing impact. Include screenshots only when terminal output or UI presentation changed in a way text will not explain well.

## Security & Configuration Tips
Keep secrets in `~/.env`, `~/.think_tank.env`, or a local `.env`; never commit API keys. `think_tank.py` now expects `OPENROUTER_API_KEY` and routes every model through OpenRouter.
