"""No translatable template string may contain a bare percent sign.

Jinja's i18n extension ends `gettext` with `return rv % variables` — "always treat
as a format string, even if there are no variables" — so `_('95% CI')` raises
`ValueError: unsupported format character 'C'` the moment the template renders. It
passes ruff, passes template compilation, and passes `pybabel compile`; only an
actual render of that exact branch catches it, which is how it reached production
three times. This scans the source instead, so no branch can hide.

Write `%%` for a literal percent, or use a `%(name)s` placeholder.
"""

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "olim" / "templates"

#: `_("...")` / `_('...')`, tolerating escaped quotes inside.
GETTEXT_CALL = re.compile(r"""_\(\s*(['"])((?:\\.|(?!\1).)*)\1""", re.S)
#: A well-formed %(name)s style conversion.
NAMED_CONVERSION = re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdfrgex]")


def bare_percent(text: str) -> bool:
    """True when a percent survives after removing valid escapes and placeholders."""
    return "%" in NAMED_CONVERSION.sub("", text).replace("%%", "")


def template_files():
    return sorted(TEMPLATES.rglob("*.html"))


@pytest.mark.parametrize("path", template_files(), ids=lambda p: str(p.name))
def test_no_bare_percent_in_translatable_strings(path):
    source = path.read_text()
    offenders = [
        (source[: m.start()].count("\n") + 1, m.group(2))
        for m in GETTEXT_CALL.finditer(source)
        if bare_percent(m.group(2))
    ]
    assert not offenders, "\n".join(
        f"{path}:{line} — {text!r} (use %% for a literal percent)" for line, text in offenders
    )


class TestTheDetectorItself:
    @pytest.mark.parametrize(
        "text",
        ["95% CI", "100% done", "50%", "a % b"],
    )
    def test_flags_a_bare_percent(self, text):
        assert bare_percent(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "95%% CI",
            "%(pct)s%% complete",
            "Round %(n)s",
            "no percent here at all",
            "%(a)s and %(b)s",
        ],
    )
    def test_accepts_escapes_and_placeholders(self, text):
        assert bare_percent(text) is False

    def test_the_regression_that_prompted_this(self):
        """`_('95% CI')` in the active learning status bar 500'd the whole loop."""
        assert bare_percent("95% CI") is True
        assert bare_percent("95%% CI") is False
