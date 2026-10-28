#!/bin/bash
set -euo pipefail
python -m pip install uv
uv sync --extra test
