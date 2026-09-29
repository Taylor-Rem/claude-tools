# ==== B67: the run ==================================================================================
#
# run.json for a prep run (kind "prep"), beside B65's fields:
#   state      picked → running → batch → finishing → done | rehearsed | stopped | publish_failed | failed
#   n, opts {segment, allow_calls, no_publish, reuse}, order [slugs, pick order], pid, deadline
#   businesses[slug]: place_id, name, category, segment, city, role active|reserve, stage (the next thing
#     to do: research → build → check → judge ⇄ fix → ready | dropped), why (a drop's reason), rounds,
#     attempts {stage: failures}, look, template, preview_slug, build_session, fixes, stages {…}
#   usage {stage: sessions, tokens, plan_usd_list, permission_denials, models, refusals}
# A business's stage only moves on when the one before it is written, so a killed conductor re-runs at
# most the stage it was in (`prep resume`).

N_DEFAULT = int(os.environ.get("PREP_N", 10))
N_MAX = 12
RESERVE = int(os.environ.get("PREP_RESERVE", 4))
HOURS = float(os.environ.get("PREP_HOURS", 4))
IMAGE_USD = float(os.environ.get("PREP_IMAGE_USD", 0))          # 0: stock only (the builder can't run img gen)
RATE_WAIT = float(os.environ.get("PREP_RATE_WAIT", 600))
RATE_TRIES = int(os.environ.get("PREP_RATE_TRIES", 6))
FINISH_RESERVE_S = float(os.environ.get("PREP_FINISH_RESERVE_MINUTES", 30)) * 60
REQUESTS = Path(os.environ.get("PREP_REQUESTS", PROJECTS / "requests"))
PREP_TEMPLATES = TOOLBELT / "templates" / "prep"
FRAME = Path(os.environ.get("PREP_FRAME", PREP_TEMPLATES / "message.md"))
SHOT_BIN = os.environ.get("PREP_SHOT") or str(BIN / "shot")
NOTIFY_BIN = os.environ.get("PREP_NOTIFY") or str(BIN / "notify")
OUTREACH_STATE = Path(os.environ.get("OUTREACH_STATE", Path.home() / ".local/state/claude-tools/outreach"))
PICK_SEGMENTS = ("services", "creatives")        # the segments whose templates have their looks (B64)
FIT_REVIEWS = (10, 300)
FIT_RATING = 4.3
PER_CATEGORY = 3
ROUNDS = 2                                        # fix rounds before a site is dropped
GENERIC_SENTENCES = 3
SPECIFIC_MAX = 140
MESSAGE_MAX = 700
PAGE_BYTES = 1_500_000
LISTING_FACTS = ("listing:phone", "listing:rating", "listing:hours", "listing:city", "listing:category",
                 "listing:maps")
GUARDED = re.compile(r"(?:\b(?:licen[cs]ed|insured|bonded|certified|guarantee[ds]?|guaranty|warrant(?:y|ies)|"
                     r"awards?|award-winning|best|number one|years|yrs|since|family[- ]owned|free estimates?)\b|#1)",
                     re.I)
TERMINAL = ("ready", "dropped")
LIVE_STATES = ("picked", "running", "batch", "finishing")
_IMG_LOCK = threading.Lock()
_STOP = threading.Event()


def approved_file():
    return STATE / "approved.json"


def sha_of(path):
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def frame_approved():
    row = read_json(approved_file(), {}) or {}
    cur = sha_of(FRAME)
    return bool(cur) and row.get("message.md") == cur


