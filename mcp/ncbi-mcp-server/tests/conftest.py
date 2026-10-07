"""Shared pytest configuration.

The project uses a src/ layout and the package is not installed into the venv
(there is no editable install), so src/ is put on sys.path here rather than
requiring `pip install -e .` before the suite can run.
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
