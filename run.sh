#!/bin/sh
# Start pewpew (finger-gun virtual camera + BlackHole mic passthrough).
set -eu
cd "$(dirname "$0")"
exec .venv/bin/python app.py "$@"
