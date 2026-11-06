"""Shared-memory frame and audio rings with locking and wake-ups.

One writer (the capture daemon) publishes frames; any number of readers (CV,
the web stream, the OBS feed) wait for new frames without polling. A slot is
never written while a reader holds a claim on it, and the writer never touches
the slot holding the newest published frame, so readers always see whole,
untorn frames. If every spare slot is claimed the writer drops that frame.
"""

import multiprocessing as mp
from multiprocessing import shared_memory

import numpy

SLOTS = 3
WRITING = -1


class FrameClaim:
    """A reader's hold on one slot; release it as soon as the data is copied."""

    def __init__(self, ring, slot, seq, time_ns, frame_hash):
        """Record the claimed slot and the metadata published with it."""
        self.ring = ring
        self.slot = slot
        self.seq = seq
        self.time_ns = time_ns
        self.hash = frame_hash
        self.frame = ring.view(slot)

    def release(self):
        """Give the slot back so the writer may reuse it."""
        if self.slot is not None:
            self.ring._release(self.slot)
            self.slot = None
            self.frame = None

    def __enter__(self):
        """Use the claim as a context manager."""
        return self

    def __exit__(self, *_):
        """Release the claim on exit."""
        self.release()


class FrameRing:
    """Shared frame slots plus the lock, wake-up condition, and metadata."""

    def __init__(self, shape, slots=SLOTS):
        """Create the shared slots; build it in the parent before forking."""
        self.shape = tuple(shape)
        self.nbytes = int(numpy.prod(self.shape))
        self.shms = [
            shared_memory.SharedMemory(create=True, size=self.nbytes)
            for _ in range(slots)
        ]
        self._views = [
            numpy.ndarray(self.shape, dtype=numpy.uint8, buffer=shm.buf)
            for shm in self.shms
        ]
        self.cond = mp.Condition()
        self._claims = mp.RawArray("i", slots)
        self._times = mp.RawArray("q", slots)
        self._hashes = mp.RawArray("Q", slots)
        self._latest = mp.RawValue("i", -1)
        self._seq = mp.RawValue("q", 0)
        self._last_time = mp.RawValue("q", 0)
        self._last_hash = mp.RawValue("Q", 0)
        self._dropped = mp.RawValue("q", 0)

    @property
    def last_time_ns(self):
        """Capture time of the newest published frame (0 before the first)."""
        return self._last_time.value

    @property
    def last_hash(self):
        """Content hash of the newest published frame (0 before the first)."""
        return self._last_hash.value

    @property
    def seq(self):
        """Sequence number of the newest published frame."""
        return self._seq.value

    @property
    def dropped(self):
        """Frames the writer dropped because no slot was free."""
        return self._dropped.value

    def view(self, slot):
        """Return the numpy view of one slot."""
        return self._views[slot]

    def begin_write(self):
        """Reserve a free slot for writing, or None if every spare slot is claimed."""
        with self.cond:
            for slot in range(len(self._views)):
                if slot != self._latest.value and self._claims[slot] == 0:
                    self._claims[slot] = WRITING
                    return slot
            self._dropped.value += 1
        return None

    def end_write(self, slot, time_ns, frame_hash):
        """Publish a written slot as the newest frame and wake readers."""
        with self.cond:
            self._claims[slot] = 0
            self._times[slot] = time_ns
            self._hashes[slot] = frame_hash
            self._latest.value = slot
            self._seq.value += 1
            self._last_time.value = time_ns
            self._last_hash.value = frame_hash
            self.cond.notify_all()

    def abort_write(self, slot):
        """Return a reserved slot without publishing it."""
        with self.cond:
            self._claims[slot] = 0

    def wait_frame(self, after_seq=0, timeout=None):
        """Block until a frame newer than `after_seq` exists, then claim it.

        Returns None on timeout so callers can check their shutdown flag.
        """
        with self.cond:
            if not self.cond.wait_for(lambda: self._seq.value != after_seq, timeout):
                return None
            slot = self._latest.value
            self._claims[slot] += 1
            return FrameClaim(
                self, slot, self._seq.value, self._times[slot], self._hashes[slot]
            )

    def _release(self, slot):
        """Drop one reader claim on a slot."""
        with self.cond:
            if self._claims[slot] > 0:
                self._claims[slot] -= 1

    def close(self, unlink=False):
        """Close the mapped slots; the creating process may also unlink them."""
        self._views = []
        for shm in self.shms:
            try:
                shm.close()
                if unlink:
                    shm.unlink()
            except (BufferError, FileNotFoundError):
                pass


