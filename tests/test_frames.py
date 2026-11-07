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


def _sine(frames, phase=0):
    import numpy

    t = numpy.arange(frames) + phase
    wave = 3000 * numpy.sin(2 * numpy.pi * 440 * t / 48000)
    return numpy.stack([wave, -wave], axis=1).round().astype(numpy.int16)


def _repair_in_chunks(audio, chunk_frames):
    from cynthia.daemons.audio import DropoutRepair

    repair = DropoutRepair()
    raw = audio.tobytes()
    step = chunk_frames * 4
    out = b"".join(repair.process(raw[i : i + step]) for i in range(0, len(raw), step))
    return repair, out


def test_dropout_repair_passes_clean_audio_through_unchanged():
    audio = _sine(4800)
    audio[1500] = (30000, -30000)  # legitimate percussion must remain intact
    audio[1000:1003] = 0  # a zero run in only some frames is not a dropout
    audio[1000:1003, 1] = 7
    repair, out = _repair_in_chunks(audio, 333)
    assert repair.repaired == 0
    assert out == audio[: -repair.HOLD].tobytes()


def test_dropout_repair_bridges_card_dropouts_split_across_reads():
    import numpy

    clean = _sine(4800)
    audio = clean.copy()
    # The card splices a packet early, then writes garbage and three zero frames
    audio[2000:2049] = _sine(49, phase=2000 + 300)
    audio[2049] = (30000, -30000)
    audio[2050:2053] = 0
    audio[2053:] = _sine(len(audio) - 2053, phase=2053 + 300)
    repair, out = _repair_in_chunks(audio, 2051)  # read ends inside the zeros
    fixed = numpy.frombuffer(out, numpy.int16).reshape(-1, 2).astype(int)
    assert repair.repaired == 1
    assert not (fixed[2040:2060] == 0).all(axis=1).any()
    jumps = numpy.abs(numpy.diff(fixed[1990:2070], 2, axis=0)).max()
    assert (
        jumps < numpy.abs(numpy.diff(audio[1990:2070].astype(int), 2, axis=0)).max() / 4
    )


def test_dropout_repair_smooths_step_when_trailing_curvature_peak_is_larger():
    import numpy

    audio = _sine(4800)
    audio[2000:] += numpy.array([1500, -1500], numpy.int16)
    audio[2049] = (30000, -30000)
    audio[2050:2053] = 0
    repair, out = _repair_in_chunks(audio, 480)
    fixed = numpy.frombuffer(out, numpy.int16).reshape(-1, 2).astype(int)
    assert repair.repaired == 1
    assert numpy.abs(numpy.diff(fixed[1990:2030], 2, axis=0)).max() < 200
    assert numpy.array_equal(fixed[:1988], audio[:1988])
    assert numpy.array_equal(fixed[2060:2100], audio[2060:2100])


def test_dropout_splice_bridge_is_identical_across_read_boundaries():
    import numpy

    audio = _sine(4800)
    audio[2000:] += numpy.array([1500, -1500], numpy.int16)
    audio[2049] = (30000, -30000)
    audio[2050:2053] = 0
    _, expected = _repair_in_chunks(audio, len(audio))
    for size in (1, 333, 2050, 2051, 2052, 2053):
        repair, actual = _repair_in_chunks(audio, size)
        assert repair.repaired == 1
        assert actual == expected


def test_dropout_repair_reconstructs_corrupt_packet_interior_not_only_edges():
    import numpy

    clean = _sine(4800)
    audio = clean.copy()
    audio[2000:2049] += numpy.tile(
        numpy.array([[8000, -8000], [-8000, 8000]], numpy.int16), (25, 1)
    )[:49]
    audio[2049] = (30000, -30000)
    audio[2050:2053] = 0
    repair, out = _repair_in_chunks(audio, 333)
    fixed = numpy.frombuffer(out, numpy.int16).reshape(-1, 2).astype(int)
    assert repair.repaired == 1
    assert numpy.abs(fixed[2000:2053] - clean[2000:2053].astype(int)).max() < 500
    assert numpy.array_equal(fixed[2053:2100], clean[2053:2100])


def test_dropout_reconstruction_preserves_high_frequency_audio():
    import numpy

    wave = numpy.rint(
        8000 * numpy.sin(2 * numpy.pi * 13001 * numpy.arange(4800) / 48000)
    ).astype(numpy.int16)
    clean = numpy.column_stack((wave, -wave))
    audio = clean.copy()
    audio[2049] = (30000, -30000)
    audio[2050:2053] = 0
    repair, out = _repair_in_chunks(audio, 2053)
    fixed = numpy.frombuffer(out, numpy.int16).reshape(-1, 2).astype(int)
    assert repair.repaired == 1
    assert numpy.abs(fixed[2001:2053] - clean[2001:2053].astype(int)).max() < 200


def test_dropout_reconstruction_handles_short_startup_context():
    import numpy

    audio = _sine(4800)
    audio[1] = (30000, -30000)
    audio[2:5] = 0
    _, expected = _repair_in_chunks(audio, len(audio))
    repair, out = _repair_in_chunks(audio, 1)
    fixed = numpy.frombuffer(out, numpy.int16).reshape(-1, 2).astype(int)
    assert repair.repaired == 1
    assert out == expected
    assert numpy.abs(fixed[:5]).max() < 3000


def test_dropout_reconstruction_bounds_output_when_predictor_fit_fails(monkeypatch):
    import numpy

    def fail(*args, **kwargs):
        raise numpy.linalg.LinAlgError("Singular audio prediction")

    monkeypatch.setattr(numpy.linalg, "solve", fail)
    audio = _sine(4800)
    audio[2000:2049] = (20000, -20000)
    audio[2049] = (30000, -30000)
    audio[2050:2053] = 0
    repair, out = _repair_in_chunks(audio, 333)
    fixed = numpy.frombuffer(out, numpy.int16).reshape(-1, 2).astype(int)
    assert repair.repaired == 1
    assert numpy.abs(fixed[1997:2053]).max() <= 3000


def test_dropout_repair_preserves_quiet_quantized_zero_crossings():
    import numpy

    wave = numpy.rint(
        64 * numpy.sin(2 * numpy.pi * 50 * numpy.arange(4800) / 48000)
    ).astype(numpy.int16)
    audio = numpy.column_stack((wave, -wave))
    repair, out = _repair_in_chunks(audio, 1)
    assert repair.repaired == 0
    assert out == audio[: -repair.HOLD].tobytes()


def test_dropout_fault_is_counted_once_if_prediction_retains_zero_signature(
    monkeypatch,
):
    from cynthia.daemons.audio import DropoutRepair

    # Simulate a quantized reconstruction which retains the three-zero marker.
    monkeypatch.setattr(DropoutRepair, "_repair", lambda *args: None)
    audio = _sine(4800)
    audio[2049] = (30000, -30000)
    audio[2050:2053] = 0
    repair, _ = _repair_in_chunks(audio, 1)
    assert repair.repaired == 1


def test_dropout_repair_detects_packet_step_even_with_tiny_garbage_frame():
    import numpy

    audio = _sine(4800)
    audio[2000:] += numpy.array([1500, -1500], numpy.int16)
    audio[2049] = (2, -2)
    audio[2050:2053] = 0
    repair, out = _repair_in_chunks(audio, 333)
    fixed = numpy.frombuffer(out, numpy.int16).reshape(-1, 2).astype(int)
    assert repair.repaired == 1
    assert numpy.abs(numpy.diff(fixed[1990:2030], 2, axis=0)).max() < 200
