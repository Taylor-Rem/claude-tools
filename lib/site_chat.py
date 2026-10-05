"""The site chat's script tag (ROADMAP B108, plan 45 § Contract 1), one place for it.

Every page of a client site carries, on its own line beside the footer badge:

    <script src="https://patchlamp.com/site-chat.js" data-site="SLUG" defer></script>

SLUG is the workspace's slug (`.client.json`), which is the project patchlamp.com
keys the bubble by. The tag costs nothing when the chat is off: the script asks
patchlamp.com for the site's state and renders nothing when the owner has turned
it off, the project is unknown, or the app's global switch is off. So the tag
stays on the pages either way, and the switch lives on patchlamp.com, not here.

The templates carry `data-site="{{SLUG}}"`, filled by `site new` like {{NAME}}.
A claimed preview (`leads preview --claim`) gets it from `ensure()`, because the
preview is rendered before anyone knows the client's slug and a preview itself
carries no bubble (plan 45, Open 5).
"""

import re

SRC = "https://patchlamp.com/site-chat.js"


def tag(slug):
    return f'<script src="{SRC}" data-site="{slug}" defer></script>'


# the whole line the tag sits on, whatever slug it names
LINE = re.compile(r'(?m)^[ \t]*<script\b[^>]*\bsrc="' + re.escape(SRC) + r'"[^>]*>\s*</script>[ \t]*\r?\n?')
_SLUG = re.compile(r'<script\b[^>]*\bsrc="' + re.escape(SRC) + r'"[^>]*\bdata-site="([^"]*)"')
_BADGE = re.compile(r'(?m)^([ \t]*)<(p|span|div|li)\b[^>]*class="patchlamp-badge".*?</\2>[ \t]*\r?\n')
_BODY_END = re.compile(r'(?m)^([ \t]*)</body>')


def slugs(html):
    """Every slug the page's site-chat tags name ([] when it has none)."""
    return _SLUG.findall(html or "")


def has(html, slug=None):
    """True when the page carries the tag (naming `slug`, when one is given)."""
    found = slugs(html)
    return bool(found) if slug is None else slug in found


def strip(html):
    """The page without the tag (a preview carries no bubble)."""
    return LINE.sub("", html or "")


def ensure(html, slug):
    """The page with exactly one tag naming `slug`: on the line after the footer badge,
    else on the line before </body>, at that line's indent. A page with neither is
    returned as it was (a fragment, not a page)."""
    if slugs(html) == [slug]:
        return html
    html = strip(html)
    m = _BADGE.search(html)
    if m:
        return html[:m.end()] + f"{m.group(1)}{tag(slug)}\n" + html[m.end():]
    m = _BODY_END.search(html)
    if m:
        return html[:m.start()] + f"{m.group(1) or '  '}{tag(slug)}\n" + html[m.start():]
    return html
