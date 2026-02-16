"""
Gateway entry point for uvicorn.

This file exists to allow proper package imports when running via uvicorn.
"""

import sys
from pathlib import Path

# Add parent directory to path to allow 'gateway' package imports
gateway_dir = Path(__file__).parent
parent_dir = gateway_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

# Now import the app from the gateway package
from gateway.main import app  # noqa: E402

__all__ = ["app"]
