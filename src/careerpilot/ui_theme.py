"""Visual identity for CareerPilot.

The CSS below is a FIXED string. Nothing from a resume, job listing or model is ever interpolated into it.
Direction: a calm workspace. Deep-navy sidebar, warm cream canvas, serif headlines, one orange accent,
small mono pills for status. Cards are white with soft corners.

HTML helpers (brand, page_header, pills, timeline) only receive strings made by the code itself
(fixed labels, formatted dates, integers) and escape everything anyway.
"""
from __future__ import annotations

import html
import re

import streamlit as st

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap');

:root {
  --navy: #16214A;
  --navy-2: #222F5E;
  --navy-3: #2B3A70;
  --cream: #F9F6F0;
  --cream-2: #F3EEE2;
  --paper: #FFFFFF;
  --ink: #111B3C;
  --muted: #5E6678;
  --line: #E7E0D1;
  --orange: #F98A0B;
  --orange-deep: #E07B00;
  --orange-soft: #FDEBD3;
  --green: #0E7A55;
  --green-soft: #D8F1E4;
  --red: #C0262D;
  --red-soft: #FCE0DF;
  --slate-soft: #E4E7EE;
  --serif: 'Newsreader', 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
  --sans: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --mono: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace;
}

html, body, [data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"], button, input, textarea, select {
  font-family: var(--sans);
}
[data-testid="stAppViewContainer"] { background: var(--cream); color: var(--ink); }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { line-height: 1.6; color: var(--ink); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--muted); }

h1, h2, h3, h4 {
  font-family: var(--serif) !important;
  color: var(--ink);
  font-weight: 500 !important;
  letter-spacing: -0.01em;
}
h3 { font-size: 1.35rem !important; }
h4 { font-size: 1.1rem !important; }

#MainMenu, footer, .stAppDeployButton { visibility: hidden; display: none; }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 1020px; padding: 2.8rem 3rem 5rem 3rem; }

/* ------------------------------------------------------------ sidebar */
[data-testid="stSidebar"] { background: var(--navy); border-right: none; }
[data-testid="stSidebar"] [data-testid="stSidebarContent"] { background: var(--navy); }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #9AA5C6; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 1.6rem; }

