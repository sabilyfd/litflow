#!/bin/sh
# web-entrypoint.sh
# Runs as root to ensure /jobs is writable by appuser, then drops privileges.
set -e
mkdir -p /jobs
chown -R appuser:appuser /jobs
exec su-exec appuser "$@"