def frame_sections():
    """{'message': text, 'call': text} from templates/prep/message.md (its comment is not the frame)."""
    raw = re.sub(r"<!--.*?-->", "", FRAME.read_text(), flags=re.S)
    out, cur = {}, None
    for line in raw.splitlines():
        m = re.match(r"^##\s+(\w+)\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: " ".join(x.strip() for x in v if x.strip()) for k, v in out.items()}


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True


def marker_path(run_id):
    return REQUESTS / f"prep-{run_id}.running"


def marker_pid(path):
    try:
        return int(Path(path).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def live_markers(clear_dead=True):
    """[(run_id, pid)] for prep markers whose process is alive; a dead one is cleared (plan § B67.7)."""
    out = []
    for p in sorted(REQUESTS.glob("prep-*.running")) if REQUESTS.exists() else []:
        pid = marker_pid(p)
        if pid and pid_alive(pid):
            out.append((p.name[len("prep-"):-len(".running")], pid))
        elif clear_dead:
            p.unlink(missing_ok=True)
    return out


def set_run(run_dir, **fields):
    with _RUN_LOCK:
        run = read_json(run_dir / "run.json", {})
        run.update(fields)
        write_json(run_dir / "run.json", run)
        return run


def set_biz(run_dir, slug, **fields):
    with _RUN_LOCK:
        run = read_json(run_dir / "run.json", {})
        b = run.setdefault("businesses", {}).setdefault(slug, {})
        b.update(fields)
        write_json(run_dir / "run.json", run)
        return b


def get_run(run_dir):
    with _RUN_LOCK:
        return read_json(Path(run_dir) / "run.json", {}) or {}


def log_line(run_dir, text):
    stamp_ = now().strftime("%H:%M:%S")
    try:
        with open(Path(run_dir) / "conductor.log", "a") as f:
            f.write(f"{stamp_} {text}\n")
    except OSError:
        pass


# ---- the pick ------------------------------------------------------------------------------------

def template_for(category):
    """The site template a category renders with, or None when that template has no looks yet."""
    L = leads()
    t = L.preview_copy(category)["template"]
    return t if L.has_library(t) else None


def suppressed_values():
    vals = set()
    p = OUTREACH_STATE / "suppress.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                v = str(json.loads(line).get("value") or "").strip().lower()
            except json.JSONDecodeError:
                continue
            if v:
                vals.add(v)
    return vals


def in_flight_places(exclude_run=None):
    """Place ids in another prep run that is still going (or stopped in the last three days)."""
    out = set()
    if not STATE.exists():
        return out
    cutoff = (today() - dt.timedelta(days=3)).isoformat()
    for d in STATE.iterdir():
        if d.name == exclude_run:
            continue
        rj = read_json(d / "run.json")
        if not rj or rj.get("kind") != "prep":
            continue
        st = rj.get("state")
        if st in LIVE_STATES or st == "publish_failed" or (st == "stopped" and (rj.get("created") or "") >= cutoff):
            out |= {b.get("place_id") for b in (rj.get("businesses") or {}).values()
                    if b.get("stage") != "dropped" and b.get("place_id")}
    return out


def reach_evidence_url(evidence):
    m = re.search(r"https?://[^\s\"'\\]+", json.dumps(evidence) if evidence else "")
    return m.group(0) if m else None


def pick_row(c, L):
    rc = L.business_reach(dict(c))
    link = c.get("presence_link") or c.get("website") or ""
    own_link = bool(re.match(r"^(?:https?://)?(?:www\.|m\.|web\.)?(?:instagram|facebook)\.com/", link))
    reach_row = (L.reach_table() or {}).get(c["place_id"]) or {}
    evidence = own_link or bool(reach_row.get("evidence"))
    fit = FIT_REVIEWS[0] <= int(c.get("reviews") or 0) <= FIT_REVIEWS[1] and float(c.get("rating") or 0) >= FIT_RATING
    city = c.get("locality") or (c.get("city") or "").split(",")[0].strip()
    has = [k for k in ("instagram", "facebook", "email") if rc.get(k)]
    why = [f"{c.get('rating')}★ ({c.get('reviews')})" + (" fits" if fit else ""),
           ("reach: " + ", ".join(has) + (" with evidence" if evidence else "")) if has else "phone only",
           f"{c.get('miles', '?')} mi"]
    return {"place_id": c["place_id"], "name": c["name"], "category": c.get("category"), "segment": c.get("segment"),
            "city": city, "rating": c.get("rating"), "reviews": c.get("reviews"), "miles": c.get("miles"),
            "fit": fit, "evidence": evidence, "reach": {k: rc.get(k) for k in ("instagram", "facebook", "email")},
            "has_reach": bool(has), "template": template_for(c.get("category")), "why": " · ".join(why)}


def pick(n, segment=None, allow_calls=False, reserve=None, exclude_run=None):
    """(picks, skipped counts): n + the reserve from the pool, by fit (plan § B67.1). Spends nothing."""
    L = leads()
    reserve = RESERVE if reserve is None else reserve
    segs = PICK_SEGMENTS if segment in (None, "", "all") else (segment,)
    for s in segs:
        if s not in L.BUSINESS_SEGMENTS:
            die(f"--segment {s}: one of {', '.join(PICK_SEGMENTS)} (the templates with looks), or all")
    pool = L.business_candidates(list(segs))
    held = set(L.contacted())
    try:
        pipeline = {l.get("place_id") for l in L.pipeline_state().values() if l.get("place_id")}
    except (OSError, SystemExit):
        pipeline = set()
    claimed, supp, flying = L.claimed_places(), suppressed_values(), in_flight_places(exclude_run)
    skipped, rows = {}, []

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1
    for c in pool:
        pid = c["place_id"]
        if pid in held:
            skip("held (messaged or kitted in the last 56 days)")
        elif pid in pipeline:
            skip("already in the pipeline")
        elif pid in claimed:
            skip("claimed their preview")
        elif pid.lower() in supp:
            skip("suppressed")
        elif pid in flying:
            skip("in another prep run")
        elif not template_for(c.get("category")):
            skip("its template has no looks yet")
        else:
            r = pick_row(c, L)
            if r["reach"].get("email") and r["reach"]["email"].lower() in supp:
                skip("suppressed")
            elif not r["has_reach"] and not allow_calls:
                skip("no reach (Instagram, Facebook or email)")
            else:
                rows.append(r)
    rows.sort(key=lambda r: (not r["fit"], not r["evidence"], r["miles"] if r["miles"] is not None else 999))
    out, per_cat = [], {}
    for r in rows:
        k = (r["category"] or "").lower()
        if per_cat.get(k, 0) >= PER_CATEGORY:
            skip(f"more than {PER_CATEGORY} of a category")
            continue
        per_cat[k] = per_cat.get(k, 0) + 1
        out.append(r)
        if len(out) >= n + reserve:
            break
    for i, r in enumerate(out):
        r["role"] = "active" if i < n else "reserve"
    return out, skipped


def picks_for_places(place_ids, n):
    """Named place ids (the rehearsal, a hand-picked night): no filter but the census, in the order given."""
    L = leads()
    out = []
    for pid in place_ids:
        c = census_row(pid)
        if not c:
            die(f"{pid}: not in the services census")
        c = dict(c)
        c["miles"] = round(L.miles(L.home(), (c["lat"], c["lng"])), 1) if c.get("lat") else None
        c["presence"], c["presence_label"], c["presence_link"] = L.presence(c)
        r = pick_row(c, L)
        if not r["template"]:
            die(f"{pid} ({c.get('category')}): its template has no looks yet")
        out.append(r)
    for i, r in enumerate(out):
        r["role"] = "active" if i < n else "reserve"
    return out


def dir_slug(name, city, taken):
    L = leads()
    base = slugify(L.plain_name(name))
    slug = base if base not in taken else slugify(f"{base}-{city}")
    k = 2
    while slug in taken:
        slug = f"{base}-{k}"
        k += 1
    return slug


def cmd_pick(args):
    n = max(1, min(args.n or N_DEFAULT, N_MAX))
    picks, skipped = pick(n, args.segment, args.allow_calls)
    if args.json:
        print(json.dumps({"picks": picks, "skipped": skipped}, indent=1))
        return 0
    for i, p in enumerate(picks, 1):
        tag = "" if p["role"] == "active" else "  (reserve)"
        print(f"{i:2}. {p['name']} · {p['category']} · {p['city']} — {p['why']}{tag}")
    if skipped:
        print("left out: " + "; ".join(f"{v} {k}" for k, v in sorted(skipped.items(), key=lambda x: -x[1])))
    if len(picks) < n:
        print(f"only {len(picks)} fit the rules (asked for {n} and a reserve of {RESERVE})")
    return 0


# ---- the draft content.json (code writes it from the high facts; the builder makes it read well) ------

def business_files(wd):
    wd = Path(wd)
    return (read_json(wd / "facts.json", {}) or {}, read_json(wd / "listing.json", {}) or {},
            read_json(wd / "packet.json", {}) or {}, read_json(wd / "content.json"))


def high_facts(facts):
    return {f["id"]: f for f in facts.get("facts") or [] if isinstance(f, dict) and f.get("confidence") == "high"
            and f.get("id")}


def guard_ok(text, ids, high):
    """A guarded word only in a text whose facts include a high credential or since fact (gate 4)."""
    return not GUARDED.search(text or "") or any(high.get(i, {}).get("kind") in ("credential", "since") for i in ids)


def prepare_images(wd, preview_slug, category):
    """The hero and four more from `img stock` through leads' picker (skips every id another preview
    shows, keeps what a rebuild had). Stock only: PREP_IMAGE_USD is 0. Returns content.json image rows."""
    L = leads()
    copy = L.preview_copy(category)
    with _IMG_LOCK:
        rows = L.preview_images(preview_slug, copy, "stock", Path(wd) / "images", gallery=4)
    out = {}
    for k, im in rows.items():
        im = dict(im)
        try:
            im["file"] = str(Path(im["file"]).resolve().relative_to(Path(wd).resolve()))
        except ValueError:
            pass
        out[k] = im
    return out


def draft_content(wd, template, look, preview_slug, images):
    """content.json from the high facts only, every text traced, the images code chose, the look the run
    assigned. The builder starts from this and makes it read like the business's own site."""
    L = leads()
    facts, listing, pkt, _ = business_files(wd)
    high = high_facts(facts)
    name = L.plain_name(facts.get("name") or pkt.get("name") or "")
    city = facts.get("city") or pkt.get("city") or ""
    category = facts.get("category") or pkt.get("category") or ""
    label = category[:1].upper() + category[1:]
    generic = []

    def T(text, ids=()):
        ids = [i for i in ids if i]
        if not ids:
            generic.append(text)
        return {"text": text, "facts": list(dict.fromkeys(ids))}

    def backed(item):
        ids = (item or {}).get("facts") or []
        return bool(ids) and all(i in high for i in ids) and guard_ok(item.get("text") or item.get("name"), ids, high)
    li = pkt.get("listing") or {}
    phone = listing.get("nationalPhoneNumber") or li.get("phone") or ""
    maps = L.clean_maps(listing.get("googleMapsUri") or li.get("maps_url") or "")
    cta = dict(T(f"Call {phone}", ["listing:phone"]), href=f"tel:{L.phone_href(phone)}") if phone else \
        dict(T("See the listing", ["listing:maps"]), href=maps or "#details")
    services = [s for s in facts.get("services") or [] if isinstance(s, dict) and backed(s)]
    items = []
    for s in services[:5]:
        f0 = high[s["facts"][0]]
        if not guard_ok(f0.get("text"), [f0["id"]], high):
            continue
        items.append({"title": T(s["name"], s["facts"]), "text": T(f0["text"], [f0["id"]])})
    hero = {"type": "hero", "kicker": T(f"{label} · {city}" if city else label, ["listing:category", "listing:city"])}
    if items:
        hero["heading"] = T(f"{items[0]['title']['text']} in {city}" if city else items[0]["title"]["text"],
                            items[0]["title"]["facts"] + (["listing:city"] if city else []))
    else:
        hero["heading"] = T(f"{label} in {city}" if city else label, ["listing:category", "listing:city"])
    if len(items) > 1:
        hero["sub"] = T(" · ".join(it["title"]["text"] for it in items[:3]),
                        [x for it in items[:3] for x in it["title"]["facts"]])
    hero["secondary"] = T("Ask for a quote" if template == "service" else "Get in touch")
    if "hero" in images:
        hero["image"] = "hero"
    proof = []
    rating, count = listing.get("rating", li.get("rating")), listing.get("userRatingCount", li.get("review_count"))
    if rating is not None and count:
        proof.append(dict(T(f"{float(rating):.1f}★ on Google · {count} review{'s' if count != 1 else ''}",
                            ["listing:rating"]), **({"href": maps} if maps else {})))
    area = facts.get("area") if isinstance(facts.get("area"), dict) and backed(facts.get("area")) else None
    say = (facts.get("hours") or {}).get("say") if isinstance(facts.get("hours"), dict) else None
    say = say if isinstance(say, dict) and backed(say) else None
    hours = [T(say["text"], say["facts"])] if say else \
        [T(h, ["listing:hours"]) for h in L.hours_for_people(listing, {"segment": facts.get("segment")})]
    if city:
        proof.append(T(f"Based in {city}", ["listing:city"]))
    if len(hours) == 1:
        proof.append(dict(hours[0]))
    sections = [hero]
    if proof:
        sections.append({"type": "proof", "items": proof})
    if items:
        sections.append({"type": "services", "heading": T("What we do"), "items": items})
    if area:
        sections.append({"type": "area", "heading": T("Where we work"), "text": T(area["text"], area["facts"])})
    paras = [T(a["text"], a["facts"]) for a in facts.get("about") or [] if isinstance(a, dict) and backed(a)]
    about = {"type": "about", "heading": T(f"About {name}"), "paragraphs": paras[:2]} if paras else None
    if about and "g1" in images:
        about["image"] = "g1"
    gal = [k for k in ("g2", "g3", "g4") if k in images] + ([] if about else [k for k in ("g1",) if k in images])
    phone_row = dict(T(phone, ["listing:phone"]), href=f"tel:{L.phone_href(phone)}") if phone else None
    links = [dict(T("See us on Google", ["listing:maps"]), href=maps)] if maps else []
    if template == "service":
        if about:
            sections.append(about)
        if gal:
            sections.append({"type": "gallery", "heading": T("Recent work"), "images": gal})
        q = {"type": "quote", "heading": T("Ask for a quote"),
             "intro": T("Tell us what you need and we'll get back to you.")}
        if phone_row:
            q["phone"] = phone_row
        sections.append(q)
        sections.append({"type": "booking", "claim_only": True, "heading": T("Book a visit"),
                         "intro": T("Pick an open time. We'll confirm by email or phone.")})
    else:
        if gal:
            sections.append({"type": "gallery", "heading": T("Selected work"), "images": gal})
        if about:
            sections.append(about)
        sections.append({"type": "contact", "heading": T("Get in touch"),
                         "intro": T("Call or message to ask about a date."), "links": links})
    det = {"type": "details", "heading": T("Hours and contact"),
           "where": T(area["text"], area["facts"]) if area else T(city or "Utah", ["listing:city"]),
           "hours": hours, "links": links}
    if phone_row:
        det["phone"] = phone_row
    sections.append(det)
    return {"schema": 1, "slug": preview_slug, "template": template, "look": look, "name": name,
            "place_id": facts.get("place_id") or pkt.get("place_id"), "city": city, "category": category,
            "segment": facts.get("segment") or pkt.get("segment"), "cta": cta, "images": images,
            "sections": sections, "generic": sorted(set(generic))}


# ---- the gates (plan § Contracts, "The gates") ----------------------------------------------------

def text_of(html_):
    """What a reader sees: comments (the claim-only blocks too), scripts and styles out, tags out."""
    import html as htmllib
    t = re.sub(r"<!--.*?-->", " ", html_ or "", flags=re.S)
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"</?(a|span|strong|em|b|i)\b[^>]*>", "", t)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def _luminance(hex_):
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def css_vars(*texts):
    out = {}
    for t in texts:
        for m in re.finditer(r":root\s*\{(.*?)\}", t or "", re.S):
            for k, v in re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b", m.group(1)):
                out[k] = v
    return out


CONTRAST_PAIRS = (("--ink", "--bg"), ("--ink-dim", "--bg"), ("--ink", "--bg-raised"), ("--accent-ink", "--accent"))


def gate_contrast(site):
    """AA (4.5:1) for the look's text colours on its grounds. The builder can't write CSS, so the look's
    own tokens are the page's colours: this reads them from the rendered site's stylesheets."""
    look_css = ""
    idx = (site / "index.html").read_text(errors="replace") if (site / "index.html").exists() else ""
    m = re.search(r'href="(css/looks/[\w-]+\.css)"', idx)
    if m and (site / m.group(1)).exists():
        look_css = (site / m.group(1)).read_text()
    v = css_vars((site / "css" / "style.css").read_text() if (site / "css" / "style.css").exists() else "", look_css)
    out = []
    for fg, bg in CONTRAST_PAIRS:
        if fg in v and bg in v:
            r = contrast(v[fg], v[bg])
            if r < 4.5:
                out.append(f"contrast {fg} on {bg} is {r:.2f}:1 (AA wants 4.5)")
    return out


THIRD_PARTY = re.compile(r"<(?:script|link|img|iframe|source|video|audio|embed|object)\b[^>]*?\b(?:src|href|srcset)"
                         r"\s*=\s*[\"']?\s*(?:https?:)?//", re.I)


def page_weight(site, page="index.html"):
    html_ = (site / page).read_text(errors="replace")
    files = {site / page}
    for ref in re.findall(r'(?:src|href)="([^"#?:]+\.(?:css|js|jpg|jpeg|png|webp|avif|gif|svg))"', html_):
        files.add(site / ref)
    for css in [f for f in list(files) if f.suffix == ".css" and f.exists()]:
        for ref in re.findall(r'url\("?([^")]+\.woff2?)"?\)', css.read_text(errors="replace")):
            files.add((css.parent / ref).resolve())
    return sum(f.stat().st_size for f in files if f.exists())


def run_context(wd):
    """(run_dir, run, biz) when the directory is a business in a prep run, else (None, {}, {})."""
    wd = Path(wd).resolve()
    run_dir = wd.parent
    run = read_json(run_dir / "run.json") if (run_dir / "run.json").exists() else None
    if not run:
        return None, {}, {}
    return run_dir, run, (run.get("businesses") or {}).get(wd.name, {})


def shot_check(wd, page):
    try:
        r = subprocess.run([SHOT_BIN, "check", f"site/{page}"], cwd=wd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"shot check {page}: {exc}"]
    if r.returncode == 0:
        return []
    bad = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip().startswith("✗")]
    return [f"shot check {page}: {b}" for b in bad] or [f"shot check {page}: exit {r.returncode} "
                                                         f"{(r.stderr or r.stdout).strip()[-200:]}"]


