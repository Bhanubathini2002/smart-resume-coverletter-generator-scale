#!/usr/bin/env bash
# Intern / Entry-Level Resume & Cover Letter Generator — ./run.sh [Input/file.xlsx] [--model X] [--workers N] [--redo]
cd "$(dirname "$0")"
python3 run.py "$@"
