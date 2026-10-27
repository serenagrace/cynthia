"""Naming helpers for encounter timing logs."""

import re

DEFAULT_ENCOUNTER_LOG = "encounter_times.log"


def encounter_log_name(hunt=None):
    """Per-hunt log filename, e.g. "Ho-Oh" -> encounter_times.hooh.log."""
    slug = re.sub(r"[^a-z0-9]", "", (hunt or "").lower())
    if not slug:
        return DEFAULT_ENCOUNTER_LOG
    return f"encounter_times.{slug}.log"
