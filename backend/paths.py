"""Shared filesystem locations.

The Python lives in backend/, but frontend/ and the data folders (bibles/,
songs/, themes/, schedules/, theme_uploads/) sit at the repo root — one level up.
"""
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
