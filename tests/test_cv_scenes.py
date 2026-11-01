import numpy


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
    import cv2
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