def fact_problems(ids, high, all_ids, where):
    out = []
    for i in ids or []:
        if i in LISTING_FACTS:
            continue
        if i not in all_ids:
            out.append(f"{where}: fact {i!r} doesn't exist")
        elif i not in high:
            out.append(f"{where}: fact {i} is medium — the site uses high facts only")
    return out


def never_problems(where, text, ctx):
    """Gate 3 over one text: no price, no street address, no person's name, no review's words."""
    out = []
    if not text:
        return out
    for rx in PRICE_RES:
        m = rx.search(text)
        if m:
            out.append(f"{where}: a price (\"{m.group(0)}\")")
            break
    for rx in ADDRESS_RES:
        m = rx.search(text)
        if m:
            out.append(f"{where}: a street address (\"{m.group(0)}\")")
            break
    nt = norm_text(text)
    if ctx["street"] and ctx["street"] in nt:
        out.append(f"{where}: the listing's street address")
    for rx in NAME_PATTERNS:
        m = rx.search(text)
        if m:
            out.append(f"{where}: a person's name (\"{m.group(0)}\")")
            break
    hit = sorted(n for n in ctx["names"] if re.search(r"\b" + re.escape(n.capitalize()) + r"\b", text))
    if hit:
        out.append(f"{where}: a person's name from the reviews ({', '.join(hit)})")
    g = grams(words(text))
    for ri, rg in enumerate(ctx["review_grams"]):
        if g & rg:
            out.append(f"{where}: shares a run of {REVIEW_RUN} words with review {ri}")
            break
    for sw in ctx["source_words"]:
        if has_words(nt, sw):
            out.append(f"{where}: a fact's source words (\"{sw[:50]}\") — never published")
            break
    return out


def never_ctx(facts, listing):
    street = ""
    addr = listing.get("formattedAddress") or ""
    if re.match(r"^\d", addr):
        street = norm_text(addr.split(",")[0])
    src_words = []
    for f in facts.get("facts") or []:
        if not isinstance(f, dict):
            continue
        for s in _sources(f) + list(f.get("unverified") or []):
            if not isinstance(s, dict) or s.get("kind") == "listing":
                continue
            w = norm_text(s.get("words") or "")
            n = len(w.split())
            if (s.get("kind") == "review" and n >= 3) or n >= 6:
                src_words.append(w)
    return {"street": street, "names": likely_names(listing, facts.get("name") or "", facts.get("city") or ""),
            "review_grams": [grams(words(t)) for t in review_texts(listing)], "source_words": src_words}


def run_gates(wd, shoot=True, render=True):
    """`prep check`: the seven gates and the message's lint over one business directory. Renders
    content.json into site/ first (the site is always exactly its content.json). Writes check.json."""
    L = leads()
    wd = Path(wd).resolve()
    facts, listing, pkt, content = business_files(wd)
    run_dir, run, biz = run_context(wd)
    gates = {str(k): [] for k in range(1, 8)}
    gates["message"] = []
    high = high_facts(facts)
    all_ids = {f.get("id") for f in facts.get("facts") or [] if isinstance(f, dict)}
    site = wd / "site"
    if not isinstance(content, dict):
        for k in gates:
            gates[k].append("content.json is missing or not JSON")
        return _write_check(wd, gates)
    # gate 5: the contract, the facts, the generic cap (first: nothing renders without it)
    errs = L.validate_content(content, wd)
    gates["5"] += errs
    for where, v in L.content_texts(content):
        if isinstance(v, dict):
            gates["5"] += fact_problems(v.get("facts"), high, all_ids, where)
    generic = set(content.get("generic") or [])
    sentences = []
    for where, v in L.content_texts(content):
        m = re.match(r"sections\[(\d+)\]", where)
        sec = content["sections"][int(m.group(1))] if m else {}
        if sec.get("claim_only") or not isinstance(v, dict) or v.get("facts"):
            continue
        t = (v.get("text") or "").strip()
        if t in generic and (re.search(r"[.!?]$", t) or len(t.split()) >= 7):
            sentences.append(t)
    if len(set(sentences)) > GENERIC_SENTENCES:
        gates["5"].append(f"{len(set(sentences))} generic sentences (at most {GENERIC_SENTENCES}): "
                          + " | ".join(sorted(set(sentences)))[:300])
    types = [s.get("type") for s in content.get("sections") or [] if isinstance(s, dict)]
    if content.get("template") == "service" and not {"quote", "booking"} <= set(types):
        gates["5"].append("a service site keeps its quote and booking sections (booking may be claim_only): "
                          "the claim refuses a home page with fewer forms")
    if biz.get("look") and content.get("look") != biz["look"]:
        gates["5"].append(f"look {content.get('look')!r}: the run set {biz['look']!r} for this site (it balances "
                          f"the looks over the night)")
    if biz.get("preview_slug") and content.get("slug") != biz["preview_slug"]:
        gates["5"].append(f"slug {content.get('slug')!r}: keep {biz['preview_slug']!r}")
    # gate 1: renders, shot check clean at 390 and 1280
    rendered = False
    if errs:
        gates["1"].append("not rendered: content.json breaks the contract (gate 5)")
    elif render:
        try:
            L.render_content(content, wd, site, today=L.now_date())
            rendered = True
        except SystemExit as exc:
            gates["1"].append(f"render failed ({exc})")
    else:
        rendered = (site / "index.html").exists()
    pages = {}
    if rendered:
        for page in ("index.html", "photos.html"):
            if (site / page).exists():
                pages[page] = (site / page).read_text(errors="replace")
        if "index.html" not in pages:
            gates["1"].append("no site/index.html")
        if shoot:
            for page in pages:
                gates["1"] += shot_check(wd, page)
    # gate 2: the preview's rules
    name = content.get("name") or ""
    footer = L.PREVIEW_FOOTER.format(name=name)
    for page, h in pages.items():
        if not re.search(r'<meta name="robots" content="noindex', h):
            gates["2"].append(f"{page}: no robots noindex meta")
        if 'class="demo-bar"' not in h:
            gates["2"].append(f"{page}: no preview bar")
        if footer not in text_of(h):
            gates["2"].append(f"{page}: not the footer sentence, word for word")
        if "This preview comes down on" not in h:
            gates["2"].append(f"{page}: no expiry line")
        if 'href="claim/"' not in h:
            gates["2"].append(f"{page}: no claim link")
    if rendered:
        claim = site / "claim" / "index.html"
        ch = claim.read_text(errors="replace") if claim.exists() else ""
        if "noindex" not in ch or f"preview={content.get('slug')}" not in ch:
            gates["2"].append("claim/index.html: not a noindex redirect naming this preview")
    ov = L.PREVIEW_OVERLAY
    if "noindex" not in (ov / "_headers").read_text(errors="replace"):
        gates["2"].append("templates/sites/_preview/_headers does not say noindex (the project root's)")
    if "Disallow: /" not in (ov / "robots.txt").read_text(errors="replace"):
        gates["2"].append("templates/sites/_preview/robots.txt does not disallow everything")
    # the message (composed here so gate 3 and 4 read it too)
    msg = compose_message(wd, preview_url=L.preview_url(content.get("slug") or "x"))
    gates["message"] += msg["problems"]
    # gate 3: never a price, an address, a name, a review's words — on the pages, in content.json, in the message
    ctx = never_ctx(facts, listing)
    for page, h in pages.items():
        gates["3"] += never_problems(page, text_of(h), ctx)
    for where, v in L.content_texts(content):
        gates["3"] += never_problems(f"content {where}", (v or {}).get("text") if isinstance(v, dict) else str(v or ""), ctx)
    gates["3"] += never_problems("message", msg.get("text") or "", ctx)
    gates["3"] = list(dict.fromkeys(gates["3"]))
    # gate 4: guarded words only behind a high credential or since fact
    for where, v in L.content_texts(content):
        if isinstance(v, dict) and not guard_ok(v.get("text"), v.get("facts") or [], high):
            gates["4"].append(f"{where}: \"{GUARDED.search(v['text']).group(0)}\" needs a high credential or since fact")
    spec = (msg.get("specific") or {})
    if spec.get("text") and GUARDED.search(spec["text"]):
        gates["4"].append(f"message.json: \"{GUARDED.search(spec['text']).group(0)}\" — no guarded word in a message")
    # gate 6: every image labelled with alt; the hero on no other site in the run or the last sixty previews
    for page, h in pages.items():
        imgs = re.findall(r"<img\b[^>]*>", re.sub(r"<!--.*?-->", "", h, flags=re.S))
        for tag in imgs:
            if not re.search(r'\balt="[^"]+"', tag):
                gates["6"].append(f"{page}: an image with no alt text ({tag[:60]})")
        labels = len(re.findall(r'class="img-label"', h))
        if labels < len(imgs):
            gates["6"].append(f"{page}: {len(imgs) - labels} image(s) without the stock/AI label")
    hero = ((content.get("images") or {}).get("hero") or {}).get("id")
    if hero:
        others = set()
        if run_dir:
            for s, b in (run.get("businesses") or {}).items():
                if s == wd.name or b.get("stage") == "dropped":
                    continue
                oc = read_json(run_dir / s / "content.json") or {}
                oid = ((oc.get("images") or {}).get("hero") or {}).get("id")
                if oid:
                    others.add(str(oid))
        if str(hero) in others:
            gates["6"].append(f"the hero photo ({hero}) is another site's in this run")
        elif str(hero) in L.image_ids_in_use(content.get("slug"), "hero"):
            gates["6"].append(f"the hero photo ({hero}) is on another of the last {L.IMAGE_REUSE_WINDOW} previews")
    # gate 7: contrast AA, under 1.5 MB, no third-party request
    if rendered and (site / "index.html").exists():
        gates["7"] += gate_contrast(site)
        w = page_weight(site)
        if w > PAGE_BYTES:
            gates["7"].append(f"the home page weighs {w / 1e6:.2f} MB (under 1.5)")
        for page, h in pages.items():
            m = THIRD_PARTY.search(re.sub(r"<!--.*?-->", "", h, flags=re.S))
            if m:
                gates["7"].append(f"{page}: a third-party request ({m.group(0)[:80]})")
        for css in site.rglob("*.css"):
            if re.search(r"url\(\s*[\"']?(?:https?:)?//|@import", css.read_text(errors="replace")):
                gates["7"].append(f"{css.relative_to(site)}: loads from another host")
    return _write_check(wd, gates, msg)


