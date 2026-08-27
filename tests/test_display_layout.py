import pytest

from kotonoha.display.layout import FontFitPolicy


def test_font_fit_policy_returns_stable_window_and_content_budgets():
    policy = FontFitPolicy()

    assert policy.window_width(1920, 20) == 1100
    assert policy.window_width(1920, 80) == 1728
    assert policy.content_width(1100) == 1044


def test_font_fit_policy_decides_overflow_from_renderer_measurement():
    policy = FontFitPolicy()

    fits = policy.decide(100.0, 120.0)
    scrolls = policy.decide(180.0, 120.0)

    assert fits.fits is True
    assert fits.overflow == 0.0
    assert scrolls.fits is False
    assert scrolls.overflow == 60.0


def test_font_fit_policy_rejects_invalid_geometry_or_measurement():
    with pytest.raises(ValueError):
        FontFitPolicy(max_screen_fraction=0.0)
    with pytest.raises(ValueError):
        FontFitPolicy().window_width(0, 20)
    with pytest.raises(ValueError):
        FontFitPolicy().decide(float("nan"), 100.0)
