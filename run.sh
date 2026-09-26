#!/usr/bin/env bash
# Smart Resume & Cover Letter Generator (Scale) — ./run.sh [Input/file.xlsx] [--model X] [--workers N] [--redo]
cd "$(dirname "$0")"
python3 run.py "$@"