def _write_check(wd, gates, msg=None):
    res = {"schema": 1, "at": now().isoformat(timespec="seconds"),
           "ok": not any(gates.values()),
           "gates": {k: {"ok": not v, "problems": v} for k, v in gates.items()}}
    if msg:
        res["message"] = {k: msg.get(k) for k in ("text", "channel", "section", "chars")}
    write_json(Path(wd) / "check.json", res)
    return res


def check_lines(res):
    out = ["OK — every gate passes" if res["ok"] else "FAIL"]
    names = {"1": "renders, shot check clean", "2": "the preview's rules", "3": "no price, address, name, review words",
             "4": "guarded words", "5": "the contract and the facts", "6": "images", "7": "contrast, weight, no third party",
             "message": "the message"}
    for k, g in res["gates"].items():
        out.append(f"  {'ok ' if g['ok'] else 'BAD'} {k}. {names.get(k, k)}")
        out += [f"      {p}" for p in g["problems"][:12]]
    return out


def cmd_check(args):
    wd = Path(args.dir or ".").resolve()
    if not (wd / "content.json").exists() and (STATE / args.dir if args.dir else wd).exists():
        wd = resolve_business_dir(args.dir) or wd
    res = run_gates(wd, shoot=not args.no_shot)
    print(json.dumps(res, indent=1) if args.json else "\n".join(check_lines(res)))
    return 0 if res["ok"] else 1


def resolve_business_dir(key):
    """A business directory by path, or by slug in the newest run that has it."""
    p = Path(key).expanduser()
    if (p / "facts.json").exists():
        return p.resolve()
    for d in sorted(STATE.iterdir(), reverse=True) if STATE.exists() else []:
        if (d / key / "facts.json").exists():
            return (d / key).resolve()
    return None


# ---- the message (plan § Contracts, "The message" and "The channel") -----------------------------------

def channel_for(pkt):
    """How Taylor reaches them, chosen by code, with the reason: the listing's own link, then the reach
    row's Instagram, its Facebook page, the published email, the phone."""
    L = leads()
    li, rc = pkt.get("listing") or {}, pkt.get("reach") or {}
    web = li.get("website") or (pkt.get("census") or {}).get("website") or ""
    ev = reach_evidence_url(rc.get("evidence"))
    from_reach = "from the reach table" + (f" (evidence {ev})" if ev else "")
    ig_own = L.ig_handle(web) if "instagram.com" in web else None
    fb_own = L.fb_page(web) if "facebook.com" in web else None

    def ig(h, why):
        return {"kind": "instagram", "label": f"Instagram DM to @{h}", "link": f"https://ig.me/m/{h}",
                "profile": f"https://www.instagram.com/{h}/", "why": why}

    def fb(page, why):
        name = page.split("/", 1)[1]
        return {"kind": "facebook", "label": f"Facebook message to {page}", "link": f"https://m.me/{name}",
                "profile": f"https://www.facebook.com/{name}", "why": why}
    if ig_own:
        return ig(ig_own, "their Google listing's website link is their Instagram")
    if fb_own:
        return fb(fb_own, "their Google listing's website link is their Facebook page")
    if rc.get("instagram"):
        return ig(rc["instagram"], "their Instagram, " + from_reach)
    if rc.get("facebook"):
        return fb(rc["facebook"], "their Facebook page, " + from_reach)
    if rc.get("email"):
        return {"kind": "email", "label": f"Email to {rc['email']}", "link": f"mailto:{rc['email']}",
                "profile": None, "why": "the address published for them, " + from_reach}
    phone = li.get("phone") or (pkt.get("census") or {}).get("phone") or ""
    return {"kind": "phone", "label": f"Call {phone}", "link": f"tel:{L.phone_href(phone)}", "profile": None,
            "why": "no Instagram, Facebook or email found: the phone"}


def compose_message(wd, preview_url=None):
    """The frame filled for one business, and its lint. {text, specific, channel, section, problems}."""
    L = leads()
    wd = Path(wd)
    facts, listing, pkt, content = business_files(wd)
    msg = read_json(wd / "message.json", {}) or {}
    spec = msg.get("specific") if isinstance(msg.get("specific"), dict) else None
    problems = []
    try:
        frames = frame_sections()
    except OSError as exc:
        return {"text": "", "problems": [f"no message frame ({exc})"], "specific": spec, "channel": None}
    channel = channel_for(pkt)
    section = "call" if channel["kind"] == "phone" else "message"
    faults = list(facts.get("faults") or pkt.get("faults") or [])
    fault = L.to_you(faults[0]) if faults else None
    if not fault:
        problems.append("no computed fault to name: the message has nothing true to say is wrong")
    if not spec or not (spec.get("text") or "").strip():
        problems.append("message.json has no specific line ({\"specific\": {\"text\": …, \"facts\": [...]}})")
        spec_text = ""
    else:
        spec_text = spec["text"].strip()
        if not re.search(r"[.?]$", spec_text):
            spec_text += "."
        if len(spec["text"].strip()) > SPECIFIC_MAX:
            problems.append(f"the specific line is {len(spec['text'].strip())} characters (at most {SPECIFIC_MAX})")
        ids = spec.get("facts") or []
        if not ids:
            problems.append("the specific line names no facts")
        high = high_facts(facts)
        all_ids = {f.get("id") for f in facts.get("facts") or [] if isinstance(f, dict)}
        problems += fact_problems(ids, high, all_ids, "the specific line")
    business = L.plain_name(facts.get("name") or pkt.get("name") or "")
    url = preview_url or L.preview_url((content or {}).get("slug") or "")
    frame = frames.get(section) or ""
    text = frame.format(business=business, fault=fault or "", specific=spec_text, preview_url=url)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) >= MESSAGE_MAX:
        problems.append(f"{len(text)} characters (under {MESSAGE_MAX})")
    links = [u.rstrip(".,;)") for u in re.findall(r"https?://\S+", text)]
    if section == "message" and links != [url]:
        problems.append(f"one link and it is the preview (found {len(links)}: {', '.join(links)[:120]})")
    if section == "call" and links:
        problems.append("the call opener carries no link")
    for rx in PRICE_RES:
        if rx.search(text):
            problems.append("a price in the message")
            break
    g = GUARDED.search(text)
    if g:
        problems.append(f"a guarded word in the message (\"{g.group(0)}\")")
    if "!" in text:
        problems.append("an exclamation mark")
    if "{" in text or "}" in text:
        problems.append("an unfilled brace in the message")
    if not text.startswith(("Hi " + business, "Say: \"Hi, is this " + business)):
        problems.append("the message greets the business by its name")
    return {"text": text, "specific": spec, "channel": channel, "section": section, "problems": problems,
            "chars": len(text), "preview_url": url, "fault": faults[0] if faults else None}


def cmd_message(args):
    wd = resolve_business_dir(args.dir) if args.dir and not Path(args.dir).is_dir() else Path(args.dir or ".").resolve()
    if not wd or not (wd / "packet.json").exists():
        die("prep message runs in a business's directory (or names one)")
    m = compose_message(wd)
    if args.json:
        print(json.dumps(m, indent=1))
        return 0 if not m["problems"] else 1
    ch = m["channel"] or {}
    print(f"send by: {ch.get('label')} → {ch.get('link')}" + (f" (profile {ch['profile']})" if ch.get("profile") else ""))
    print(f"   why: {ch.get('why')}")
    print(f"\n{m['text']}\n")
    print(f"{m['chars']} characters · " + ("lint OK" if not m["problems"] else "lint FAIL:\n  " + "\n  ".join(m["problems"])))
    return 0 if not m["problems"] else 1


# ---- sessions with a rate limit's patience ----------------------------------------------------------

class Ctx:
    """What a conductor's workers share: the deadline, the stop flag, the Places spend, the reuse map."""

    def __init__(self, run_dir, deadline, reuse=None):
        self.run_dir, self.deadline, self.reuse = Path(run_dir), deadline, reuse or {}
        self.spend = {"usd": 0.0, "calls": 0, "where": None}

    def stopped(self):
        return _STOP.is_set() or (self.run_dir / "STOP").exists()

    def late(self):
        return time.time() > self.deadline

    def left(self):
        return max(5.0, self.deadline - time.time())


def sessions_with_patience(ctx, wd, stage, model, prompt, seconds, resume=None, tag=None):
    """run_session, and on a rate limit wait PREP_RATE_WAIT and try again (never counted as a failure)."""
    out = []
    for attempt in range(RATE_TRIES + 1):
        if ctx.stopped():
            break
        t = tag if attempt == 0 else f"{tag}-r{attempt}"
        s = run_session(wd, stage, model, prompt, min(seconds, ctx.left()), resume=resume, tag=t)
        out.append(s)
        if s.get("rate_limited") and not ctx.late():
            log_line(ctx.run_dir, f"{Path(wd).name} {tag}: a rate limit — waiting {RATE_WAIT:.0f}s")
            _STOP.wait(RATE_WAIT)
            continue
        break
    return out


# ---- the stages ------------------------------------------------------------------------------------

BUILD_PROMPT = """Build this business's preview site. Your manual is BUILD.md in this directory: read it first, \
then facts.json and the draft content.json code wrote from the high facts. Make content.json read like their \
own site (never HTML: `leads preview --from content.json --out site` renders it), look at it with `shot`, \
write message.json, and run `prep check` until it prints OK. Caps: {minutes:g} minutes. Nothing leaves this \
directory: you never message, post or publish anything."""

FIX_PROMPT = """Round {round} of fixes for this site. {who} asks:

{fixes}

Fix content.json (and message.json if it's named) — never HTML. Render with `leads preview --from content.json \
--out site`, look with `shot`, run `prep check` until it prints OK, then stop. BUILD.md still holds."""

JUDGE_PROMPT = """Judge this preview site (round {round}). Your manual is JUDGE.md in this directory: read it \
first, then look at shots/phone.png before anything else, then the other screenshots, content.json and \
facts.json. Write review.json exactly as JUDGE.md shows, then stop."""

BATCH_PROMPT = """Tonight's {n} preview sites, side by side. Your manual is BATCH.md in this directory: read it, \
then messages.json, then look at every screen in screens/. Write batch.json exactly as BATCH.md shows, then stop."""


def drop(run_dir, slug, why):
    log_line(run_dir, f"{slug}: dropped — {why}")
    set_biz(run_dir, slug, stage="dropped", why=why)


