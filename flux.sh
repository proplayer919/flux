#!/usr/bin/env bash

# Detect if sudo has been used to run this script, if not, warn the user
if [ "$EUID" -ne 0 ]; then
  echo "Flux requires elevated permissions to run."
  exit 1
fi

# Run the CLI
python3 /opt/pollypackages/flux/cli.py "$@"