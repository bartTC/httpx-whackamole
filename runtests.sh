#!/usr/bin/env bash

set -euxo pipefail

for python in 3.{9..14}; do
    uv run --python=${python} --group=dev pytest
done
