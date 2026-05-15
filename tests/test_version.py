from __future__ import annotations

import re

from app.version import APP_VERSION
from app.web.routes import templates


def test_app_version_is_current_semver() -> None:
    assert APP_VERSION == "0.1.4"
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION)


def test_app_version_is_available_in_templates() -> None:
    assert templates.env.globals["app_version"] == APP_VERSION
