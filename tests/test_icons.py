from pathlib import Path

from app.collector.icons import placeholder_svg


def test_placeholder_svg_contains_svg_tag():
    svg = placeholder_svg()
    assert svg.startswith("<svg")
    assert "N/A" in svg


def test_app_icon_has_transparent_background():
    svg = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "icon.svg").read_text(encoding="utf-8")
    canvas_path = "M0 0 C378.84 0 757.68 0 1148 0 C1148 306.24 1148 612.48 1148 928"

    assert f'{canvas_path} C769.16 928 390.32 928 0 928 C0 621.76 0 315.52 0 0 Z "' not in svg
    assert f'{canvas_path} C769.16 928 390.32 928 0 928 C0 621.76 0 315.52 0 0 Z M570.25' not in svg
