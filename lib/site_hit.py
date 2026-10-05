"""The page-load count's script tag (ROADMAP B127, ~/projects/plans/50-site-numbers.md § Contract 1).

Every page of a client site carries, on its own line after the site chat's tag:

    <script src="https://patchlamp.com/hit.js" data-site="SLUG" defer></script>

SLUG is the workspace's slug (`.client.json`). The script sends patchlamp.com the
page's path and the referrer once per page load, with no cookie; patchlamp.com keeps
the path, the referring host and the day, nothing about the visitor, and counts it
only when SLUG is a client project and the page is on one of that project's hosts.
`site stats` reads it back. Previews carry no tag (they are nobody's project yet);
a claim adds it.
"""

import re

SRC = "https://patchlamp.com/hit.js"
CHAT_SRC = "https://patchlamp.com/site-chat.js"


def tag(slug):
    return f'<script src="{SRC}" data-site="{slug}" defer></script>'


LINE = re.compile(r'(?m)^[ \t]*<script\b[^>]*\bsrc="' + re.escape(SRC) + r'"[^>]*>\s*</script>[ \t]*\r?\n?')
_SLUG = re.compile(r'<script\b[^>]*\bsrc="' + re.escape(SRC) + r'"[^>]*\bdata-site="([^"]*)"')
_CHAT = re.compile(r'(?m)^([ \t]*)<script\b[^>]*\bsrc="' + re.escape(CHAT_SRC) + r'"[^>]*>\s*</script>[ \t]*\r?\n')
_BADGE = re.compile(r'(?m)^([ \t]*)<(p|span|div|li)\b[^>]*class="patchlamp-badge".*?</\2>[ \t]*\r?\n')
_BODY_END = re.compile(r'(?m)^([ \t]*)</body>')


def slugs(html):
    """Every slug the page's count tags name ([] when it has none)."""
    return _SLUG.findall(html or "")


def has(html, slug=None):
    found = slugs(html)
    return bool(found) if slug is None else slug in found


def strip(html):
    """The page without the tag (a preview is nobody's site yet)."""
    return LINE.sub("", html or "")


def ensure(html, slug):
    """The page with exactly one tag naming `slug`: on the line after the site chat's
    tag, else after the footer badge, else before </body>, at that line's indent. A page
    with none of them is returned as it was (a fragment, not a page)."""
    if slugs(html) == [slug]:
        return html
    html = strip(html)
    for rx in (_CHAT, _BADGE):
        m = rx.search(html)
        if m:
            return html[:m.end()] + f"{m.group(1)}{tag(slug)}\n" + html[m.end():]
    m = _BODY_END.search(html)
    if m:
        return html[:m.start()] + f"{m.group(1) or '  '}{tag(slug)}\n" + html[m.start():]
    return html
