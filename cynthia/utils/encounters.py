"""Naming helpers for encounter timing logs."""

import re
from dataclasses import dataclass, field
from datetime import datetime

DEFAULT_ENCOUNTER_LOG = "encounter_times.log"
STOP_MARKER = "#STOP"
START_MARKER = "#START"


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


def marker_line(kind, reason=""):
    """Log line recording that hunting stopped (#STOP) or started (#START)."""
    return f"{datetime.now()},{kind},{reason}\n"


def _marker_kind(line):
    fields = line.split(",", 2)
    if len(fields) > 1 and fields[1].strip() in (STOP_MARKER, START_MARKER):
        return fields[1].strip()
    return None


@dataclass
class EncounterLog:
    """Parsed encounter log: encounter stamps plus intervals when not hunting (epoch ms)."""

    encounters: list = field(default_factory=list)
    pauses: list = field(default_factory=list)
    first: int = None
    stopped_at: int = None

    @property
    def paused_ms(self):
        """Total time in completed pauses."""
        return sum(end - start for start, end in self.pauses)

    def paused_between(self, a, b):
        """Time in completed pauses that falls inside [a, b]."""
        return sum(max(0, min(b, e) - max(a, s)) for s, e in self.pauses)


def parse_encounter_log(lines):
    """Split log lines into encounters and stop/start pauses.

    A #START with no preceding #STOP (e.g. after a crash) is treated as a pause
    beginning at the previous log entry.
    """
    log = EncounterLog()
    last = None
    for line in lines:
        stamp = log_timestamp_ms(line)
        if stamp is None:
            continue
        if log.first is None:
            log.first = stamp
        kind = _marker_kind(line)
        if kind == STOP_MARKER:
            if log.stopped_at is None:
                log.stopped_at = stamp
        elif kind == START_MARKER:
            began = log.stopped_at if log.stopped_at is not None else last
            if began is not None and stamp > began:
                log.pauses.append((began, stamp))
            log.stopped_at = None
        else:
            log.encounters.append(stamp)
        last = stamp
    return log


def average_interval_ms(lines, outlier_factor=3, min_samples=0):
    """Mean time in ms between consecutive encounters, or None if unavailable.

    Returns None when fewer than min_samples gaps exist. Time spent not hunting
    (between #STOP and #START markers) is excluded from each gap.

    Gaps above outlier_factor x the median are dropped, since long gaps
    usually mean the bot was not running between encounters.
    """
    log = parse_encounter_log(lines)
    stamps = log.encounters
    gaps = [
        b - a - log.paused_between(a, b) for a, b in zip(stamps, stamps[1:]) if b > a
    ]
    gaps = [g for g in gaps if g > 0]
    if not gaps or len(gaps) < min_samples:
        return None
    ordered = sorted(gaps)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else sum(ordered[mid - 1 : mid + 1]) / 2
    kept = [g for g in gaps if g <= median * outlier_factor]
    return sum(kept) / len(kept)
