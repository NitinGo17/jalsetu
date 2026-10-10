"""
JalSetu backend package.

Loads a project-root ``.env`` file if one is present, so ``SARVAM_API_KEY`` can
be set without exporting it by hand in every shell. Dependency-free (no
python-dotenv needed) and it never overwrites a variable that is already set in
the real environment.

The parser is deliberately forgiving, because a .env written by hand on Windows
arrives in several shapes:
  - a UTF-8 BOM at the start of the file (Notepad adds one)
  - Windows (CRLF) line endings
  - ``export KEY=value`` (a habit copied from Linux/macOS shells)
  - values wrapped in single or double quotes
  - spaces around the ``=``

The .env file is for local development only and must never be committed.
"""

import os
from pathlib import Path
from typing import Dict, Optional

BOM = "\ufeff"


def parse_env_text(text: str) -> Dict[str, str]:
    """Parse .env content into a dict. Pure, tolerant, never raises."""
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        # Strip a BOM (file start) and any surrounding whitespace.
        line = raw.lstrip(BOM).strip()
        if not line or line.startswith("#"):
            continue
        # Tolerate a leading `export ` copied from a shell.
        if line.lower().startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lstrip(BOM)
        value = value.strip().strip('"').strip("'").strip()
        if key:
            out[key] = value
    return out


def dotenv_path() -> Path:
    """The .env path JalSetu looks for: the project root, next to requirements.txt."""
    return Path(__file__).resolve().parent.parent / ".env"


def load_dotenv(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Read and parse a .env file. Returns {} if it is missing or unreadable."""
    path = env_path if env_path is not None else dotenv_path()
    try:
        if not path.is_file():
            return {}
        # utf-8-sig transparently drops a BOM; the parser strips one too.
        return parse_env_text(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return {}


def apply_env(pairs: Dict[str, str], environ: Optional[Dict[str, str]] = None) -> None:
    """Apply pairs to the environment, never overwriting a value already set."""
    env = os.environ if environ is None else environ
    for key, value in pairs.items():
        if key and key not in env:
            env[key] = value


def _load_dotenv() -> None:
    apply_env(load_dotenv())


_load_dotenv()
