import numpy
import pytest


def test_change_grip_order_is_scored_without_matching_other_screens():
    from cynthia.daemons.cv import CV, _score_scenes

    scene = CV.change_grip_order_scene
    frame = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    frame[scene.y : scene.y + scene.h, scene.x : scene.x + scene.w] = scene.buffer
    scores, _ = _score_scenes(frame, 0)
    assert scores["change_grip_order"] > 0.98
    frame[:] = 0
    scores, _ = _score_scenes(frame, 1_000_000_000)
    assert scores["change_grip_order"] < 0.98


def test_quick_settings_scene_matches_template():
    from cynthia.daemons.cv import CV

    scene = CV.quick_settings_scene
    frame = numpy.zeros((scene.y + scene.h, scene.x + scene.w, 3), dtype=numpy.uint8)
    frame[scene.y : scene.y + scene.h, scene.x : scene.x + scene.w] = scene.buffer
    assert scene.ssim_match(frame) > CV.QUICK_SETTINGS_THRESHOLD

    frame[scene.y : scene.y + scene.h, scene.x : scene.x + scene.w] = 255
    assert scene.ssim_match(frame) <= CV.QUICK_SETTINGS_THRESHOLD


def test_scrape_text_crops_columns_as_well_as_rows(monkeypatch):
    from cynthia.daemons.cv import CV

    seen = []
    monkeypatch.setattr(CV, "_recognize", lambda gray: seen.append(gray.shape) or "x")
    CV.scrape_text(numpy.zeros((1080, 1920, 3), dtype=numpy.uint8), y=870, h=260, w=860)

    assert seen == [(210, 860)]


def test_fast_ssim_matches_skimage():
    from skimage.metrics import structural_similarity

    from cynthia.daemons.cv import _window_stats, fast_ssim

    rng = numpy.random.default_rng(0)
    ref = rng.integers(0, 255, (90, 120, 3), dtype=numpy.uint8)
    other = numpy.clip(ref + rng.normal(0, 20, ref.shape), 0, 255).astype(numpy.uint8)
    ref_f = ref.astype(numpy.float32)
    got = fast_ssim(ref_f, _window_stats(ref_f), other)
    assert abs(got - structural_similarity(ref, other, channel_axis=-1)) < 1e-4


def test_scene_reuses_score_within_interval_and_rejects_far_frames():
    from cynthia.daemons.cv import Scene

    ref = numpy.full((64, 64, 3), 100, dtype=numpy.uint8)
    scene = Scene(ref, w=64, h=64, scale=1.0, interval=1.0, reject=30)
    assert scene.ssim_match(ref, 1.0, now_ns=0) > 0.99
    white = numpy.full_like(ref, 255)
    assert scene.ssim_match(white, 1.0, now_ns=5e8) > 0.99  # cached
    assert scene.ssim_match(white, 1.0, now_ns=2e9) == 0.0  # rejected


@pytest.mark.parametrize("final_scene", ["elgato_no_signal", "change_grip_order"])
def test_cv_worker_preserves_encounter_state_and_releases_frames(
    monkeypatch, tmp_path, final_scene
):
    """Exercise the real worker orchestration without OCR, capture, or a child process."""
    import io
    from types import SimpleNamespace

    from cynthia.daemons import cv
    from cynthia.utils.drive import Drive

    def initialize(self, dman, *args, **kwargs):
        """Replace process-backed namespaces with local test state."""
        self.ns = SimpleNamespace(run=True)
        self.uns = dman.uns

    monkeypatch.setattr(cv.Daemon, "__init__", initialize)
    monkeypatch.setattr(cv.CVDaemon, "start", lambda self: None)
    monkeypatch.setattr(cv, "get_ocr", lambda: None)
    monkeypatch.setattr(cv.os, "nice", lambda value: None)
    monkeypatch.setattr(cv.UVC, "frame_to_buffer", lambda frame: io.BytesIO(b"png"))
    monkeypatch.setattr(cv.CV, "scrape_text", lambda *a, **k: "Pokémon Shining Pearl")
    scores = iter(("home", "home", "bdsp_tbox", "bdsp_tbox", final_scene))
    texts = iter(("A wild Pokémon appeared!", ""))

    def score(frame, stamp, **kwargs):
        """Feed deterministic scenes and the encounter-start OCR text."""
        scene = next(scores)
        if scene == "home" and stamp == 6_000_000_000:
            monkeypatch.setattr(cv.CV, "scrape_text", lambda *a, **k: " \t")
        if scene == "bdsp_tbox":
            text = next(texts)
            monkeypatch.setattr(cv.CV, "scrape_text", lambda *a, **k: text)
        return {scene: 1.0}, None

    monkeypatch.setattr(cv, "_score_scenes", score)
    dman = SimpleNamespace(
        uns=SimpleNamespace(),
        drive=Drive(tmp_path),
        context=SimpleNamespace(args=SimpleNamespace(hunt="Cresselia")),
    )
    daemon = cv.CVDaemon(dman)
    claims = []

    class Ring:
        """Supply five accepted frames and then end the worker."""

        def wait_frame(self, last_seq, timeout):
            """Return the next timestamped frame or request shutdown."""
            if last_seq == 5:
                daemon.ns.run = False
                return None
            claim = SimpleNamespace(
                seq=last_seq + 1,
                time_ns=(last_seq + 1) * 3_000_000_000,
                frame=numpy.zeros(cv.FB0.shape(), dtype=numpy.uint8),
                released=False,
            )
            claim.release = lambda: setattr(claim, "released", True)
            claims.append(claim)
            return claim

    drive = dman.drive
    daemon.loop(daemon.ns, daemon.uns, Ring(), drive)
    assert all(claim.released for claim in claims)
    assert daemon.ns.game == "Pokémon Shining Pearl"
    assert not daemon.ns.home and not daemon.ns.playing
    assert daemon.uns.nxbt_daemon_stop
    assert daemon.uns.last_encounter_time is not None
    assert daemon.ns.png == b"png"
    log = drive.path(daemon.ns.encounter_log).read_text()
    assert ",Pokémon Shining Pearl,3000.000000" in log