def fail_stage(run_dir, slug, stage, why):
    """A stage that fails twice drops the business (plan § B67.3). Returns True when dropped."""
    b = get_run(run_dir)["businesses"][slug]
    att = dict(b.get("attempts") or {})
    att[stage] = att.get(stage, 0) + 1
    set_biz(run_dir, slug, attempts=att, last_error=why)
    log_line(run_dir, f"{slug} {stage}: failed ({why}), attempt {att[stage]}")
    if att[stage] >= 2:
        drop(run_dir, slug, f"{stage} failed twice ({why})")
        return True
    return False


def fable_in(sessions):
    return next((s["error"] for s in sessions if "Fable" in (s.get("error") or "")), None)


def stage_research(ctx, slug, b):
    run_dir = ctx.run_dir
    wd = run_dir / slug
    src = ctx.reuse.get(b["place_id"])
    if src:
        wd.mkdir(exist_ok=True)
        (wd / "log").mkdir(exist_ok=True)
        for f in ("facts.json", "listing.json", "packet.json"):
            if (src / f).exists():
                shutil.copy2(src / f, wd / f)
        for f in (src / "log").glob("research*"):
            shutil.copy2(f, wd / "log" / f.name)
        res = lint_file(wd / "facts.json")
        doc = read_json(wd / "facts.json", {}) or {}
        status = ("failed" if not res["ok"] else "skip" if doc.get("verdict") == "skip" else
                  "thin" if res["thin"] else "facts")
        entry = {"place_id": b["place_id"], "name": doc.get("name") or b.get("name"), "status": status,
                 "reason": doc.get("skip_reason") if status == "skip" else None, "lint": res, "sessions": [],
                 "reused_from": str(src)}
        record(run_dir, slug, "research", entry)
    else:
        entry = None
        for attempt in range(RATE_TRIES + 1):
            entry = research_one(b["place_id"], run_dir, spend=ctx.spend, fetch=True, slug=slug)
            last = (entry.get("sessions") or [{}])[-1]
            if last.get("rate_limited") and not ctx.late() and not ctx.stopped():
                log_line(run_dir, f"{slug} research: a rate limit — waiting {RATE_WAIT:.0f}s")
                _STOP.wait(RATE_WAIT)
                continue
            break
        if ctx.stopped():
            return
        if fable_in(entry.get("sessions") or []):
            return drop(run_dir, slug, fable_in(entry["sessions"]))
        if entry["status"] == "failed" and not (entry.get("lint") or {}).get("errors") and \
                not fail_stage(run_dir, slug, "research", entry.get("reason") or "no result"):
            return          # stays at research: tried again next pass
    # the facts gate (stage 3, code)
    st = entry["status"]
    if st == "facts":
        set_biz(run_dir, slug, stage="build", name=entry.get("name") or b.get("name"))
    elif st == "thin":
        drop(run_dir, slug, "thin facts (fewer than three high facts or no service)")
    elif st == "skip":
        drop(run_dir, slug, f"research said skip: {entry.get('reason')}")
    elif get_run(run_dir)["businesses"][slug].get("stage") != "dropped":
        drop(run_dir, slug, f"research: {entry.get('reason')}")


def assign_look_and_slug(run_dir, slug):
    """The look (least used in the run so far for this template, so no look takes over the night) and the
    preview's slug (name and town, stable: a place that had a preview keeps its slug)."""
    L = leads()
    with _RUN_LOCK:
        run = read_json(run_dir / "run.json", {})
        bs = run["businesses"]
        b = bs[slug]
        if b.get("look") and b.get("preview_slug"):
            return b
        facts = read_json(run_dir / slug / "facts.json", {}) or {}
        tpl = b.get("template") or template_for(facts.get("category") or b.get("category"))
        looks = L.template_looks(tpl)
        used = {}
        for s, o in bs.items():
            if s != slug and o.get("look") and o.get("stage") != "dropped" and o.get("template") == tpl:
                used[o["look"]] = used.get(o["look"], 0) + 1
        look = min(looks, key=lambda lk: (used.get(lk, 0), looks.index(lk)))
        mine = next((m["slug"] for m in L.previews_all() if m.get("place_id") == b["place_id"]), None)
        taken = {m["slug"] for m in L.previews_all() if m.get("place_id") != b["place_id"]} | \
                {o.get("preview_slug") for s, o in bs.items() if s != slug and o.get("preview_slug")}
        pslug = mine if mine and mine not in taken else L.preview_slug(facts.get("name") or b["name"],
                                                                         facts.get("city") or b.get("city") or "", taken)
        b.update(template=tpl, look=look, preview_slug=pslug)
        write_json(run_dir / "run.json", run)
        return b


def stage_build(ctx, slug, b):
    run_dir = ctx.run_dir
    wd = run_dir / slug
    b = assign_look_and_slug(run_dir, slug)
    stamp(wd, "build", None, None)
    if not (wd / "content.json").exists():
        facts = read_json(wd / "facts.json", {}) or {}
        images = prepare_images(wd, b["preview_slug"], facts.get("category") or b.get("category"))
        content = draft_content(wd, b["template"], b["look"], b["preview_slug"], images)
        write_json(wd / "content.json", content)
        write_json(wd / "content.draft.json", content)
    sessions = sessions_with_patience(ctx, wd, "build", MODEL_BUILD, BUILD_PROMPT.format(
        minutes=STAGE_MINUTES["build"]), STAGE_MINUTES["build"] * 60, tag="build")
    if ctx.stopped():
        return
    last = sessions[-1] if sessions else {}
    record(run_dir, slug, "build", {"sessions": sessions, "session_id": last.get("session_id")})
    if fable_in(sessions):
        return drop(run_dir, slug, fable_in(sessions))
    if last.get("session_id"):
        set_biz(run_dir, slug, build_session=last["session_id"])
    if not last.get("ok"):
        fail_stage(run_dir, slug, "build", last.get("error") or last.get("subtype") or "no result")
        return
    set_biz(run_dir, slug, stage="check")


def stage_check(ctx, slug, b):
    run_dir = ctx.run_dir
    res = run_gates(run_dir / slug)
    failing = [f"gate {k}: {p}" for k, g in res["gates"].items() for p in g["problems"]]
    rounds = int(b.get("rounds") or 0)
    record(run_dir, slug, f"check-{rounds}", {"ok": res["ok"], "problems": failing[:30], "sessions": []},
           usage_stage="check")
    if res["ok"]:
        set_biz(run_dir, slug, stage="judge")
    elif rounds < ROUNDS:
        set_biz(run_dir, slug, stage="fix", rounds=rounds + 1, fixes=failing[:20], fix_from="prep check")
    else:
        drop(run_dir, slug, f"the gates still fail after {ROUNDS} fix rounds: " + "; ".join(failing[:3]))


def take_shots(wd):
    """The judge's eyes, taken by code the same way for every site: the first phone screen, the whole
    page on a phone, the first desktop screen, the whole desktop page."""
    wd = Path(wd)
    (wd / "shots").mkdir(exist_ok=True)
    out = {}
    for name, extra in (("phone", ["--mobile"]), ("phone-full", ["--mobile", "--full", "--dpr", "1"]),
                        ("desktop", []), ("desktop-full", ["--full"])):
        dest = f"shots/{name}.png"
        try:
            r = subprocess.run([SHOT_BIN, "site/index.html", *extra, "--out", dest], cwd=wd, capture_output=True,
                               text=True, timeout=180)
            out[name] = (wd / dest).exists() and r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            out[name] = False
    return out


def validate_review(r):
    """(review, problem). A pass with a failing check is a fix; a fix with no list takes the failing lines."""
    if not isinstance(r, dict):
        return None, "review.json is missing or not JSON"
    v = r.get("verdict")
    checks = r.get("checks")
    if v not in ("pass", "fix", "drop"):
        return None, f"verdict {v!r} (pass, fix or drop)"
    if not isinstance(checks, list) or sorted(c.get("n") for c in checks if isinstance(c, dict)) != [1, 2, 3, 4, 5, 6]:
        return None, "checks must be the six lines, n 1 to 6"
    failing = [f"{c['n']}. {c.get('line')}" for c in checks if not c.get("ok")]
    fixes = [str(x) for x in r.get("fixes") or [] if str(x).strip()]
    if v == "pass" and failing:
        v = "fix"
    if v == "fix" and not fixes:
        fixes = failing
    if v == "fix" and not fixes:
        return None, "a fix with nothing to fix"
    return dict(r, verdict=v, fixes=fixes), None


def stage_judge(ctx, slug, b):
    run_dir = ctx.run_dir
    wd = run_dir / slug
    rnd = int(b.get("rounds") or 0) + 1
    take_shots(wd)
    stamp(wd, "judge", None, None)
    (wd / "review.json").unlink(missing_ok=True)
    sessions = sessions_with_patience(ctx, wd, "judge", MODEL_JUDGE, JUDGE_PROMPT.format(round=rnd),
                                      STAGE_MINUTES["judge"] * 60, tag=f"judge-{rnd}")
    if ctx.stopped():
        return
    review, problem = validate_review(read_json(wd / "review.json"))
    if review:
        write_json(wd / "log" / f"review-{rnd}.json", review)
    record(run_dir, slug, f"judge-{rnd}", {"sessions": sessions, "verdict": (review or {}).get("verdict"),
                                           "fixes": (review or {}).get("fixes"), "glad": (review or {}).get("glad"),
                                           "problem": problem}, usage_stage="judge")
    if fable_in(sessions):
        return drop(run_dir, slug, fable_in(sessions))
    if not review:
        fail_stage(run_dir, slug, "judge", problem)
        return
    rounds = int(b.get("rounds") or 0)
    if review["verdict"] == "pass":
        set_biz(run_dir, slug, stage="ready", glad=review.get("glad"))
    elif review["verdict"] == "drop":
        drop(run_dir, slug, "the judge: " + (review.get("glad") or "; ".join(review.get("fixes") or [])
                                             or next((c.get("line") for c in review["checks"] if not c.get("ok")), "drop")))
    elif rounds < ROUNDS:
        set_biz(run_dir, slug, stage="fix", rounds=rounds + 1, fixes=review["fixes"], fix_from="the judge")
    else:
        drop(run_dir, slug, f"still not a pass after {ROUNDS} fix rounds: " + "; ".join(review["fixes"][:2]))


