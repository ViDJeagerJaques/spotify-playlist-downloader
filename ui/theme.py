"""NX9 theme — design tokens and the CSS Streamlit renders once per rerun.

WHAT THIS IS (and is not)
-------------------------
The original NX9 "Neural Gateway" design has an animated WebGL/Three.js
background: particles, dither, atmosphere. **Streamlit cannot render that as a
page background**, and emulating it with heavy JS would fight the framework's
full-page rerun on every interaction. The user agreed to colour + typography
only, so that is exactly what ships here. No animation, no canvas, no WebGL.

Tokens (from the design spec)
-----------------------------
    accent / primary    #A8D055   neon green
    background          #050F05   near-black, green cast
    surface             #18181B
    text primary        #FFFFFF
    text secondary      #A1A1AA
    border              #27272A
    display/body font   Inter
    label/mono font     JetBrains Mono
    radius card         8px
    radius pill         9999px
    spacing base        8px
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# design tokens
# --------------------------------------------------------------------------
PRIMARY = "#A8D055"
BACKGROUND = "#050F05"
SURFACE = "#18181B"
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#A1A1AA"
BORDER = "#27272A"
RADIUS = "8px"
RADIUS_PILL = "9999px"
SPACING = "8px"

FONT_SANS = "Inter"
FONT_MONO = "JetBrains Mono"

# Square artwork helper: Spotify-style covers are 1:1, but st.image preserves
# the source ratio, so we force the box and crop with object-fit.
SQUARE_ART_CSS = f"""
<style>
.nx9-art {{
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border-radius: {RADIUS};
    border: 1px solid {BORDER};
}}
.nx9-art-img {{
    width: 100%;
    aspect-ratio: 1 / 1;
    overflow: hidden;
    border-radius: {RADIUS};
    border: 1px solid {BORDER};
    background: {SURFACE};
}}
.nx9-art-img img {{
    width: 100% !important;
    height: 100% !important;
    object-fit: cover;
    display: block;
}}
/* Sized variants used by app.py. The box is always square; only the width
   differs, so a 48px list thumbnail and a 200px header stay 1:1. */
