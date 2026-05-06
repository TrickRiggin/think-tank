# Repository Guidelines

## Project Structure & Module Organization
`think_tank.py` is the product: a single-file CLI that runs the multi-model deliberation pipeline. There is no MCP wrapper anymore; keep this repo CLI-first. `README.md` is the user-facing setup and usage guide; `CLAUDE.md` stores stable architecture notes and operating constraints. Planning and design docs live under `docs/superpowers/plans/` and `docs/superpowers/specs/` with date-prefixed filenames such as `2026-04-05-wisemen.md`.

## Build, Test, and Development Commands
There is no build system here; run scripts directly with Python.

- `pip install requests` installs the CLI runtime dependency.
- `python think_tank.py --help` shows CLI flags and examples.
- `python think_tank.py "Your question"` runs the default multi-model pipeline.
- `python think_tank.py --crux "Decision question"` verifies the crux-framing path.
- `python think_tank.py --no-chairman --json "Quick smoke test"` verifies light mode and JSON output.
- `python think_tank.py --review --no-save "Which response is strongest?"` verifies optional peer review/ranking diagnostics.
- `python think_tank.py --save out.md "Prompt"` saves `output/out.md` and `output/out.html` for review.
- `python think_tank.py --no-save "Quick throwaway"` skips default artifact writes.

## Coding Style & Naming Conventions
Use Python 3.10+ style, 4-space indentation, and `snake_case` for functions and variables. Match the existing style in `think_tank.py`: explicit control flow, small helpers, and minimal abstraction. Prefer stdlib plus `requests`; do not add frameworks or packaging overhead unless the payoff is clear. For new docs in `docs/superpowers/`, use the existing date-first naming pattern.

## Testing Guidelines
There is no automated test suite yet, so every code change needs manual smoke coverage. Run tests from the repo root so `CLAUDE.md` auto-detection is exercised. At minimum, verify one normal CLI run and one `--json` run. When output formatting changes, inspect both the saved markdown and the generated HTML report. Peer review/ranking is opt-in with `--review`; do not treat it as the default pipeline when testing normal behavior.

## Commit & Pull Request Guidelines
Recent history uses short conventional prefixes such as `fix:` and `docs:` followed by an imperative summary, for example `fix: tighten review rankings`. Keep commits scoped to one change. PRs should explain the behavior change, list the manual test commands you ran, and call out any environment-variable or model-routing impact. Include screenshots only when terminal output or UI presentation changed in a way text will not explain well.

## Security & Configuration Tips
Keep secrets in `~/.env`, `~/.think_tank.env`, or a local `.env`; never commit API keys. `think_tank.py` now expects `OPENROUTER_API_KEY` and routes every model through OpenRouter.
