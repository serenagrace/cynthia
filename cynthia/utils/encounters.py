"""Naming helpers for encounter timing logs."""

import re

DEFAULT_ENCOUNTER_LOG = "encounter_times.log"


def encounter_log_name(hunt=None):
    """Per-hunt log filename, e.g. "Ho-Oh" -> encounter_times.hooh.log."""
    slug = re.sub(r"[^a-z0-9]", "", (hunt or "").lower())
    if not slug:
        return DEFAULT_ENCOUNTER_LOG
    return f"encounter_times.{slug}.log"


def average_encounter_ms(lines, outlier_factor=3):
    """Mean encounter time in ms from log lines, or None if unavailable.

    Times above outlier_factor x the median are dropped, since long gaps
    usually mean the bot was not running between encounters.
    """
    times = []
    for line in lines:
        try:
            value = float(line.rsplit(",", 1)[1])
        except (IndexError, ValueError):
            continue
        if value > 0:
            times.append(value)
    if not times:
        return None
    ordered = sorted(times)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else sum(ordered[mid - 1 : mid + 1]) / 2
    kept = [t for t in times if t <= median * outlier_factor]
    return sum(kept) / len(kept)
