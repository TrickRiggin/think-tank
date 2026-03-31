#!/usr/bin/env python3
"""Think Tank MCP Server — exposes think_tank as tools for Claude Code.

Two tools:
  - think_tank_light: 4 models answer in parallel, no review/synthesis
  - think_tank_heavy: full pipeline with deliberation, review, and chairman synthesis
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("think-tank")

THINK_TANK_SCRIPT = str(Path(__file__).parent / "think_tank.py")


def _run_think_tank(question: str, extra_args: list[str] = None, cwd: str = None) -> dict:
    """Shell out to think_tank.py --json and return parsed result."""
    cmd = [sys.executable, THINK_TANK_SCRIPT, "--json"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(question)

    # Use provided cwd, or fall back to env, or home
    work_dir = cwd or os.environ.get("THINK_TANK_CWD") or str(Path.home())

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max
            cwd=work_dir,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired:
        return {"error": "Think Tank timed out after 5 minutes"}

    if result.returncode != 0:
        return {"error": f"Think Tank failed (exit {result.returncode})", "stderr": result.stderr[-1000:]}

    # Parse JSON from stdout (last line, in case of any stray output)
    stdout = result.stdout.strip()
    if not stdout:
        return {"error": "Think Tank produced no output", "stderr": result.stderr[-1000:]}

    # Find the JSON object — should be the last line
    for line in reversed(stdout.split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass

    return {"error": "Could not parse JSON from Think Tank output", "stdout_tail": stdout[-500:]}


@mcp.tool()
def think_tank_light(question: str, files: str = "", cwd: str = "") -> str:
    """Get quick opinions from 4 AI models (Claude, GPT, Gemini, Grok) in parallel.

    No review or synthesis — just raw responses. Use for gut checks,
    quick sanity checks, or getting diverse perspectives fast.

    Args:
        question: The question or topic to deliberate on.
        files: Optional comma-separated file paths to include as context.
        cwd: Optional working directory (for CLAUDE.md auto-detection).
    """
    args = ["--no-chairman"]
    if files:
        args.extend(["--files", files])

    result = _run_think_tank(question, args, cwd=cwd or None)

    if "error" in result:
        return json.dumps(result, indent=2)

    # Format for readability in Claude Code context
    output = {"question": result.get("question", question), "models": result.get("models", []), "responses": {}}

    for round_data in result.get("rounds", []):
        for model_key, data in round_data.get("responses", {}).items():
            output["responses"][model_key] = data.get("text", "")

    output["total_elapsed"] = result.get("total_elapsed", 0)
    return json.dumps(output, indent=2, ensure_ascii=False)


@mcp.tool()
def think_tank_heavy(question: str, rounds: int = 2, files: str = "", cwd: str = "") -> str:
    """Full Think Tank deliberation: 4 models debate, anonymized peer review, chairman synthesis.

    Use for design decisions, architecture questions, strategy debates,
    or any problem that benefits from structured multi-model deliberation.

    Args:
        question: The question or topic to deliberate on.
        rounds: Number of deliberation rounds (default 2). More rounds = more cross-pollination.
        files: Optional comma-separated file paths to include as context.
        cwd: Optional working directory (for CLAUDE.md auto-detection).
    """
    args = ["--rounds", str(rounds)]
    if files:
        args.extend(["--files", files])

    result = _run_think_tank(question, args, cwd=cwd or None)

    if "error" in result:
        return json.dumps(result, indent=2)

    return json.dumps(result, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
