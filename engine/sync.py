"""Standalone Supabase sync step for chained jobs.

Usage: python -m engine.sync
"""
from __future__ import annotations

from . import storage


def main():
    if storage.supabase_enabled():
        print(storage.sync_to_supabase())
    else:
        print("supabase not enabled")


if __name__ == "__main__":
    main()
