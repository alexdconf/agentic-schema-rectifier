#!/bin/bash
set -e

echo "Running tests..."
PYTHONPATH=src uv run python -m unittest discover -s tests
echo "Tests passed!"