def stage_fix(ctx, slug, b):
    run_dir = ctx.run_dir
    wd = run_dir / slug
    rnd = int(b.get("rounds") or 1)
    stamp(wd, "build", None, None)
    fixes = "\n".join(f"- {x}" for x in b.get("fixes") or [])
    prompt = FIX_PROMPT.format(round=rnd, who="The judge" if b.get("fix_from") == "the judge" else "`prep check`",
                               fixes=fixes)
    sid = b.get("build_session")
    sessions = sessions_with_patience(ctx, wd, "build", MODEL_BUILD, prompt, STAGE_MINUTES["fix"] * 60,
                                      resume=sid, tag=f"fix-{rnd}")
    if sid and sessions and not sessions[-1].get("session_id") and not ctx.stopped():
        # the resume itself failed (a lost session): the same fix list in a fresh build session
        sessions += sessions_with_patience(ctx, wd, "build", MODEL_BUILD, BUILD_PROMPT.format(
            minutes=STAGE_MINUTES["fix"]) + "\n\n" + prompt, STAGE_MINUTES["fix"] * 60, tag=f"fix-{rnd}-fresh")
    if ctx.stopped():
        return
    last = sessions[-1] if sessions else {}
    record(run_dir, slug, f"fix-{rnd}", {"sessions": sessions, "fixes": b.get("fixes")}, usage_stage="fix")
    if fable_in(sessions):
        return drop(run_dir, slug, fable_in(sessions))
    if last.get("session_id"):
        set_biz(run_dir, slug, build_session=last["session_id"])
    if not last.get("ok"):
        fail_stage(run_dir, slug, f"fix-{rnd}", last.get("error") or "no result")
        return
    set_biz(run_dir, slug, stage="check")


STAGES = {"research": stage_research, "build": stage_build, "check": stage_check, "judge": stage_judge,
          "fix": stage_fix}


def advance(ctx, slug):
    """One business from wherever run.json says it is to ready or dropped (or until stop / the deadline)."""
    while True:
        if ctx.stopped():
            return
        b = get_run(ctx.run_dir)["businesses"][slug]
        st = b.get("stage")
        if st in TERMINAL:
            return
        if ctx.late():
            drop(ctx.run_dir, slug, f"out of time at {st}")
            return
        log_line(ctx.run_dir, f"{slug}: {st}")
        try:
            STAGES[st](ctx, slug, b)
        except Exception as exc:  # noqa: BLE001 — one business failing never stops the night
            import traceback
            log_line(ctx.run_dir, f"{slug} {st}: {traceback.format_exc()[-600:]}")
            if fail_stage(ctx.run_dir, slug, st, f"{type(exc).__name__}: {exc}"):
                return


# ---- the conductor ----------------------------------------------------------------------------------

def reuse_map(reuse_id):
    """place_id → the directory of a finished research run's business whose facts linted."""
    if not reuse_id:
        return {}
    d = STATE / reuse_id
    rj = read_json(d / "run.json")
    if not rj:
        die(f"--reuse {reuse_id}: no run there")
    out = {}
    for s, b in (rj.get("businesses") or {}).items():
        if b.get("place_id") and (d / s / "facts.json").exists():
            out[b["place_id"]] = d / s
    return out


def kill_sessions(run_dir):
    for p in (Path(run_dir) / "pids").glob("*") if (Path(run_dir) / "pids").exists() else []:
        try:
            pid = int(p.name)
            os.killpg(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        p.unlink(missing_ok=True)


def conduct(run_id):
    """The state machine over run.json: four businesses at a time through their stages; a dropped one's
    place goes to the next in the reserve; then the batch pass and finish."""
    run_dir = STATE / run_id
    run = get_run(run_dir)
    if not run:
        die(f"no run {run_id}")
    os.environ.pop("LEADS_PREVIEW_YES", None)            # the previews project is Taylor's to create
    (run_dir / "STOP").unlink(missing_ok=True)
    _STOP.clear()
    kill_sessions(run_dir)                                 # whatever a killed conductor left running

    def on_term(signum, frame):
        _STOP.set()
        kill_sessions(run_dir)
    signal.signal(signal.SIGTERM, on_term)
    deadline = time.time() + max(60.0, HOURS * 3600 - FINISH_RESERVE_S)
    set_run(run_dir, state="running", pid=os.getpid(), deadline=dt.datetime.fromtimestamp(deadline, TZ).isoformat(
        timespec="seconds"), resumed=int(run.get("resumed", -1)) + 1)
    log_line(run_dir, f"conductor {os.getpid()} up; deadline {dt.datetime.fromtimestamp(deadline, TZ):%H:%M}")
    ctx = Ctx(run_dir, deadline, reuse_map((run.get("opts") or {}).get("reuse")))
    n = int(run.get("n") or N_DEFAULT)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, PARALLEL)) as pool:
            futs = {}
            while True:
                rj = get_run(run_dir)
                bs, order = rj["businesses"], rj["order"]
                if not ctx.stopped() and not ctx.late():
                    ready = sum(1 for s in order if bs[s].get("stage") == "ready")
                    going = [s for s in order if bs[s].get("role") == "active" and bs[s].get("stage") not in TERMINAL]
                    want = n - ready - len(going)
                    for s in order:
                        if want <= 0:
                            break
                        if bs[s].get("role") == "reserve" and bs[s].get("stage") not in TERMINAL:
                            set_biz(run_dir, s, role="active")
                            log_line(run_dir, f"{s}: from the reserve")
                            want -= 1
                    rj = get_run(run_dir)
                    for s in rj["order"]:
                        b = rj["businesses"][s]
                        if b.get("role") == "active" and b.get("stage") not in TERMINAL and s not in futs:
                            futs[s] = pool.submit(advance, ctx, s)
                if not futs:
                    break
                done, _ = concurrent.futures.wait(list(futs.values()), timeout=5,
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
                for s in [s for s, f in futs.items() if f in done]:
                    futs.pop(s)
                if ctx.stopped() and not futs:
                    break
        if ctx.places_spent() if hasattr(ctx, "places_spent") else ctx.spend["calls"]:
            ledger_append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                           "kind": "places_details", "tool": "prep", "calls": ctx.spend["calls"],
                           "cost_usd": round(ctx.spend["usd"], 4),
                           "billed_to": f"google:GOOGLE_MAPS_API_KEY({ctx.spend['where']})", "project": "global",
                           "for": f"prep {run_id}"})
            with _RUN_LOCK:
                rr = read_json(run_dir / "run.json", {})
                rr.setdefault("spend", {})["places_usd"] = round(rr.get("spend", {}).get("places_usd", 0)
                                                                  + ctx.spend["usd"], 4)
                write_json(run_dir / "run.json", rr)
            ctx.spend = {"usd": 0.0, "calls": 0, "where": None}
        if ctx.stopped():
            set_run(run_dir, state="stopped", pid=None)
            marker_path(run_id).unlink(missing_ok=True)
            log_line(run_dir, "stopped")
            return 3
        batch(ctx)
        opts = get_run(run_dir).get("opts") or {}
        return finish(run_dir, publish=not opts.get("no_publish"))
    except Exception as exc:  # noqa: BLE001
        import traceback
        log_line(run_dir, traceback.format_exc()[-1500:])
        set_run(run_dir, state="failed", error=f"{type(exc).__name__}: {exc}", pid=None)
        marker_path(run_id).unlink(missing_ok=True)
        if not (get_run(run_dir).get("opts") or {}).get("no_publish"):
            send_notify(f"Prep {run_id} stopped on an error ({type(exc).__name__}: {exc}). Nothing was sent. "
                        f"`prep status {run_id}` shows where it got to; `prep resume {run_id}` carries on.")
        return 1


# ---- stage 8: the batch pass (Opus, one session) -------------------------------------------------------

