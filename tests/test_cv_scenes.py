import numpy


def test_quick_settings_scene_matches_template():
    from cynthia.daemons.cv import CV

    scene = CV.quick_settings_scene
    frame = numpy.zeros((scene.y + scene.h, scene.x + scene.w, 3), dtype=numpy.uint8)
    frame[scene.y : scene.y + scene.h, scene.x : scene.x + scene.w] = scene.buffer
    assert scene.ssim_match(frame) > CV.QUICK_SETTINGS_THRESHOLD

    frame[scene.y : scene.y + scene.h, scene.x : scene.x + scene.w] = 255
    assert scene.ssim_match(frame) <= CV.QUICK_SETTINGS_THRESHOLD
