#!/bin/bash
set -e

echo "Starting the application stack..."
docker compose up --build
