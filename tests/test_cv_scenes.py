from pathlib import Path

import cv2
import pytest

SCENES = Path(__file__).resolve().parents[1] / "cynthia" / "daemons" / "scenes"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("quick_settings_sample1", True),
        ("quick_settings_sample2", True),
        ("quick_settings_sample3", True),
        ("home_screen_quick_settings", True),
        ("sample_no_quick_settings", False),
        ("switch_home_screen_full", False),
        ("bdsp_boot", False),
    ],
)
def test_quick_settings_scene(name, expected):
    from cynthia.daemons.cv import CV

    frame = cv2.imread(str(SCENES / f"{name}.png"))
    score = CV.quick_settings_scene.ssim_match(frame)
    assert (score > CV.QUICK_SETTINGS_THRESHOLD) == expected
