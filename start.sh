#!/usr/bin/env bash
python -m gunicorn app:app --bind 0.0.0.0:$PORT