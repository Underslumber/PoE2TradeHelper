from app.collector.icons import placeholder_svg


def test_placeholder_svg_contains_svg_tag():
    svg = placeholder_svg()
    assert svg.startswith("<svg")
    assert "N/A" in svg
