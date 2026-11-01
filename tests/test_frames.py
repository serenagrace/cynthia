from cynthia.daemons.frames import AUDIO_BYTES_PER_SEC, AudioRing, FrameRing


def test_audio_ring_wraps_and_returns_what_was_written():
    ring = AudioRing(seconds=1)
    try:
        ring.write(bytes(range(256)) * 600, 100)  # wraps the one-second buffer
        data, pos, end_ns, skipped = ring.read(0, 0.1, max_lag_ms=2000)
        assert pos == ring.total and end_ns == 100
        assert data == (bytes(range(256)) * 600)[-len(data) :]
        assert skipped >= 0
    finally:
        ring.close()


def test_audio_reader_that_falls_behind_jumps_to_the_live_edge():
    ring = AudioRing(seconds=2)
    try:
        ring.write(b"\x01" * AUDIO_BYTES_PER_SEC, 1)
        data, pos, _, skipped = ring.read(0, 0.1, max_lag_ms=250, resume_lag_ms=60)

        assert skipped > 0
        assert len(data) == 60 * AUDIO_BYTES_PER_SEC // 1000
        assert pos == ring.total
        assert ring.read(pos, 0.01) == (b"", pos, 0, 0)
    finally:
        ring.close()


def test_frame_ring_publishes_whole_frames_and_drops_when_all_claimed():
    ring = FrameRing((4, 4, 3))
    try:
        for stamp in (1, 2):
            slot = ring.begin_write()
            ring.view(slot)[:] = stamp
            ring.end_write(slot, stamp, stamp)
        claim = ring.wait_frame(0, 0.1)
        assert claim.seq == 2 and claim.frame[0, 0, 0] == 2
        claim.release()
        assert ring.wait_frame(2, 0.01) is None
    finally:
        ring.close(unlink=True)


def test_audio_capture_only_runs_for_listeners_or_the_obs_feed():
    from types import SimpleNamespace

    from cynthia.daemons.audio import audio_wanted

    assert not audio_wanted(SimpleNamespace())
    assert audio_wanted(SimpleNamespace(audio_listeners=1))
    assert audio_wanted(SimpleNamespace(obs_feeding=True))
    assert not audio_wanted(SimpleNamespace(audio_listeners=0, obs_feeding=False))
