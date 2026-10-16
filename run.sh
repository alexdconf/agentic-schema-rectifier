#!/bin/bash
set -e

# 1. Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

# 2. Check if Ollama is running (checks the default port 11434)
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Error: Ollama is not running. Please start Ollama and try again."
    exit 1
fi

echo "Starting the application stack..."
docker compose up --build