AUDIO_RATE = 48000
AUDIO_FRAME_BYTES = 4  # 16-bit stereo
AUDIO_BYTES_PER_SEC = AUDIO_RATE * AUDIO_FRAME_BYTES


def audio_bytes_to_ns(count):
    """Duration in nanoseconds of `count` bytes of 48 kHz 16-bit stereo audio."""
    return count * 1_000_000_000 // AUDIO_BYTES_PER_SEC


class AudioRing:
    """Shared PCM ring: one capture writer, any number of catch-up-aware readers.

    Every write records the wall-clock time at which its last sample was
    captured, using the same clock as `FrameRing`, so a consumer can line audio
    up with video. Readers track their own position. A reader that falls behind
    (slow client, stalled encoder) is moved forward to the live edge instead of
    playing stale audio, and the number of skipped bytes is reported.
    """

    def __init__(self, seconds=10):
        """Create the shared byte ring; build it in the parent before forking."""
        self.capacity = seconds * AUDIO_BYTES_PER_SEC
        self._buf = mp.RawArray("B", self.capacity)
        self._view = numpy.frombuffer(self._buf, dtype=numpy.uint8)
        self.cond = mp.Condition()
        self._total = mp.RawValue("Q", 0)
        self._end_ns = mp.RawValue("q", 0)

    @property
    def total(self):
        """Total bytes ever written; the live edge for readers."""
        return self._total.value

    @property
    def last_time_ns(self):
        """Capture time of the newest sample, or 0 if nothing was written."""
        return self._end_ns.value

    def write(self, data, end_ns):
        """Append whole audio frames captured up to `end_ns` and wake readers."""
        data = numpy.frombuffer(data, dtype=numpy.uint8)
        data = data[: len(data) - len(data) % AUDIO_FRAME_BYTES]
        if not len(data):
            return
        data = data[-self.capacity :]
        with self.cond:
            start = self._total.value % self.capacity
            first = min(len(data), self.capacity - start)
            self._view[start : start + first] = data[:first]
            self._view[: len(data) - first] = data[first:]
            self._total.value += len(data)
            self._end_ns.value = end_ns
            self.cond.notify_all()

    def live_position(self, lag_ms=0):
        """Position for a new reader: the live edge, optionally `lag_ms` behind."""
        lag = lag_ms * AUDIO_BYTES_PER_SEC // 1000
        lag -= lag % AUDIO_FRAME_BYTES
        return max(0, self.total - lag)

    def read(self, pos, timeout=None, max_lag_ms=250, resume_lag_ms=60):
        """Wait for audio after `pos`, returning `(data, new_pos, end_ns, skipped)`.

        If the reader is more than `max_lag_ms` behind it jumps to
        `resume_lag_ms` behind the live edge and `skipped` counts the dropped
        bytes. Returns `(b"", pos, 0, 0)` when nothing arrives within `timeout`.
        """
        max_lag = max_lag_ms * AUDIO_BYTES_PER_SEC // 1000
        with self.cond:
            if not self.cond.wait_for(lambda: self._total.value > pos, timeout):
                return b"", pos, 0, 0
            total = self._total.value
            skipped = 0
            if total - pos > min(max_lag, self.capacity):
                new_pos = self.live_position(resume_lag_ms)
                skipped, pos = new_pos - pos, new_pos
            start = pos % self.capacity
            count = total - pos
            first = min(count, self.capacity - start)
            data = bytes(self._view[start : start + first]) + bytes(
                self._view[: count - first]
            )
            end_ns = self._end_ns.value
        return data, total, end_ns, skipped

    def close(self):
        """Drop the numpy view so the shared array can be released."""
        self._view = None
