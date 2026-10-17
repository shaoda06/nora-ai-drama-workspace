#!/bin/sh
set -eu
service_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$service_dir/.venv/bin/python" "$service_dir/scripts/launcher.py" stop