.brand { display: flex; align-items: center; gap: .85rem; margin: .2rem 0 2.2rem .2rem; }
.brand .logo { width: 2.9rem; height: 2.9rem; border-radius: 14px; background: var(--orange); display: grid; place-items: center; }
.brand .logo svg { width: 1.5rem; height: 1.5rem; }
.brand .word { font-family: var(--sans); font-weight: 700; font-size: 1.35rem; color: #fff; letter-spacing: -0.01em; }

/* nav: a radio turned into a menu */
.st-key-nav, .st-key-nav [data-testid="stRadio"] { width: 100% !important; }
.st-key-nav [data-testid="stRadioGroup"] { gap: .35rem; }
.st-key-nav [data-testid="stRadioGroup"] > div { width: 100%; }
.st-key-nav label[data-testid="stRadioOption"] {
  width: 100%; margin: 0; padding: .78rem 1rem; border-radius: 14px; cursor: pointer; transition: background .12s ease;
}
.st-key-nav label[data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-nav label[data-testid="stRadioOption"] p { color: #C4CBE3; font-weight: 500; font-size: 1.05rem; }
.st-key-nav label[data-testid="stRadioOption"]:hover { background: rgba(255,255,255,.06); }
.st-key-nav label[data-testid="stRadioOption"][data-selected="true"] { background: var(--navy-2); }
.st-key-nav label[data-testid="stRadioOption"][data-selected="true"] p { color: #fff; font-weight: 600; }
.st-key-nav label[data-testid="stRadioOption"]:has(input:focus-visible) { outline: 2px solid var(--orange); outline-offset: 1px; }

.side-foot { border-top: 1px solid rgba(255,255,255,.12); margin: 2.4rem 0 .9rem 0; padding-top: 1rem; }
.side-foot .tag { font-family: var(--mono); font-size: .72rem; letter-spacing: .12em; color: #9AA5C6; text-transform: uppercase; }
[data-testid="stSidebar"] .stButton > button {
  background: transparent; border: 1px solid rgba(255,255,255,.22); color: #E6EAF7; border-radius: 12px; font-weight: 500;
}
[data-testid="stSidebar"] .stButton > button:hover { background: rgba(255,255,255,.08); border-color: rgba(255,255,255,.4); color: #fff; }

/* ------------------------------------------------------- page header */
.eyebrow { font-family: var(--mono); font-size: .78rem; letter-spacing: .22em; text-transform: uppercase; color: var(--orange); margin: 0 0 .7rem 0; }
.page-title { font-family: var(--serif); font-weight: 500; font-size: 3rem; line-height: 1.08; letter-spacing: -0.02em; color: var(--ink); margin: 0; }
.page-sub { color: var(--muted); font-size: 1.1rem; margin: .7rem 0 1.6rem 0; line-height: 1.5; }

/* ----------------------------------------------------------- buttons */
.stButton > button, .stDownloadButton > button, .stLinkButton > a {
  border-radius: 12px; font-weight: 600; border: 1px solid var(--line); background: var(--paper); color: var(--ink);
  padding: .55rem 1.1rem; transition: background .12s ease, border-color .12s ease, color .12s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover { background: var(--cream-2); border-color: #D9D0BB; color: var(--ink); }
.stButton > button[kind="primary"] { background: var(--navy); border-color: var(--navy); color: #fff; padding: .7rem 1.4rem; font-size: 1.02rem; }
.stButton > button[kind="primary"]:hover { background: var(--navy-3); border-color: var(--navy-3); color: #fff; }
.stButton > button p, .stDownloadButton > button p, .stLinkButton > a p { color: inherit !important; font-weight: inherit; }
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible { outline: 3px solid #FAC98A; outline-offset: 2px; }
.stButton > button:disabled { opacity: .45; }

/* ------------------------------------------------------------ inputs */
[data-testid="stWidgetLabel"] p { font-weight: 600; font-size: 1.02rem; color: var(--ink); }
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"], [data-testid="stSelectbox"] > div:last-child > div,
[data-testid="stDateInput"] > div:last-child > div, [data-testid="stMultiSelect"] > div:last-child > div {
  background: var(--cream) !important; border: 1px solid #E3DCCB !important; border-radius: 12px !important;
}
[data-testid="stTextInputRootElement"] input, [data-testid="stTextAreaRootElement"] textarea { background: transparent !important; color: var(--ink); }
[data-testid="stTextInputRootElement"] input::placeholder, [data-testid="stTextAreaRootElement"] textarea::placeholder { color: #7B8294; }
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stSelectbox"] > div:last-child > div:focus-within {
  border-color: var(--orange) !important; box-shadow: 0 0 0 3px rgba(249,138,11,.18) !important;
}
[data-testid="stFileUploaderDropzone"] { background: var(--cream); border: 1px dashed #D5CBB4; border-radius: 12px; }
[data-testid="stFileUploaderDropzone"] button { border-radius: 10px; }
[data-testid="stChatInput"] { border-radius: 14px; }

/* -------------------------------------------------- cards and metrics */
[class*="st-key-box-"], [class*="st-key-card"], [class*="st-key-pass"] {
  border: 1px solid var(--line) !important; border-radius: 20px !important; background: var(--paper);
  box-shadow: 0 1px 2px rgba(17,27,60,.04); padding: 1.3rem 1.4rem 1rem 1.4rem;
}
[class*="st-key-box-"] [class*="st-key-box-"] { box-shadow: none; border-radius: 14px !important; background: var(--cream); }
.card-title { font-family: var(--sans); font-weight: 700; font-size: 1.25rem; color: var(--ink); margin: .2rem 0 .15rem 0; }
.card-desc { color: var(--muted); font-size: 1.02rem; line-height: 1.5; margin: 0 0 1.1rem 0; }

[data-testid="stMetricValue"], [data-testid="stMetricValue"] * { font-family: var(--serif) !important; font-weight: 500; font-size: 2.6rem; letter-spacing: -0.02em; }
[data-testid="stMetricLabel"] p { color: var(--muted); font-weight: 500; font-size: .95rem; }
[data-testid="stProgress"] > div > div { background-color: #EFE8D8; height: .5rem; border-radius: 99px; }
[data-testid="stProgress"] > div > div > div { background-color: var(--orange); border-radius: 99px; }

/* the switch row ("Include remote roles") */
.st-key-remote-card { background: var(--cream); border: 1px solid var(--line); border-radius: 16px; padding: 1rem 1.2rem; margin: .4rem 0 1rem 0; }
.st-key-remote-card [data-testid="stVerticalBlockBorderWrapper"] { border: none !important; box-shadow: none; }
.st-key-remote-card .row-title { font-weight: 600; font-size: 1.05rem; margin: 0; }
.st-key-remote-card .row-desc { color: var(--muted); font-size: .95rem; margin: .2rem 0 .1rem 0; }

/* -------------------------------------------------------------- pills */
.pill { display: inline-flex; align-items: baseline; gap: .55rem; font-family: var(--mono); font-size: .76rem; letter-spacing: .1em;
  text-transform: uppercase; padding: .5rem .95rem; border-radius: 999px; border: 1px solid var(--line); background: var(--cream-2); color: #3E475C; }
.pill b { font-size: 1.05rem; font-weight: 600; letter-spacing: 0; }
.pill.slate { background: var(--slate-soft); border-color: #CBD2E0; color: var(--ink); }
.pill.orange { background: var(--orange-soft); border-color: #F6CE9B; color: var(--orange-deep); }
.pill.green { background: var(--green-soft); border-color: #A9DBC2; color: var(--green); }
.pill.red { background: var(--red-soft); border-color: #F2B8B5; color: var(--red); }
.pill.off { background: transparent; border-style: dashed; color: #8A90A0; }
.pill-row { display: flex; flex-wrap: wrap; gap: .6rem; margin: .2rem 0 1.5rem 0; }
.pill-row.tight { gap: .45rem; margin: .4rem 0 .2rem 0; }
.pill-row.tight .pill { padding: .38rem .8rem; font-size: .72rem; }

/* st.badge (skills): same mono feel */
[data-testid="stBadge"], .stBadge, span[class*="Badge"] { font-family: var(--mono); letter-spacing: .04em; }

/* -------------------------------------------------- workspace sub-nav */
.st-key-ws [data-testid="stRadioGroup"] { gap: .35rem; background: var(--cream-2); border: 1px solid var(--line); border-radius: 14px; padding: .3rem; width: fit-content; }
.st-key-ws label[data-testid="stRadioOption"] { margin: 0; padding: .45rem 1.15rem; border-radius: 10px; cursor: pointer; }
.st-key-ws label[data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-ws label[data-testid="stRadioOption"] p { color: var(--muted); font-weight: 600; }
.st-key-ws label[data-testid="stRadioOption"][data-selected="true"] { background: var(--paper); box-shadow: 0 1px 2px rgba(17,27,60,.1); }
.st-key-ws label[data-testid="stRadioOption"][data-selected="true"] p { color: var(--ink); }

/* ------------------------------------------------------ job cards */
.st-key-pass-high-0, [class*="st-key-pass-high"] { border-left: 5px solid var(--green) !important; }
[class*="st-key-pass-mid"] { border-left: 5px solid var(--orange) !important; }
[class*="st-key-pass-low"] { border-left: 5px solid #A7ADBB !important; }
[class*="st-key-pass"] hr { border: 0; border-top: 1px dashed var(--line); margin: .6rem 0; }

/* dates as a route */
.route { display: flex; align-items: flex-start; margin: .6rem 0 1.6rem 0; }
.route .stop { flex: 1; position: relative; text-align: left; padding-top: 1.6rem; }
.route .stop::before { content: ''; position: absolute; top: .55rem; left: 0; right: 0; border-top: 2px solid var(--line); }
.route .stop::after { content: ''; position: absolute; top: .2rem; left: 0; width: .8rem; height: .8rem; border-radius: 50%; background: var(--paper); border: 3px solid var(--orange); }
.route .stop:last-child::before { right: 70%; }
.route .n { font-family: var(--serif); font-weight: 500; font-size: 2rem; line-height: 1; }
.route .l { color: var(--muted); font-size: .9rem; margin-top: .15rem; }

[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border-radius: 14px; overflow: hidden; border: 1px solid var(--line); }
[data-testid="stExpander"] details { border: 1px solid var(--line); border-radius: 14px; background: var(--paper); }
[data-testid="stAlert"] { border-radius: 14px; }

@media (max-width: 720px) {
  .block-container { padding: 1.6rem 1.1rem 4rem 1.1rem; }
  .page-title { font-size: 2.2rem; }
  .route { flex-direction: column; }
  .route .stop { padding-bottom: .8rem; }
  .route .stop::before { display: none; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
"""

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~$<&])")

TONES = {"neutral", "slate", "orange", "green", "red", "off"}

_LOGO = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="#16214A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4V8z"/>'
    '<path d="M9 9.5h6M9 14.5h6" /></svg>'
)


_card_n = 0


def card():
    """A white rounded card. Keyed so the stylesheet can find it."""
    global _card_n
    _card_n += 1
    return st.container(border=True, key=f"box-{_card_n}")


def apply() -> None:
    """Inject the fixed stylesheet once per run."""
    global _card_n
    _card_n = 0
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def plain(text: str) -> str:
    """Make untrusted text render as plain text (no markdown, links, images or HTML)."""
    return _MD_SPECIAL.sub(r"\\\1", str(text or "")).replace("\n", "  \n")


def brand() -> None:
    st.markdown(f'<div class="brand"><div class="logo">{_LOGO}</div><div class="word">CareerPilot</div></div>',
                unsafe_allow_html=True)


def side_foot(tag: str) -> None:
    st.markdown(f'<div class="side-foot"><div class="tag">{html.escape(tag)}</div></div>', unsafe_allow_html=True)


def page_header(eyebrow: str, title: str, subtitle: str = "") -> None:
    sub = f'<p class="page-sub">{html.escape(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<p class="eyebrow">{html.escape(eyebrow)}</p><h1 class="page-title">{html.escape(title)}</h1>{sub}',
        unsafe_allow_html=True,
    )


def card_head(title: str, desc: str = "") -> None:
    d = f'<p class="card-desc">{html.escape(desc)}</p>' if desc else ""
    st.markdown(f'<div class="card-title">{html.escape(title)}</div>{d}', unsafe_allow_html=True)


def pills(items: list[tuple[str, int | None, str]], tight: bool = False) -> None:
    """Status pills. items = (fixed label, optional integer, tone). Labels are escaped, counts forced to int."""
    out = []
    for label, count, tone in items:
        tone = tone if tone in TONES else "neutral"
        num = f"<b>{int(count)}</b>" if count is not None else ""
        cls = "" if tone == "neutral" else f" {tone}"
        out.append(f'<span class="pill{cls}">{html.escape(label)}{num}</span>')
    if out:
        st.markdown(f'<div class="pill-row{" tight" if tight else ""}">' + "".join(out) + "</div>", unsafe_allow_html=True)


def timeline(stops: list[tuple[str, str]], today) -> None:
    """Upcoming reminders as a route: a stop per date. Only code-made strings reach the HTML:
    dates formatted here, kind labels from a fixed map, and day counts as integers (no titles)."""
    from datetime import date as _date

    labels = {"deadline": "Application deadline", "interview": "Interview", "test": "Online test",
              "follow_up": "Follow up", "prep": "Preparation", "other": "Reminder"}
    stops_html = []
    for iso, kind in stops:
        try:
            d = _date.fromisoformat(iso)
        except ValueError:
            continue
        left = (d - today).days
        when = "today" if left == 0 else "tomorrow" if left == 1 else f"in {int(left)} days"
        stops_html.append(
            f'<div class="stop"><div class="n">{html.escape(d.strftime("%d %b"))}</div>'
            f'<div class="l">{html.escape(labels.get(kind, "Reminder"))}, {html.escape(when)}</div></div>'
        )
    if stops_html:
        st.markdown('<div class="route">' + "".join(stops_html) + "</div>", unsafe_allow_html=True)


def round_line(text: str, note: bool = False) -> None:
    """One agent step in the Jobs log. Text is escaped and wrapped by markdown, not injected as HTML."""
    st.markdown(plain(text))
