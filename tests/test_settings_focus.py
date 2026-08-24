"""Presentation contract for keyboard focus feedback in settings inputs."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QSpinBox, QWidget

from kotonoha.config import Config
from kotonoha.settings_dialog import SettingsDialog


def _widget_rgb_colors(widget: QWidget) -> set[tuple[int, int, int]]:
    """Return the colors actually rendered by a widget, including its border."""
    image = widget.grab().toImage()
    return {
        (
            image.pixelColor(x, y).red(),
            image.pixelColor(x, y).green(),
            image.pixelColor(x, y).blue(),
        )
        for x in range(image.width())
        for y in range(image.height())
    }


def test_focused_input_renders_the_configured_accent_ring(qapp) -> None:
    """A focused input visibly uses the configured accent as its focus ring."""
    dialog = SettingsDialog(Config(accent_start="#FF4FA3"))
    dialog.show()
    dialog.activateWindow()
    QApplication.setActiveWindow(dialog)
    qapp.processEvents()

    field = dialog.findChildren(QSpinBox)[0]
    field.clearFocus()
    qapp.processEvents()
    unfocused = _widget_rgb_colors(field)

    field.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    focused = _widget_rgb_colors(field)

    assert field.hasFocus()
    assert (255, 79, 163) not in unfocused
    assert (255, 79, 163) in focused
    dialog.close()
