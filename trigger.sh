#!/bin/bash

# modeled after what GCS sends a Cloud Function, to trigger
# a cloud event

# Configuration
URL=${1:-"http://localhost:8080"}
BUCKET=${2:-"schema-rectifier-input"}
FILE_NAME=${3:-"example.csv"}

echo "Triggering Cloud Function at $URL"
echo "Simulating file upload for gs://$BUCKET/$FILE_NAME"

curl -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "ce-id: $(uuidgen 2>/dev/null || echo $RANDOM)" \
  -H "ce-specversion: 1.0" \
  -H "ce-type: google.cloud.storage.object.v1.finalized" \
  -H "ce-source: //storage.googleapis.com/projects/_/buckets/$BUCKET" \
  -H "ce-subject: objects/$FILE_NAME" \
  -d "{
    \"bucket\": \"$BUCKET\",
    \"name\": \"$FILE_NAME\",
    \"metageneration\": \"1\",
    \"timeCreated\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
    \"updated\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }"

echo -e "\n\nTrigger sent!"
