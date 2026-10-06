// The small Markdown a signed document is written in (# headings, paragraphs,
// - and 1. lists, **bold**, *italic*), as HTML. It is the same function as
// `to_html` / `shown_html` in claude-tools/bin/sign, line for line, so the page
// a customer signs and the PDF made afterwards show the same thing from the
// same stored text (tests/test_sign.py runs both on the same fixtures). The
// HTML is never stored: only the text is, and only the text is hashed, so
// what is shown can't drift from what was signed. Everything is escaped
// first, so the page never runs what a document holds.

const W = "[\\p{L}\\p{N}_]";

export function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}

function inline(s) {
  s = escHtml(s);
  s = s.replace(/\*\*(.+?)\*\*/gu, "<strong>$1</strong>");
  s = s.replace(new RegExp(`(?<![\\p{L}\\p{N}_*])\\*(?!\\s)(.+?)(?<!\\s)\\*(?![\\p{L}\\p{N}_*])`, "gu"), "<em>$1</em>");
  s = s.replace(new RegExp(`(?<!${W})_(?!\\s)(.+?)(?<!\\s)_(?!${W})`, "gu"), "<em>$1</em>");
  return s;
}

export function toHtml(body) {
  const out = [];
  let para = [], items = [], kind = null;
  const flush = () => {
    if (para.length) out.push("<p>" + para.map(inline).join("<br>") + "</p>");
    if (items.length) out.push(`<${kind}>` + items.map((x) => `<li>${inline(x)}</li>`).join("") + `</${kind}>`);
    para = []; items = []; kind = null;
  };
  for (const line of body.split("\n")) {
    const s = line.trim();
    const h = s.match(/^(#{1,3})\s+(.*)$/);
    const ul = s.match(/^[-*+]\s+(.*)$/);
    const ol = s.match(/^\d+[.)]\s+(.*)$/);
    if (!s) flush();
    else if (h) {
      flush();
      const n = h[1].length;
      out.push(`<h${n}>${inline(h[2])}</h${n}>`);
    } else if (ul || ol) {
      const want = ul ? "ul" : "ol";
      if (para.length || (kind && kind !== want)) flush();
      kind = want;
      items.push((ul || ol)[1]);
    } else if (items.length && (line.startsWith(" ") || line.startsWith("\t"))) {
      items[items.length - 1] += " " + s;
    } else {
      if (items.length) flush();
      para.push(s);
    }
  }
  flush();
  return out.join("\n");
}

// The text less a first "# " line that only repeats the title (the page and the PDF show it as their heading).
export function shownHtml(body, title) {
  let lines = body.split("\n");
  if (lines.length && /^#\s+/.test(lines[0]) && lines[0].replace(/^#+/, "").trim() === title) lines = lines.slice(1);
  return toHtml(lines.join("\n"));
}
