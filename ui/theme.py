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
   differs, so a list thumbnail and a large header cover stay 1:1. Widths scale
   with the viewport so they do not look tiny on a large monitor or crowd the
   text on a small one. */
.nx9-art-sm {{
    width: clamp(2.75rem, 3vw, 3rem);
}}
.nx9-art-lg {{
    width: clamp(9rem, 14vw, 12.5rem);
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

/* ---- page width ------------------------------------------------------
   app.py already calls st.set_page_config(layout="wide"), and Streamlit 1.63
   implements that by setting the main block container's max-width to `initial`
   (verified: getComputedStyle gives "none" and the box measures the full
   viewport). So there is no 736px cap left to undo — the real problem is the
   opposite one: with no ceiling at all, a 1920px monitor stretches the table to
   1920px, the album column drifts ~1400px away from the title, and there is a
   lake of empty space in the middle. So we add an upper bound only.

   `94vw` keeps a visible gutter on very narrow windows, and the 1600px ceiling
   stops single rows becoming unreadable line lengths. */
.block-container,
[data-testid="stMainBlockContainer"] {{
    max-width: min(1600px, 94vw) !important;
    padding-left: clamp(1rem, 3vw, 3rem) !important;
    padding-right: clamp(1rem, 3vw, 3rem) !important;
}}
/* Very wide screens: hold the ceiling even tighter so rows stay scannable. */
@media (min-width: 1700px) {{
    .block-container,
    [data-testid="stMainBlockContainer"] {{
        max-width: 1600px !important;
    }}
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
/* Every dimension below is clamp()'d so the table scales with the viewport
   instead of being pinned to one screen size. Spacing follows a strict 4/8px
   rhythm (0.25rem = 4px) — no odd 9/10/13/14px values, which is what made the
   earlier version read as arbitrary. */
.nx9-tbl-row {{
    display: grid;
    grid-template-columns:
        clamp(1.75rem, 2vw, 2rem)          /* nomor  28 -> 32px */
        clamp(2.75rem, 3vw, 3rem)          /* cover  44 -> 48px */
        minmax(0, 1fr)                     /* judul          */
        minmax(0, clamp(8rem, 14vw, 16rem))/* album 128 -> 256px */
        clamp(2.5rem, 3vw, 2.75rem);       /* durasi 40 -> 44px */
    align-items: center;
    gap: clamp(0.75rem, 1.5vw, 1rem);
    padding: clamp(0.5rem, 1vw, 0.75rem) clamp(0.75rem, 1.5vw, 1.25rem);
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
    font-size: 0.75rem;
    text-align: right;
}}
/* Stays a filled square even when the image 404s or the track has no artwork:
   background + fixed aspect-ratio means a failed <img> degrades to a grey tile,
   never to a collapsed/roboh box. */
.nx9-tbl-art {{
    width: clamp(2.75rem, 3vw, 3rem);
    height: clamp(2.75rem, 3vw, 3rem);
    aspect-ratio: 1 / 1;
    overflow: hidden;
    border-radius: {RADIUS};
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
/* Type hierarchy: title 15px / sub 13px is a real step, not the 1px gap the
   old 14px / 13px pair had. */
.nx9-tbl-title {{
    color: {TEXT_PRIMARY};
    font-weight: 600;
    font-size: 0.9375rem;
    line-height: 1.4;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-tbl-sub {{
    color: {TEXT_SECONDARY};
    font-size: 0.8125rem;
    line-height: 1.4;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.nx9-tbl-dur {{
    color: {TEXT_SECONDARY};
    font-size: 0.8125rem;
    text-align: right;
    font-family: '{FONT_MONO}', monospace;
    white-space: nowrap;
}}
/* Header captions reuse the exact same grid template as the rows, otherwise the
   caption sits at a different x than the data underneath it. */
.nx9-tbl-head {{
    color: {TEXT_SECONDARY};
    font-size: 0.6875rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-weight: 600;
}}
/* Tablet / small laptop: drop the album column before the title gets squeezed.
   The track count must drop with it — a hidden grid item still occupies its
   track if the template keeps the column, which leaves a hole in the row. */
@media (max-width: 1100px) {{
    .nx9-tbl-row {{
        grid-template-columns: clamp(1.75rem, 2vw, 2rem)
                             clamp(2.75rem, 3vw, 3rem)
                             minmax(0, 1fr)
                             clamp(2.5rem, 3vw, 2.75rem);
    }}
    .nx9-tbl-album {{
        display: none;
    }}
}}
/* Phone / narrow window: the row number goes too, and the touch targets grow. */
@media (max-width: 640px) {{
    .nx9-tbl-row {{
        grid-template-columns: clamp(2.75rem, 3vw, 3rem) minmax(0, 1fr)
                             clamp(2.5rem, 3vw, 2.75rem);
        gap: clamp(0.5rem, 1.5vw, 0.75rem);
    }}
    .nx9-tbl-num {{
        display: none;
    }}
    .nx9-tbl-art {{
        width: clamp(2.75rem, 3vw, 3rem);
        height: clamp(2.75rem, 3vw, 3rem);
    }}
}}

/* Remove Streamlit's built-in inter-column gap, but ONLY on the track-table
   rows. The table renders each row as [grid HTML][actions] in its own
   stHorizontalBlock, and 16px of gutter between just those two columns pushes
   the actions off to the right of the grid.

   This used to be a global `.stHorizontalBlock` rule, which silently removed
   the gutter from every other multi-column row on every page (the cover gallery
   and the button rows ended up with tiles touching). Scoped with :has() so only
   table rows lose it. */
.stHorizontalBlock:has(.nx9-tbl-row) {{
    gap: 0 !important;
    flex-wrap: nowrap !important;
}}
.stHorizontalBlock:has(.nx9-tbl-row) > [data-testid="stColumn"] {{
    padding-left: 2px;
    padding-right: 2px;
}}
/* Give the grid column a zero flex basis so it absorbs whatever is left over.

   This also fixes a wrap bug found at 480px: Streamlit computes the first
   column's basis as `calc(87.72% - 16px)` to make room for its 16px gap. With
   the gap removed but the basis left alone, 351px + a 96px actions column is
   447px inside a 419px row, flex-wrap fires, and the checkbox + button drop onto
   a second line — putting the Unduh button ~47px below the cover. A basis of 0
   keeps the two on one line at any viewport.

   Both rules below key off `:has(.nx9-tbl-row)`, not `.nx9-tbl-data`, so the
   caption row gets the identical split. Otherwise its grid ends up 89px
   narrower than the data rows' grid and the headings sit at different x. */
.stHorizontalBlock:has(.nx9-tbl-row) > [data-testid="stColumn"]:first-child {{
    flex: 1 1 0 !important;
    /* A flex item defaults to min-width:auto, i.e. it refuses to shrink below
       its own min-content width. The grid row contains nowrap (ellipsised)
       text, so without this the column refuses to give ground, flex-wrap fires
       and the actions drop onto their own line. Same reason .nx9-tbl-body needs
       min-width: 0, one level up. */
    min-width: 0 !important;
}}
/* The checkbox + Unduh button need a fixed width; left to a flex ratio they
   shrink below their content and wrap.

   `min-width` is not optional here. On narrow windows Streamlit sets
   `min-width: calc(100% - 24px)` on every column, which at 480px resolves to
   395px inside a 419px block — the actions column swallows the row, the grid
   column is squeezed to 24px and the title track collapses to 0. Overriding
   min-width pins it back to 6rem at every viewport. */
.stHorizontalBlock:has(.nx9-tbl-row) > [data-testid="stColumn"]:last-child {{
    flex: 0 0 6rem !important;
    min-width: 6rem !important;
}}
/* Tighter gutter between the checkbox and the button, so 6rem is comfortable. */
.stHorizontalBlock:has(.nx9-tbl-row) > [data-testid="stColumn"]:last-child
    [data-testid="stHorizontalBlock"] {{
    gap: 0.5rem !important;
}}
/* Empty placeholder cells in the caption row. They keep the row and artwork
   classes so the narrow-screen media queries hide them in step with the data
   rows, but they must neither paint anything nor give the caption row height. */
.nx9-tbl-spacer {{
    background: transparent;
}}
.nx9-tbl-spacer.nx9-tbl-art {{
    height: 0;
}}
/* Line the actions up with the artwork.
   Streamlit reserves the row's height from the widget column and top-aligns
   everything in the block, so the Unduh button and the cover do not share a
   baseline. The offsets are fixed numbers, so they can be balanced
   arithmetically rather than with a fragile "centre it" override:

     cover top  = 3px left-column margin + 1px border + row padding-top
     button top = this margin-top

   The padding is a clamp(), so the margin has to be the same clamp() plus the
   4px of margin+border — a fixed px value here would drift out of alignment at
   every viewport other than the one it was measured at.

   Row height is art (44-48) + 2x padding (16-24) + 2 = 62-74px, while the action
   slot only needs margin + 40px button + 5px = 57-61px, so the block always
   takes its height from the grid and the two columns stop fighting over it.
   `:has()` keys off `.nx9-tbl-data` and is deliberately not nested inside
   another `:has()` — a nested one makes the selector invalid and the browser
   drops the rule silently. */
.stHorizontalBlock:has(.nx9-tbl-data) > [data-testid="stColumn"]:last-child {{
    margin-top: calc(4px + clamp(0.5rem, 1vw, 0.75rem));
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
    gap: clamp(1rem, 2vw, 1.5rem);
    align-items: flex-end;
    padding: clamp(1rem, 2vw, 1.5rem);
    border-radius: {RADIUS};
    border: 1px solid {BORDER};
    background: {SURFACE};
}}
.nx9-header-art {{
    width: clamp(9rem, 14vw, 12.5rem);
    height: clamp(9rem, 14vw, 12.5rem);
    min-width: clamp(9rem, 14vw, 12.5rem);
    border-radius: {RADIUS};
    object-fit: cover;
    border: 1px solid {BORDER};
    background: {BACKGROUND};
}}
.nx9-header-title {{
    font-size: clamp(1.5rem, 2.5vw, 1.875rem);
    font-weight: 700;
    color: {TEXT_PRIMARY};
    line-height: 1.2;
    margin: 0 0 0.5rem 0;
}}
.nx9-header-meta {{
    color: {TEXT_SECONDARY};
    font-size: 0.8125rem;
}}
/* Phone / narrow window: a side-by-side card stops being readable once the
   cover takes up a third of the width, so stack it and shrink the artwork.
   Both the width and the height must be clamped — otherwise the box stops
   being square and the cover gets stretched. */
@media (max-width: 640px) {{
    .nx9-header {{
        flex-direction: column;
        align-items: flex-start;
        gap: 1rem;
    }}
    .nx9-header-art,
    .nx9-art-lg {{
        width: clamp(6rem, 25vw, 8rem);
        height: clamp(6rem, 25vw, 8rem);
        min-width: clamp(6rem, 25vw, 8rem);
    }}
    .nx9-header-title {{
        font-size: 1.5rem;
    }}
}}
</style>
"""


def inject_theme() -> None:
    """Render the NX9 stylesheet. Call once, before any page content."""
    import streamlit as st

    st.markdown(NX9_CSS, unsafe_allow_html=True)
    st.markdown(SQUARE_ART_CSS, unsafe_allow_html=True)