.nx9-art-sm {{
    width: 48px;
}}
/* The Download Lagu table uses a slightly smaller thumbnail. */
.nx9-art-tbl {{
    width: 40px;
    height: 40px;
}}
.nx9-art-lg {{
    width: 200px;
    max-width: 100%;
}}
</style>
"""

NX9_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ---- base typography ------------------------------------------------ */
html, body, [class*="css"] {{
    font-family: '{FONT_SANS}', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
.stApp {{
    background: {BACKGROUND};
}}

/* Monospace for numbers, durations, ids, code — anything tabular. */
code, pre, .nx9-mono, [data-testid="stMetricValue"] {{
    font-family: '{FONT_MONO}', ui-monospace, SFMono-Regular, Menlo, monospace !important;
}}

/* ---- secondary text (captions / hints) ------------------------------ */
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span,
.stCaption {{
    color: {TEXT_SECONDARY} !important;
}}

/* ---- bordered containers (cards) ------------------------------------ */
/* Streamlit marks these with data-testid="borderedContainer". */
[data-testid="borderedContainer"],
[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: {RADIUS} !important;
    border-color: {BORDER} !important;
    background-color: {SURFACE} !important;
    padding: 24px !important;
    transition: border-color .15s ease;
}}
[data-testid="borderedContainer"]:hover,
[data-testid="stVerticalBlockBorderWrapper"]:hover {{
    border-color: {PRIMARY} !important;
}}

/* ---- expander -------------------------------------------------------- */
[data-testid="stExpander"] {{
    border-radius: {RADIUS} !important;
    border-color: {BORDER} !important;
    background-color: {SURFACE};
}}
[data-testid="stExpander"] summary:hover {{
    color: {PRIMARY} !important;
}}

/* ---- buttons: pill radius ------------------------------------------- */
[data-testid="stButton"] button,
[data-testid="stDownloadButton"] button {{
    border-radius: {RADIUS_PILL} !important;
    font-weight: 500 !important;
    font-family: '{FONT_SANS}', sans-serif !important;
    border: 1px solid {BORDER} !important;
    transition: border-color .15s ease, color .15s ease;
}}
[data-testid="stButton"] button:hover,
[data-testid="stDownloadButton"] button:hover {{
    border-color: {PRIMARY} !important;
    color: {PRIMARY} !important;
}}
/* Primary buttons keep the accent fill. */
[data-testid="stButton"] button[kind="primary"],
[data-testid="stDownloadButton"] button[kind="primary"] {{
    background-color: {PRIMARY} !important;
    color: #050F05 !important;
    border-color: {PRIMARY} !important;
}}
[data-testid="stButton"] button[kind="primary"]:hover,
[data-testid="stDownloadButton"] button[kind="primary"]:hover {{
    filter: brightness(1.08);
    color: #050F05 !important;
}}

/* ---- inputs ---------------------------------------------------------- */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stRadio"] label,
[data-baseweb="input"] {{
    border-radius: {RADIUS} !important;
    border-color: {BORDER} !important;
    background-color: {SURFACE} !important;
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within {{
    border-color: {PRIMARY} !important;
    box-shadow: 0 0 0 1px {PRIMARY} !important;
}}

/* ---- sidebar --------------------------------------------------------- */
[data-testid="stSidebar"] {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER};
}}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    font-family: '{FONT_SANS}', sans-serif !important;
    letter-spacing: -0.01em;
}}

/* Active nav item gets the accent dot colour. */
[data-testid="stSidebar"] .stRadio label p {{
    font-weight: 500;
}}

/* ---- tabs ------------------------------------------------------------ */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
    gap: {SPACING};
    border-bottom: 1px solid {BORDER};
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
    border-radius: {RADIUS} {RADIUS} 0 0;
    padding: {SPACING} 16px;
}}
[data-testid="stTabs"] [aria-selected="true"] {{
    color: {PRIMARY} !important;
}}

/* ---- track list (#5): one row per song ------------------------------- */
.nx9-track {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    border-radius: {RADIUS};
    border: 1px solid transparent;
}}
.nx9-track:hover {{
    background: {SURFACE};
    border-color: {BORDER};
}}
.nx9-track-index {{
    font-family: '{FONT_MONO}', monospace;
    color: {TEXT_SECONDARY};
    font-size: 12px;
    min-width: 22px;
    text-align: right;
}}
.nx9-track-art {{
    width: 48px;
    height: 48px;
    min-width: 48px;
    border-radius: 6px;
    object-fit: cover;
    border: 1px solid {BORDER};
    background: {SURFACE};
}}
.nx9-track-body {{
    flex: 1;
    min-width: 0;
}}
.nx9-track-title {{
    color: {TEXT_PRIMARY};
    font-weight: 500;
    font-size: 14px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-track-sub {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-track-dur {{
    font-family: '{FONT_MONO}', monospace;
    color: {TEXT_SECONDARY};
    font-size: 12px;
    white-space: nowrap;
}}

/* Download Lagu table (Spotify-style columns).
   Every cell is one line with an ellipsis — long titles and album names must
   never wrap, otherwise row heights drift and the table stops reading as rows. */
.nx9-cell-title {{
    color: {TEXT_PRIMARY};
    font-weight: 600;
    font-size: 14px;
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-cell-sub {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-cell-dur {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
    text-align: right;
    white-space: nowrap;
}}
.nx9-num {{
    font-size: 12px;
    text-align: left;
    color: {TEXT_SECONDARY};
}}
.nx9-head {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}}

/* ---------------------------------------------------------------------------
   Download Lagu table — CSS Grid, one HTML block per row.

   Why not st.columns(): Streamlit's stHorizontalBlock has a built-in 16px gap
   (verified: getComputedStyle(...).gap === "16px" on 1.63.0). Seven columns per
   row means six gaps = 96px of dead space, and the narrow columns around the
   checkbox/button widgets get squeezed so the artwork spills out of its own
   column. Grid gives us exact pixel control and guarantees every row uses the
   same template, so columns cannot drift between rows.

   Two rules below are load-bearing, not decoration:
     * minmax(0, 1fr) on the title column — a bare `1fr` is minmax(auto, 1fr),
       so the column refuses to shrink below the longest word and the ellipsis
       never triggers.
     * min-width: 0 on .nx9-tbl-body — a grid item defaults to min-width:auto
       for the same reason. Both must stay together.
   --------------------------------------------------------------------------- */
/* Row height is chosen to match what Streamlit reserves for the widgets.
   Measured: the row block reserves the action slot's height, and any grid
   content taller than that overflows instead of growing the block. So the
   artwork is 40px and padding + border keep the grid at 52px, comfortably inside
   the 54px the action slot needs — see the alignment note further down.

   The earlier 48px artwork produced a 66px grid that overflowed a 50px block,
   which is what left the Unduh button floating above the cover.
   Widths are tuned so the title column stays wide: Streamlit's default
   .block-container caps the app at 736px, so every fixed track here is stolen
   from the title. */
.nx9-tbl-row {{
    display: grid;
    grid-template-columns: 28px 40px minmax(0, 1fr) minmax(0, 140px) 44px;
    align-items: center;
    gap: 10px;
    padding: 9px 10px;
    border-radius: {RADIUS};
    border: 1px solid transparent;
}}
.nx9-tbl-row:hover {{
    background: {SURFACE};
    border-color: {BORDER};
}}
.nx9-tbl-num {{
    font-family: '{FONT_MONO}', monospace;
    color: {TEXT_SECONDARY};
    font-size: 12px;
    text-align: right;
}}
/* Stays a filled square even when the image 404s or the track has no artwork:
   background + fixed aspect-ratio means a failed <img> degrades to a grey tile,
   never to a collapsed/roboh box. */
.nx9-tbl-art {{
    width: 40px;
    height: 40px;
    aspect-ratio: 1 / 1;
    overflow: hidden;
    border-radius: 6px;
    background: {SURFACE};
}}
.nx9-tbl-art img {{
    width: 100% !important;
    height: 100% !important;
    object-fit: cover;
    display: block;
}}
.nx9-tbl-body {{
    min-width: 0;
}}
.nx9-tbl-title {{
    color: {TEXT_PRIMARY};
    font-weight: 600;
    font-size: 14px;
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-tbl-sub {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-tbl-dur {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
    text-align: right;
    font-family: '{FONT_MONO}', monospace;
    white-space: nowrap;
}}
/* Header captions reuse the exact same grid template as the rows, otherwise the
   caption sits at a different x than the data underneath it. */
.nx9-tbl-head {{
    color: {TEXT_SECONDARY};
    font-size: 11px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-weight: 600;
}}
/* Narrow screens: drop the album column before the title is squeezed. */
@media (max-width: 900px) {{
    .nx9-tbl-row {{
        grid-template-columns: 28px 40px minmax(0, 1fr) 44px;
    }}
    .nx9-tbl-album {{
        display: none;
    }}
}}

/* Kill Streamlit's built-in inter-column gap. The table renders each row as
   [grid HTML][actions] in its own stHorizontalBlock, and 16px of gutter between
   just two columns pushes the grid off-centre. This is safe to do globally
   because it only removes spacing; column widths still come from flex. */
.stHorizontalBlock {{
    gap: 0 !important;
}}
.stHorizontalBlock > [data-testid="stColumn"] {{
    padding-left: 2px;
    padding-right: 2px;
}}
/* Line the actions up with the artwork.
   Streamlit reserves the row's height from the widget column and top-aligns
   everything in the block, so the Unduh button and the 40px cover do not share
   a baseline. The offsets are all fixed numbers, so they can be balanced
   arithmetically rather than with a fragile "centre it" override:

     cover top   = 3px left-column margin + 1px border + 9px row padding = 13px
     button top  = 13px top margin on the action column

   The grid row is 60px (40px artwork + 2x9 padding + 2x1 border) while the
   action slot needs only 50px, so the block height comes from the grid and the
   two columns stop fighting over it. `:has()` keys off `.nx9-tbl-data` and is
   deliberately not nested inside another `:has()` — a nested one makes the
   selector invalid and the browser drops the rule silently. */
.stHorizontalBlock:has(.nx9-tbl-data) > [data-testid="stColumn"]:last-child {{
    margin-top: 13px;
}}

/* Pill badge (e.g. part labels, backend tags). */
.nx9-pill {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: {RADIUS_PILL};
    border: 1px solid {BORDER};
    background: {SURFACE};
    color: {TEXT_SECONDARY};
    font-family: '{FONT_MONO}', monospace;
    font-size: 11px;
}}
.nx9-pill-accent {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: {RADIUS_PILL};
    border: 1px solid {PRIMARY};
    background: transparent;
    color: {PRIMARY};
    font-family: '{FONT_MONO}', monospace;
    font-size: 11px;
}}

/* Playlist header card. */
.nx9-header {{
    display: flex;
    gap: 24px;
    align-items: flex-end;
    padding: 24px;
    border-radius: {RADIUS};
    border: 1px solid {BORDER};
    background: {SURFACE};
}}
.nx9-header-art {{
    width: 200px;
    height: 200px;
    min-width: 200px;
    border-radius: {RADIUS};
    object-fit: cover;
    border: 1px solid {BORDER};
    background: {BACKGROUND};
}}
.nx9-header-title {{
    font-size: 30px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
    line-height: 1.2;
    margin: 0 0 6px 0;
}}
.nx9-header-meta {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
}}
</style>
"""


def inject_theme() -> None:
    """Render the NX9 stylesheet. Call once, before any page content."""
    import streamlit as st

    st.markdown(NX9_CSS, unsafe_allow_html=True)
    st.markdown(SQUARE_ART_CSS, unsafe_allow_html=True)