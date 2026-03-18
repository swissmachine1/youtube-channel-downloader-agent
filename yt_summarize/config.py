import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (or current working directory)
load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS_SHORT = 300
MAX_TOKENS_LONG = 2000
MAX_TOKENS_COMBINED = 3000

def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key