def batch(ctx):
    run_dir = ctx.run_dir
    set_run(run_dir, state="batch")
    rj = get_run(run_dir)
    ready = [s for s in rj["order"] if rj["businesses"][s].get("stage") == "ready"]
    res = {"schema": 1, "order": list(ready), "drop": {}, "notes": {}, "heroes_alike": [], "messages_alike": [],
           "last_word": None, "ran": False}
    looks = {}
    for s in ready:
        k = f"{rj['businesses'][s].get('template')}/{rj['businesses'][s].get('look')}"
        looks[k] = looks.get(k, 0) + 1
    res["looks"] = looks
    cap = max(4, -(-4 * len(ready) // 10))
    res["looks_ok"] = all(v <= cap for v in looks.values())
    if len(ready) >= 2 and not ctx.stopped():
        bd = run_dir / "batch"
        (bd / "screens").mkdir(parents=True, exist_ok=True)
        rows = []
        for s in ready:
            wd = run_dir / s
            c = read_json(wd / "content.json", {}) or {}
            hero = (c.get("images") or {}).get("hero") or {}
            if (wd / "shots" / "phone.png").exists():
                shutil.copy2(wd / "shots" / "phone.png", bd / "screens" / f"{s}.png")
            m = compose_message(wd)
            rows.append({"slug": s, "name": c.get("name"), "category": c.get("category"), "city": c.get("city"),
                         "look": c.get("look"), "hero_id": hero.get("id"), "hero_alt": hero.get("alt"),
                         "screen": f"screens/{s}.png", "message": m["text"]})
        write_json(bd / "messages.json", rows)
        stamp(bd, "batch", None, None)
        (bd / "batch.json").unlink(missing_ok=True)
        sessions = sessions_with_patience(ctx, bd, "batch", MODEL_JUDGE, BATCH_PROMPT.format(n=len(ready)),
                                          STAGE_MINUTES["batch"] * 60, tag="batch")
        record(run_dir, None, "batch", {"sessions": sessions}, usage_stage="batch")
        got = read_json(bd / "batch.json")
        if isinstance(got, dict) and not fable_in(sessions):
            order = [s for s in got.get("order") or [] if s in ready]
            res["order"] = list(dict.fromkeys(order + [s for s in ready if s not in order]))
            res["drop"] = {s: str(w) for s, w in (got.get("drop") or {}).items() if s in ready}
            for k in ("notes", "heroes_alike", "messages_alike", "last_word"):
                if got.get(k) is not None:
                    res[k] = got[k]
            res["ran"] = True
        else:
            res["problem"] = fable_in(sessions) or "no batch.json (the order stays the pick's)"
        res["sessions"] = len(sessions)
    for s, why in res["drop"].items():
        drop(run_dir, s, f"the batch pass: {why}")
    write_json(run_dir / "batch.json", res)
    set_run(run_dir, outline_order=[s for s in res["order"] if s not in res["drop"]])
    return res


# ---- stage 9: finish (code) ------------------------------------------------------------------------------

def send_notify(text):
    try:
        r = subprocess.run([NOTIFY_BIN, text], capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def found_lines(facts, k=3):
    keep = ("service", "specialty", "about", "since", "credential", "area", "other")
    fs = [f for f in facts.get("facts") or [] if isinstance(f, dict) and f.get("kind") in keep]
    high = [f["text"] for f in fs if f.get("confidence") == "high"]
    med = [f"{f['text']} (unconfirmed)" for f in fs if f.get("confidence") != "high"]
    return (high[:k - 1] + med[:1] + high[k - 1:])[:k] if med else high[:k]


def outline_entry(i, wd, m):
    facts, listing, pkt, content = business_files(wd)
    li = pkt.get("listing") or {}
    ch = m["channel"] or {}
    rating = li.get("rating")
    head = [f"{i}. {content.get('name')} — {facts.get('category')}, {facts.get('city')}",
            (f"{rating}★ ({li.get('review_count')} reviews)" if rating else "no rating")
            + (f" · {m['fault']}" if m.get("fault") else "")]
    found = found_lines(facts)
    if found:
        head.append("Found: " + " · ".join(found))
    head.append(f"Site: {m['preview_url']}")
    claim = read_json(Path(wd) / "site" / "claim.json")
    claim_url = (claim or {}).get("url") or leads().claim_link(content, Path(wd))
    head.append(f"Sign-up: {claim_url}")
    asks = [a for a in facts.get("owner_asks") or [] if a]
    head.append("To finish it they'd send: " + ("; ".join(asks[:4]) if asks else "their own photos"))
    head.append(f"Send by {ch.get('label')}: {ch.get('link')}" + (f" (profile {ch['profile']})" if ch.get("profile") else "")
                + f" — {ch.get('why')}")
    return "\n".join(head)


def finish(run_dir, publish=True):
    """Stage 9, all code: the gates again, the publish (never --yes), the hold for the delivered only, the
    ledger row, the outline, notify, the marker removed. A failed publish holds the messages back."""
    L = leads()
    run_dir = Path(run_dir)
    run_id = run_dir.name
    set_run(run_dir, state="finishing")
    rj = get_run(run_dir)
    order = rj.get("outline_order") or rj["order"]
    bs = rj["businesses"]
    ready = [s for s in order if bs.get(s, {}).get("stage") == "ready"]
    delivered = []
    for s in ready:
        res = run_gates(run_dir / s)
        if res["ok"]:
            delivered.append(s)
        else:
            bad = [f"gate {k}: {p}" for k, g in res["gates"].items() for p in g["problems"]]
            drop(run_dir, s, "failed the gates at finish: " + "; ".join(bad[:2]))
    publish_note = None
    if publish and delivered:
        for s in list(delivered):
            r = subprocess.run([sys.executable, str(LEADS_BIN), "preview", "--from", str(run_dir / s / "content.json"),
                                "--no-publish"], capture_output=True, text=True, env=dict(os.environ))
            if r.returncode != 0:
                drop(run_dir, s, f"leads preview couldn't render it into the previews tree: {(r.stderr or r.stdout)[-200:]}")
                delivered.remove(s)
            else:
                register_images(run_dir / s)
        ok, host = L.preview_publish(dry=False)
        if not ok:
            set_run(run_dir, state="publish_failed", pid=None, delivered=delivered)
            write_outline(run_dir, delivered, held=True)
            send_notify(f"Prep {run_id}: {len(delivered)} sites ready, but the publish failed, so no message went "
                        f"out and nothing is held. `prep publish {run_id}` retries; the outline waits in "
                        f"{run_dir / 'outline.md'}.")
            marker_path(run_id).unlink(missing_ok=True)
            return 2
        publish_note = host
    msgs = write_outline(run_dir, delivered, held=False)
    delivered = [s for s in delivered if s in msgs]
    if publish and delivered:
        rows = [(bs[s]["place_id"], read_json(run_dir / s / "content.json", {}).get("name") or bs[s].get("name"))
                for s in delivered]
        L.STATE.mkdir(parents=True, exist_ok=True)
        with open(L.STATE / "remote.jsonl", "a") as f:
            f.write(json.dumps({"ts": now().isoformat(timespec="seconds"), "for": today().isoformat(),
                                "place_ids": [r[0] for r in rows], "names": [r[1] for r in rows], "mode": "prep",
                                "run": run_id}) + "\n")
    rj = get_run(run_dir)
    usage = rj.get("usage") or {}
    ledger_append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "kind": "prep",
                   "tool": "prep", "run": run_id, "delivered": len(delivered),
                   "researched": sum(1 for b in rj["businesses"].values() if "research" in (b.get("stages") or {})),
                   "dropped": sum(1 for b in rj["businesses"].values() if b.get("stage") == "dropped"),
                   "cost_usd": round(float((rj.get("spend") or {}).get("places_usd") or 0), 4),
                   "plan_usd_list": round(sum(float(u.get("plan_usd_list") or 0) for u in usage.values()), 4),
                   "billed_to": "plan:claude.ai", "project": "global", "rehearsal": not publish,
                   "models": sorted({m for u in usage.values() for m in u.get("models") or []}),
                   "usage": {k: {kk: v for kk, v in u.items() if kk != "refusals"} for k, u in usage.items()}})
    lines = (run_dir / "outline.notify.json")
    notes = read_json(lines, [])
    sent = None
    if publish:
        sent = [send_notify(t) for t in notes]
    set_run(run_dir, state="done" if publish else "rehearsed", pid=None, delivered=delivered,
            finished=now().isoformat(timespec="seconds"), host=publish_note,
            notified=(sum(1 for x in sent if x) if sent is not None else None))
    marker_path(run_id).unlink(missing_ok=True)
    log_line(run_dir, f"finished: {len(delivered)} delivered" + ("" if publish else " (rehearsal: nothing published, "
                                                                                  "nothing held, nobody notified)"))
    return 0


def register_images(wd):
    """The images a delivered site shows, in the previews' registry, so no later preview repeats them."""
    L = leads()
    c = read_json(Path(wd) / "content.json", {}) or {}
    have = {(r.get("slug"), str(r.get("id"))) for r in L.image_registry()}
    for role, im in (c.get("images") or {}).items():
        if (c["slug"], str(im.get("id"))) not in have:
            L.image_register(c["slug"], role, im, im.get("alt") or "")


def write_outline(run_dir, delivered, held=False):
    """outline.md (what `prep last` reprints), outline.notify.json (the messages notify sends, in order).
    Returns {slug: message} for the businesses whose message passed its lint."""
    run_dir = Path(run_dir)
    rj = get_run(run_dir)
    bs = rj["businesses"]
    msgs, blocks, notes = {}, [], []
    for s in delivered:
        m = compose_message(run_dir / s)
        if m["problems"]:
            drop(run_dir, s, "the message failed its lint at finish: " + "; ".join(m["problems"][:2]))
            continue
        msgs[s] = m
    rj = get_run(run_dir)
    bs = rj["businesses"]
    dropped = [(s, b) for s, b in bs.items() if b.get("stage") == "dropped"]
    researched = sum(1 for b in bs.values() if "research" in (b.get("stages") or {}))
    header = (f"Prep {run_dir.name} · {len(msgs)} ready · {researched} researched, {len(dropped)} dropped"
              + (" · HELD: the publish failed, nothing sent" if held else ""))
    notes.append(header)
    for i, (s, m) in enumerate(msgs.items(), 1):
        entry = outline_entry(i, run_dir / s, m)
        blocks.append(f"{entry}\n\nThe message ({m['chars']} characters):\n\n{m['text']}")
        notes += [entry, m["text"]]
    if dropped:
        tail = "Dropped: " + "; ".join(f"{b.get('name') or s} — {b.get('why')}" for s, b in dropped)
        notes.append(tail)
    else:
        tail = "Dropped: none."
    batch_ = read_json(run_dir / "batch.json", {}) or {}
    md = [f"# {header}", ""]
    if batch_.get("last_word"):
        md += [f"_{batch_['last_word']}_", ""]
    md += ["\n\n---\n\n".join(blocks) if blocks else "Nothing ready tonight.", "", "---", "", tail, "",
           f"Reply `sent 1 3 4` for the ones you send (`leads sent` logs them)." if not held else
           f"`prep publish {run_dir.name}` retries the publish, then sends this."]
    (run_dir / "outline.md").write_text("\n".join(md) + "\n")
    write_json(run_dir / "outline.notify.json", notes if not held else [header])
    write_json(run_dir / "outline.json", [{"n": i, "slug": s, "text": m["text"], "channel": m["channel"],
                                           "preview_url": m["preview_url"]} for i, (s, m) in enumerate(msgs.items(), 1)])
    return msgs


# ---- the commands ------------------------------------------------------------------------------------

def preflight(no_publish=False):
    """Why a run can't start, or []. The login is the subscription and neither model is Fable, always;
    for a real run also the approved frame and the previews project (Taylor's), and no other run going."""
    out = []
    for m in (MODEL_BUILD, MODEL_JUDGE):
        if not m or "fable" in m.lower():
            out.append(f"model {m!r}: never Fable, always named")
    st = auth_status()
    if not (st.get("authMethod") == "claude.ai" and st.get("loggedIn") and st.get("subscriptionType")):
        out.append(f"the claude login is not the subscription ({st.get('authMethod') or st.get('error') or 'logged out'})")
    live = live_markers()
    if live:
        out.append(f"prep run {live[0][0]} is still going (pid {live[0][1]}): `prep status` / `prep stop`")
    if not no_publish:
        if not frame_approved():
            out.append("the message frame isn't approved: read templates/prep/message.md, then `prep approve`")
        ok, why = previews_project()
        if not ok:
            out.append(f"the previews project isn't there yet ({why}): TAYLOR-TODO §1 \"Preview sites\"")
    return out


def previews_project():
    L = leads()
    try:
        r = subprocess.run([str(L.SITE_BIN), "previews", "--ls", "--project", L.PREVIEW_PROJECT],
                           capture_output=True, text=True, timeout=60, env=dict(os.environ, SITE_ADMIN="1"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, (out.splitlines()[-1] if out else f"exit {r.returncode}")[:160]


def init_run(picks, n, opts):
    run_id, run_dir = new_run(kind="prep")
    bs, order = {}, []
    for p in picks:
        s = dir_slug(p["name"], p["city"], set(order))
        order.append(s)
        bs[s] = {"place_id": p["place_id"], "name": p["name"], "category": p["category"], "segment": p["segment"],
                 "city": p["city"], "role": p["role"], "stage": "research", "rounds": 0, "attempts": {},
                 "template": p["template"], "why_picked": p["why"]}
    set_run(run_dir, kind="prep", state="picked", n=n, opts=opts, order=order, businesses=bs,
            caps=dict(CAPS, parallel=PARALLEL, hours=HOURS, reserve=RESERVE, image_usd=IMAGE_USD,
                      places_usd=PLACES_USD, minutes=STAGE_MINUTES, turns=STAGE_TURNS))
    write_json(run_dir / "picks.json", picks)
    return run_id, run_dir


def launch(run_id, run_dir, foreground=False):
    REQUESTS.mkdir(parents=True, exist_ok=True)
    marker = marker_path(run_id)
    if foreground:
        marker.write_text(f"{os.getpid()}\nprep run {run_id} (foreground) {now():%Y-%m-%d %H:%M}\n")
        return conduct(run_id)
    log = open(run_dir / "conductor.log", "a")
    cmd = ["timeout", "--signal=TERM", "--kill-after=60", f"{int(HOURS * 3600 + 600)}s", sys.executable, str(SELF),
           "conduct", run_id]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                         env=dict(os.environ))
    marker.write_text(f"{p.pid}\nprep run {run_id} {now():%Y-%m-%d %H:%M}\n")
    set_run(run_dir, launcher_pid=p.pid)
    return 0


def cmd_run(args):
    n = max(1, min(args.n or N_DEFAULT, N_MAX))
    for m in (MODEL_BUILD, MODEL_JUDGE):
        refuse_fable(m)
    no_pub = args.no_publish or args.dry_run
    if not args.dry_run:
        why = preflight(no_publish=no_pub)
        if why:
            die("not starting:\n  " + "\n  ".join(why))
    if args.places:
        picks = picks_for_places(list(dict.fromkeys(args.places)), n)
        skipped = {}
    else:
        picks, skipped = pick(n, args.segment, args.allow_calls)
    if not picks:
        die("nothing to pick: " + ("; ".join(f"{v} {k}" for k, v in skipped.items()) or "the pool is empty"))
    active = [p for p in picks if p["role"] == "active"]
    if args.dry_run:
        print(f"prep run --dry-run: {len(active)} picked, {len(picks) - len(active)} in reserve — nothing started")
        for i, p in enumerate(picks, 1):
            print(f"  {i:2}. {p['name']} · {p['category']} · {p['city']} — {p['why']}"
                  + ("" if p["role"] == "active" else " (reserve)"))
        return 0
    opts = {"segment": args.segment, "allow_calls": args.allow_calls, "no_publish": bool(args.no_publish),
            "reuse": args.reuse, "places": args.places or None}
    if args.reuse:
        reuse_map(args.reuse)
    run_id, run_dir = init_run(picks, n, opts)
    names = ", ".join(p["name"] for p in active)
    when = (now() + dt.timedelta(hours=HOURS)).strftime("%-I:%M %p")
    print(f"Prep {run_id}: {len(active)} picked ({names}), {len(picks) - len(active)} in reserve. "
          + ("Rehearsal: nothing is published and nobody is notified; " if args.no_publish else
             f"Running now; the outline comes by message by {when} at the latest, and ")
          + f"lands in {run_dir / 'outline.md'}.")
    sys.stdout.flush()
    return launch(run_id, run_dir, foreground=args.foreground)


def latest_run(want=None, states=None):
    if want:
        d = STATE / want
        if not (d / "run.json").exists():
            die(f"no run {want} under {STATE}")
        return d
    for d in sorted(STATE.iterdir(), reverse=True) if STATE.exists() else []:
        rj = read_json(d / "run.json")
        if rj and rj.get("kind") == "prep" and (states is None or rj.get("state") in states):
            return d
    die("no prep run yet" + (f" in state {', '.join(states)}" if states else ""))


def cmd_conduct(args):
    return conduct(args.run_id)


def cmd_resume(args):
    run_dir = latest_run(args.run_id, None if args.run_id else ("stopped", "running", "batch", "finishing", "failed",
                                                                  "picked"))
    rj = get_run(run_dir)
    if rj.get("state") in ("done", "rehearsed"):
        die(f"{run_dir.name} is {rj['state']}: nothing to resume")
    if rj.get("state") == "publish_failed":
        die(f"{run_dir.name}: the publish failed — `prep publish {run_dir.name}` retries it")
    pid = rj.get("pid")
    if pid and pid_alive(pid) and pid != os.getpid():
        die(f"{run_dir.name}'s conductor is still running (pid {pid}); `prep stop` first")
    why = [w for w in preflight(no_publish=(rj.get("opts") or {}).get("no_publish")) if "is still going" not in w]
    if why:
        die("not resuming:\n  " + "\n  ".join(why))
    left = {s: b.get("stage") for s, b in rj["businesses"].items() if b.get("stage") not in TERMINAL}
    print(f"Prep {run_dir.name} resumed: {len(left)} still in progress "
          f"({', '.join(f'{s} at {st}' for s, st in list(left.items())[:6])}).")
    sys.stdout.flush()
    return launch(run_dir.name, run_dir, foreground=args.foreground)


def cmd_stop(args):
    run_dir = latest_run(args.run_id, None if args.run_id else LIVE_STATES)
    (run_dir / "STOP").write_text(now().isoformat(timespec="seconds") + "\n")
    rj = get_run(run_dir)
    for pid in {rj.get("pid"), rj.get("launcher_pid"), marker_pid(marker_path(run_dir.name))}:
        if pid and pid_alive(pid) and pid != os.getpid():
            for sig_target in (lambda: os.killpg(pid, signal.SIGTERM), lambda: os.kill(pid, signal.SIGTERM)):
                try:
                    sig_target()
                    break
                except (ProcessLookupError, PermissionError):
                    continue
    kill_sessions(run_dir)
    set_run(run_dir, state="stopped", pid=None)
    marker_path(run_dir.name).unlink(missing_ok=True)
    print(f"Prep {run_dir.name} stopped. `prep resume {run_dir.name}` carries on where it was.")
    return 0


def usage_lines(usage):
    out = []
    for stage in ("research", "build", "check", "judge", "fix", "batch"):
        u = usage.get(stage)
        if not u or not u.get("sessions"):
            continue
        out.append(f"  {stage:8} {u['sessions']:3} sessions · in {u['input_tokens'] + u['cache_read_input_tokens'] + u['cache_creation_input_tokens']:,}"
                   f" (cached {u['cache_read_input_tokens']:,}) · out {u['output_tokens']:,} · list ${u['plan_usd_list']:.2f}"
                   f" · {u['permission_denials']} refused · {', '.join(u['models'])}")
    return out


def cmd_status(args):
    run_dir = latest_run(args.run_id)
    rj = get_run(run_dir)
    mk = marker_path(run_dir.name)
    alive = bool(rj.get("pid")) and pid_alive(rj.get("pid"))
    print(f"Prep {run_dir.name} · {rj.get('state')} · n {rj.get('n')} · "
          + (f"conductor {rj['pid']} running" if alive else "no conductor running")
          + (f" · marker {mk.name}" if mk.exists() else "") + (" · rehearsal" if (rj.get("opts") or {}).get("no_publish") else ""))
    for i, s in enumerate(rj.get("order") or [], 1):
        b = rj["businesses"][s]
        role = "" if b.get("role") == "active" else " (reserve)"
        extra = f" — {b['why']}" if b.get("why") else ""
        look = f" [{b.get('template')}/{b.get('look')}]" if b.get("look") else ""
        print(f"  {i:2}. {s}: {b.get('stage')}{look}{role}{extra}"
              + (f" · round {b['rounds']}" if b.get("rounds") else ""))
    lines = usage_lines(rj.get("usage") or {})
    if lines:
        print("usage by stage (the plan's, notional):")
        print("\n".join(lines))
    if (run_dir / "outline.md").exists():
        print(f"outline: {run_dir / 'outline.md'}")
    return 0


def cmd_finish(args):
    run_dir = latest_run(args.run_id)
    rj = get_run(run_dir)
    if rj.get("pid") and pid_alive(rj["pid"]) and rj["pid"] != os.getpid():
        die(f"{run_dir.name}'s conductor is running (pid {rj['pid']})")
    no_pub = args.no_publish or (rj.get("opts") or {}).get("no_publish")
    if not no_pub:
        why = [w for w in preflight(False) if "is still going" not in w]
        if why:
            die("not finishing:\n  " + "\n  ".join(why))
    code = finish(run_dir, publish=not no_pub)
    print((run_dir / "outline.md").read_text() if (run_dir / "outline.md").exists() else f"finish: exit {code}")
    return code


def cmd_publish(args):
    run_dir = latest_run(args.run_id, None if args.run_id else ("publish_failed",))
    rj = get_run(run_dir)
    if rj.get("state") != "publish_failed":
        die(f"{run_dir.name} is {rj.get('state')}: only a failed publish is retried here")
    why = [w for w in preflight(False) if "is still going" not in w]
    if why:
        die("not publishing:\n  " + "\n  ".join(why))
    code = finish(run_dir, publish=True)
    print(f"Prep {run_dir.name}: " + ("published and sent" if code == 0 else "the publish failed again"))
    return code


def cmd_last(args):
    run_dir = latest_run(args.run_id, None if args.run_id else ("done", "rehearsed", "publish_failed"))
    md = run_dir / "outline.md"
    if not md.exists():
        die(f"{run_dir.name} has no outline yet")
    if not args.html:
        print(md.read_text().rstrip())
        return 0
    import html as htmllib
    rows = read_json(run_dir / "outline.json", []) or []
    body = htmllib.escape(md.read_text())
    cards = "".join(f'<section><h2>{r["n"]}. {htmllib.escape(r["slug"])}</h2><p><a href="{htmllib.escape(r["preview_url"])}">'
                    f'the site</a> · <a href="{htmllib.escape((r.get("channel") or {}).get("link") or "#")}">send</a></p>'
                    f'<textarea readonly rows="7">{htmllib.escape(r["text"])}</textarea></section>' for r in rows)
    page = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta name=robots content=noindex><title>Prep {run_dir.name}</title>"
            f"<style>body{{font:16px/1.5 system-ui;margin:0 auto;max-width:44rem;padding:1rem;background:#fff;color:#111}}"
            f"textarea{{width:100%;font:inherit}}pre{{white-space:pre-wrap}}</style>"
            f"<h1>Prep {run_dir.name}</h1>{cards}<details><summary>The whole outline</summary><pre>{body}</pre></details>")
    out = run_dir / "outline.html"
    out.write_text(page)
    print(out)
    return 0


def cmd_approve(args):
    frames = frame_sections()
    sample = {"business": "Pinnacle Painting", "fault": "there's no website on your listing",
              "specific": "Your listing shows kitchen cabinets as the main work, so I put that first.",
              "preview_url": "https://previews.patchlamp.com/pinnacle-painting-sandy/"}
    problems = []
    for k in ("message", "call"):
        if k not in frames:
            problems.append(f"no ## {k} section")
            continue
        text = frames[k].format(**sample)
        print(f"───── {k} ─────\n{text}\n")
        for want in ("{business}", "{fault}", "{specific}") + (("{preview_url}",) if k == "message" else ()):
            if want not in frames[k]:
                problems.append(f"{k}: {want} is missing")
        if any(rx.search(text) for rx in PRICE_RES):
            problems.append(f"{k}: a price")
        if GUARDED.search(text):
            problems.append(f"{k}: a guarded word ({GUARDED.search(text).group(0)})")
        if "!" in text:
            problems.append(f"{k}: an exclamation mark")
        if len(text) >= MESSAGE_MAX - SPECIFIC_MAX + len(sample["specific"]) and len(text) >= MESSAGE_MAX:
            problems.append(f"{k}: too long")
    if problems:
        die("not approved — fix these first: " + "; ".join(problems))
    if args.dry_run:
        print("[dry-run] not recorded.")
        return 0
    write_json(approved_file(), {"message.md": sha_of(FRAME), "at": now().isoformat(timespec="seconds"),
                                 "file": str(FRAME)})
    print(f"Approved: templates/prep/message.md ({sha_of(FRAME)[:12]}). Editing it un-approves it.")
    return 0
