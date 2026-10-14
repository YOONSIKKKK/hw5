"""Central configuration for the Campus Customs agent backend.

Every knob that affects cost or safety lives here so it can be audited in one
place -- above all the model id, which the assignment pins to a single value.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
OUTPUT_DIR = ROOT / "output"
AUDIT_TRAIL = OUTPUT_DIR / "audit_trail.json"

# The repo root holds the shared .env with PORTKEY_API_KEY.
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env", override=True)

# --------------------------------------------------------------------------
# Model -- the assignment restricts every agent to exactly one model.
# --------------------------------------------------------------------------
MODEL_ID = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"


def portkey_api_key() -> str:
    key = os.environ.get("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError(
            "PORTKEY_API_KEY is not set. Put it in the repository root .env file."
        )
    return key


# --------------------------------------------------------------------------
# MCP -- the only route to shop data.
# --------------------------------------------------------------------------
MCP_HOST = os.environ.get("CAMPUS_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("CAMPUS_MCP_PORT", "8787"))
MCP_URL = os.environ.get("CAMPUS_MCP_URL", f"http://{MCP_HOST}:{MCP_PORT}/mcp")

# --------------------------------------------------------------------------
# Token and runaway controls.  Multi-agent loops burn tokens fast, so every
# limit below is deliberately tight.
# --------------------------------------------------------------------------
MAX_DELEGATION_DEPTH = 3          # Boss -> specialist -> specialist, then stop.
MAX_REQUESTS_PER_TICKET = 40      # model calls across one ticket's whole tree
MAX_TOTAL_TOKENS_PER_TICKET = 180_000
MAX_TOOL_CALLS_PER_TICKET = 60
MAX_OUTPUT_TOKENS = 3_000         # per model response; 1,400 proved too tight for
                                  # the Boss's structured decision output
AGENT_RETRIES = 2

# The human who signs off on money.  Recorded in payments.approved_by.
DEFAULT_SUPERVISOR = "Yunsik Jung"

# Agents may never call this; only the backend does, and only after a human
# clicks approve or deny in the dashboard.
SUPERVISOR_ONLY_TOOLS = frozenset({"supervisor_resolve_approval"})
