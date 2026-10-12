"""Verify the NX9 theme ships the right tokens and safe CSS (#2).

Checks the *content* of the stylesheet and the Streamlit theme config, not how
it looks — rendering is verified separately by starting the real app.

Explicitly asserted as ABSENT: WebGL / Three.js / canvas / keyframe animation.
The user agreed to colour + typography only, and Streamlit re-runs the whole page
on every interaction, so heavy animation would make the app unusable.

Run:  python tests/test_theme.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import theme  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


def test_tokens():
    """Design tokens match the NX9 spec exactly."""
    check("theme: primary #A8D055", theme.PRIMARY == "#A8D055", theme.PRIMARY)
    check("theme: background #050F05", theme.BACKGROUND == "#050F05", theme.BACKGROUND)
    check("theme: surface #18181B", theme.SURFACE == "#18181B", theme.SURFACE)
    check("theme: text #FFFFFF", theme.TEXT_PRIMARY == "#FFFFFF", theme.TEXT_PRIMARY)
    check("theme: secondary #A1A1AA", theme.TEXT_SECONDARY == "#A1A1AA", theme.TEXT_SECONDARY)
    check("theme: border #27272A", theme.BORDER == "#27272A", theme.BORDER)
    check("theme: card radius 8px", theme.RADIUS == "8px", theme.RADIUS)
    check("theme: pill radius 9999px", theme.RADIUS_PILL == "9999px", theme.RADIUS_PILL)
    check("theme: spacing 8px", theme.SPACING == "8px", theme.SPACING)
    check("theme: sans is Inter", theme.FONT_SANS == "Inter", theme.FONT_SANS)
    check("theme: mono is JetBrains Mono", theme.FONT_MONO == "JetBrains Mono", theme.FONT_MONO)


def test_config_toml_matches_tokens():
    """config.toml and theme.py must not drift apart."""
    cfg = ROOT / ".streamlit" / "config.toml"
    check("theme: config.toml exists", cfg.exists(), str(cfg))
    if not cfg.exists():
        return
    text = cfg.read_text(encoding="utf-8")
    check("theme: config primary", f'primaryColor = "{theme.PRIMARY}"' in text)
    check("theme: config background", f'backgroundColor = "{theme.BACKGROUND}"' in text)
    check("theme: config surface", f'secondaryBackgroundColor = "{theme.SURFACE}"' in text)
    check("theme: config text", f'textColor = "{theme.TEXT_PRIMARY}"' in text)
    check("theme: config has [theme] section", "[theme]" in text)


def test_css_contains_required_rules():
    css = theme.NX9_CSS
    check("theme: Inter font applied", theme.FONT_SANS in css)
    check("theme: JetBrains Mono applied", theme.FONT_MONO in css)
    check("theme: fonts imported", "@import" in css and "fonts.googleapis.com" in css)
    check("theme: border colour used", theme.BORDER in css)
    check("theme: pill radius on buttons", theme.RADIUS_PILL in css)
    check("theme: square art ratio", "aspect-ratio" in theme.SQUARE_ART_CSS)
    check("theme: square art object-fit", "object-fit" in theme.SQUARE_ART_CSS)
    check("theme: track row styles present", "nx9-track" in css)
    check("theme: header styles present", "nx9-header" in css)


def test_square_art_variants_exist():
    """R3: app.py emits .nx9-art-sm / .nx9-art-lg, so they must be styled."""
    css = theme.SQUARE_ART_CSS
    check("theme: nx9-art-sm variant", ".nx9-art-sm" in css, "missing size variant")
    check("theme: nx9-art-lg variant", ".nx9-art-lg" in css, "missing size variant")
    # Every square box must pin BOTH dimensions or aspect-ratio, otherwise the
    # image renders at the source ratio (the original R3 bug).
    check("theme: img forced square", "height: 100%" in css and
          "object-fit: cover" in css, "img could overflow its box")


def test_app_uses_the_square_art_class():
    """R3 regression: the class must actually be USED, not just defined."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    check("theme: app uses nx9-art-img", "nx9-art-img" in src,
          "the square-art class is defined but never used")
    check("theme: app escapes image urls", "html.escape" in src,
          "cover URLs are not escaped before going into HTML")
    check("theme: app no longer relies on st.image for square art",
          "square via CSS" not in src, "stale comment about square art")


def test_no_heavy_animation():
    """The agreed scope is colour + typography. No WebGL, canvas, or loops."""
    css = theme.NX9_CSS + theme.SQUARE_ART_CSS
    for banned in ("three", "threejs", "webgl", "<canvas", "@keyframes",
                   "requestAnimationFrame", "shader", "particles"):
        check(f"theme: no '{banned}'", banned not in css.lower(), banned)
    # A 150ms hover transition is fine; a spin/loop animation is not.
    check("theme: only short hover transition",
          "@keyframes" not in css and "animation:" not in css)


def test_contrast_is_readable():
    """White on #050F05 is high contrast; the accent on surface must be legible."""
    def luminance(hex_color: str) -> float:
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))

        def lin(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    def ratio(fg: str, bg: str) -> float:
        a, b = luminance(fg) + 0.05, luminance(bg) + 0.05
        hi, lo = max(a, b), min(a, b)
        return hi / lo

    r_text = ratio(theme.TEXT_PRIMARY, theme.BACKGROUND)
    check("theme: white on bg > 12:1", r_text > 12, f"{r_text:.1f}:1")
    r_secondary = ratio(theme.TEXT_SECONDARY, theme.BACKGROUND)
    check("theme: secondary text > 4.5:1", r_secondary > 4.5, f"{r_secondary:.1f}:1")
    r_accent = ratio(theme.PRIMARY, theme.BACKGROUND)
    check("theme: accent on bg > 7:1", r_accent > 7, f"{r_accent:.1f}:1")


def test_streamlit_widgets_targeted_not_broken():
    """CSS must target Streamlit's own testids, not blindly restyle everything."""
    css = theme.NX9_CSS
    for hook in ('data-testid="borderedContainer"',
                 'data-testid="stButton"',
                 'data-testid="stDownloadButton"',
                 'data-testid="stExpander"',
                 'data-testid="stSidebar"',
                 'data-testid="stTextInput"'):
        check(f"theme: hooks {hook}", hook in css)

    # Selectors must be scoped; a bare `*` or bare `input` would wreck widgets.
    check("theme: no global '*' selector", "html *," not in css and "html * {" not in css)


def main():
    test_tokens()
    test_config_toml_matches_tokens()
    test_css_contains_required_rules()
    test_square_art_variants_exist()
    test_app_uses_the_square_art_class()
    test_no_heavy_animation()
    test_contrast_is_readable()
    test_streamlit_widgets_targeted_not_broken()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()