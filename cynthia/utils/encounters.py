"""Naming helpers for encounter timing logs."""

import re
from datetime import datetime

DEFAULT_ENCOUNTER_LOG = "encounter_times.log"


def encounter_log_name(hunt=None):
    """Per-hunt log filename, e.g. "Ho-Oh" -> encounter_times.hooh.log."""
    slug = re.sub(r"[^a-z0-9]", "", (hunt or "").lower())
    if not slug:
        return DEFAULT_ENCOUNTER_LOG
    return f"encounter_times.{slug}.log"


def log_timestamp_ms(line):
    """Epoch ms of an encounter log line, or None if the line is malformed."""
    try:
        return int(
            datetime.strptime(
                line.split(",")[0].strip(), "%Y-%m-%d %H:%M:%S.%f"
            ).timestamp()
            * 1000
        )
    except ValueError:
        return None


def average_interval_ms(lines, outlier_factor=3):
    """Mean time in ms between consecutive log entries, or None if unavailable.

    Gaps above outlier_factor x the median are dropped, since long gaps
    usually mean the bot was not running between encounters.
    """
    stamps = []
    for line in lines:
        try:
            stamps.append(
                datetime.strptime(line.split(",")[0].strip(), "%Y-%m-%d %H:%M:%S.%f")
            )
        except ValueError:
            continue
    gaps = [(b - a).total_seconds() * 1000 for a, b in zip(stamps, stamps[1:]) if b > a]
    if not gaps:
        return None
    ordered = sorted(gaps)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else sum(ordered[mid - 1 : mid + 1]) / 2
    kept = [g for g in gaps if g <= median * outlier_factor]
    return sum(kept) / len(kept)
