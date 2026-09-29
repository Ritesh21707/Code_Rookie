#!/usr/bin/env sh
cd "$(dirname "$0")" || exit 1
python3 -m unittest discover -s tests -v
