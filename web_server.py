#!/usr/bin/env python3
"""web_server.py – Local paper viewer/editor server + static site generator"""

import sys, re, json, mimetypes, base64, shutil, os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
LAYOUT_FILE  = BASE_DIR / "layout.json"
RATINGS_FILE = BASE_DIR / "ratings.json"
MASTER_FILE  = BASE_DIR / "master_notes.md"
DEFAULT_BIB  = "template.bib"


def available_bib_files():
    return sorted(p.name for p in BASE_DIR.glob("*.bib") if p.is_file())


def default_bib_name():
    return DEFAULT_BIB if (BASE_DIR / DEFAULT_BIB).exists() else (available_bib_files()[0] if available_bib_files() else DEFAULT_BIB)


def master_notes_path(bib_name=None):
    bib_name = bib_name or get_active_bib_name()
    if bib_name == DEFAULT_BIB:
        return MASTER_FILE
    return BASE_DIR / f"master_notes_{Path(bib_name).stem}.md"


def normalize_layout(data):
    data = dict(data or {})
    active = data.get("active_bib") or default_bib_name()
    if active not in available_bib_files():
        active = default_bib_name()
    if not isinstance(data.get("orders"), dict):
        legacy_order = data.get("order") or []
        data["orders"] = {active: legacy_order}
    data["active_bib"] = active
    data.setdefault("view", "list")
    return data

# ─── bib parser ───────────────────────────────────────────────────────────────
# NOTE: the selected .bib file is the source of truth and must stay read-only
# from this codebase — only ever .read_text() it here, never .write_text().
def parse_bib(bib_path=None):
    bib_path = Path(bib_path) if bib_path else BASE_DIR / get_active_bib_name()
    text = bib_path.read_text(encoding='utf-8')
    entries = {}
    for m in re.finditer(r'@(\w+)\{(\w+),(.*?)(?=\n@|\Z)', text, re.DOTALL):
        etype, key, body = m.group(1), m.group(2), m.group(3)
        fields = {'_type': etype.lower()}
        for fm in re.finditer(r'(\w+)\s*=\s*\{(.*?)\}(?=\s*,|\s*\n\s*[}\w])', body, re.DOTALL):
            fields[fm.group(1).lower()] = re.sub(r'\s+', ' ', fm.group(2)).strip()
        entries[key] = fields
    return entries

def bib_order(bib_path=None):
    bib_path = Path(bib_path) if bib_path else BASE_DIR / get_active_bib_name()
    text = bib_path.read_text(encoding='utf-8')
    return re.findall(r'@\w+\{(\w+),', text)

def bib_warnings(bib_path=None):
    """Sanity-check the selected bib for mistakes that make an entry silently
    vanish or render with missing data (a malformed entry just fails the
    parse_bib() regex with no error otherwise)."""
    bib_path = Path(bib_path) if bib_path else BASE_DIR / get_active_bib_name()
    text = bib_path.read_text(encoding='utf-8')
    label = bib_path.name
    warnings = []

    starts = re.findall(r'@\w+\s*\{\s*([^,\s}]*)', text)
    parsed = parse_bib(bib_path)
    missing = [k for k in starts if k and k not in parsed]
    if missing:
        warnings.append(
            f"{label}: " + ", ".join(sorted(set(missing))) +
            " didn't parse — check for a missing comma right after the key, or a brace mismatch."
        )

    for key, f in parsed.items():
        missing_fields = [name for name in ('title', 'author', 'year') if not f.get(name)]
        if missing_fields:
            warnings.append(f"'{key}': missing {', '.join(missing_fields)}.")

    for m in re.finditer(r'@\w+\{(\w+),(.*?)(?=\n@|\Z)', text, re.DOTALL):
        key, body = m.group(1), m.group(2)
        # body includes the entry's own closing "}" (captured up to the next
        # "@" or EOF), so a well-formed entry is off by exactly one brace.
        stripped = body.rstrip()
        if stripped.endswith('}'):
            stripped = stripped[:-1]
        if stripped.count('{') != stripped.count('}'):
            warnings.append(f"'{key}': braces look unbalanced — a field value may be missing a closing brace.")

    warnings += bib_content_warnings(parsed)
    return warnings

def cross_bib_warnings():
    """Checks that need every .bib file at once, so they surface regardless
    of which one is currently active: the same key defined in two files (a
    citation moved without deleting the old copy), and a paper folder whose
    key isn't in any .bib file (the citation was deleted/renamed and the
    folder was left behind)."""
    warnings = []
    origin = {}
    for bib_name in available_bib_files():
        try:
            entries = parse_bib(BASE_DIR / bib_name)
        except Exception:
            continue
        for key in entries:
            if key in origin:
                warnings.append(f"'{key}' is defined in both {origin[key]} and {bib_name} — remove it from one.")
                continue
            origin[key] = bib_name

    for folder in sorted(BASE_DIR.iterdir()):
        name = folder.name
        if not folder.is_dir() or name.startswith('.') or name.startswith('_') or name == 'site':
            continue
        if not (folder / f"{name}.md").exists() and not (folder / f"{name}_ai.md").exists():
            continue
        if name not in origin:
            warnings.append(f"'{name}/' has no matching entry in any .bib file — delete the folder, or re-add its citation.")
    return warnings

def bib_content_warnings(parsed):
    """Duplicate entries (same DOI or same title under different keys) and
    entries with no DOI. Shared by papers.py and web_server.py."""
    warnings = []
    by_doi, by_title = {}, {}
    for key, f in parsed.items():
        doi = re.sub(r'^(https?://)?(dx\.)?doi\.org/', '', (f.get('doi') or '').strip().lower()).rstrip('.,;')
        if not doi:
            m = re.search(r'10\.\d{4,9}/[^\s"<>]+', f.get('url', '') or '', re.I)
            doi = m.group(0).lower().rstrip('.,;') if m else ''
        if doi:
            by_doi.setdefault(doi, []).append(key)
        else:
            warnings.append(f"'{key}': no doi field.")
        title = re.sub(r'[^a-z0-9]+', ' ', (f.get('title') or '').lower()).strip()
        if title:
            by_title.setdefault(title, []).append(key)
    for doi, keys in by_doi.items():
        if len(keys) > 1:
            warnings.append(f"duplicate DOI {doi}: {', '.join(keys)} — keep one and delete the rest.")
    seen_doi_dups = {tuple(k) for k in by_doi.values() if len(k) > 1}
    for title, keys in by_title.items():
        if len(keys) > 1 and tuple(keys) not in seen_doi_dups:
            warnings.append(f"duplicate title \"{parsed[keys[0]].get('title', '')[:60]}\": {', '.join(keys)} — keep one and delete the rest.")
    return warnings

# ─── venue short name ─────────────────────────────────────────────────────────
VENUE_PATTERNS = [
    ('Creativity and Cognition', 'C&C'),
    ('Computer-Supported Cooperative Work', 'CSCW'),
    ('Human Factors in Computing Systems', 'CHI'),
    ('Human-Robot Interaction', 'HRI'),
    ('User Interface Software and Technology', 'UIST'),
    ('Tangible, Embedded and Embodied Interaction', 'TEI'),
    ('Designing Interactive Systems', 'DIS'),
    ('ACM Multimedia', 'ACM MM'),
    ('Neural Information Processing Systems', 'NeurIPS'),
    ('International Conference on Machine Learning', 'ICML'),
    ('International Joint Conference on Artificial Intelligence', 'IJCAI'),
    ('Association for Computational Linguistics', 'ACL'),
    ('Empirical Methods in Natural Language Processing', 'EMNLP'),
    ('Conference on Computer Vision and Pattern Recognition', 'CVPR'),
    ('International Conference on Computer Vision', 'ICCV'),
    ('European Conference on Computer Vision', 'ECCV'),
]

def make_venue_short(venue, year):
    if not venue: return ''
    year_suffix = "'" + str(year)[-2:] if year else ''
    low = venue.lower()
    for pattern, abbr in VENUE_PATTERNS:
        if pattern.lower() in low:
            prefix = ''
            if 'extended abstract' in low: prefix = 'EA '
            elif 'workshop' in low: prefix = 'WS '
            return (prefix + abbr + (' ' + year_suffix if year_suffix else '')).strip()
    stripped = re.sub(
        r'\b(Proceedings?|of|the|Annual|ACM/?IEEE|ACM|IEEE|International|Conference|Symposium|Workshop|on)\b',
        '', venue, flags=re.I)
    parts = [w for w in stripped.split() if len(w) > 2][:3]
    short = ' '.join(parts)
    return (short + (' ' + year_suffix if year_suffix else '')).strip() if short else (venue[:12] + '...')

# ─── affiliations ─────────────────────────────────────────────────────────────
# ai_file.md is a master file: the AI writes it via `analyze`, but the user can
# hand-edit it too (e.g. fixing a wrong/missing affiliation tag). A bare
# "<unknown>" placeholder is filtered out here so it never shows as a real tag.
_PLACEHOLDER_TAGS = ('unknown', 'br', 'p', 'em', 'strong', 'a')

def parse_affiliations(key):
    ai_file = BASE_DIR / key / f"{key}_ai.md"
    if not ai_file.exists(): return []
    text = ai_file.read_text(encoding='utf-8')
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    m = re.search(r'## Affiliations\n(.*?)(?=\n##|\n---|\Z)', text, re.DOTALL)
    section = m.group(1) if m else text
    found = []
    for fm in re.finditer(r'<([A-Za-z][^<>\n]{1,60})>', section):
        tag = fm.group(1).strip()
        if tag and tag.lower() not in _PLACEHOLDER_TAGS and tag not in found:
            found.append(tag)
    return found[:5]

# ─── notes sections (Quotes / My Thoughts / Sense / Tags) ─────────────────────
def _note_section_pattern(header):
    return re.compile(rf'^##[ \t]*{re.escape(header)}[ \t]*\n(.*?)(?=\n##[ \t]|\Z)', re.DOTALL | re.MULTILINE)

def parse_note_sections(raw_md):
    def extract(header):
        m = _note_section_pattern(header).search(raw_md)
        return m.group(1).strip() if m else ''
    def extract_list(header):
        raw = extract(header)
        return [t.strip() for t in re.split(r'[,\n]', raw) if t.strip()]
    return {
        'quotes':   extract('Quotes'),
        'thoughts': extract('My Thoughts'),
        'apply':    extract('Sense'),
        'tags':     extract_list('Tags'),
        'abstract': extract('Abstract'),
        'venue':    extract('Venue'),
        'keywords': extract_list('Keywords'),
    }

def save_note_sections(key, updates):
    """Merge {header: content} into {key}.md, touching only those headers —
    editing Abstract independently from Quotes/Thoughts/Sense/Tags (or vice
    versa) must never clobber the sections it doesn't know about."""
    md_file = BASE_DIR / key / f"{key}.md"
    text = md_file.read_text(encoding='utf-8') if md_file.exists() else ''
    for header, content in updates.items():
        new_block = f"## {header}\n\n{content}\n\n"
        if _note_section_pattern(header).search(text):
            text = _note_section_pattern(header).sub(lambda _: new_block, text, count=1)
        else:
            text = text.rstrip()
            text = (text + "\n\n" if text else "") + new_block
    md_file.write_text(text, encoding='utf-8')

# ─── ratings ──────────────────────────────────────────────────────────────────
def load_ratings():
    if RATINGS_FILE.exists():
        return json.loads(RATINGS_FILE.read_text(encoding='utf-8'))
    return {}

def save_ratings(ratings):
    RATINGS_FILE.write_text(json.dumps(ratings, indent=2, ensure_ascii=False), encoding='utf-8')

def get_rating(key):
    return load_ratings().get(key, 0)

def set_rating(key, value):
    r = load_ratings()
    r[key] = max(0, min(3, int(value)))
    save_ratings(r)

# ─── paper data ───────────────────────────────────────────────────────────────
def get_paper(key):
    entries = parse_bib()
    fields = entries.get(key, {})
    folder = BASE_DIR / key

    venue_full  = fields.get('booktitle') or fields.get('journal', '')
    year        = fields.get('year', '')

    raw_kw       = fields.get('keywords', '')
    bib_keywords = [k.strip() for k in re.split(r'[,;]', raw_kw) if k.strip()] if raw_kw else []

    named = re.compile(rf'^{re.escape(key)}_\d+\.(png|jpg|jpeg)$', re.I)
    screenshots = sorted(
        f.name for f in folder.iterdir() if named.match(f.name)
    ) if folder.exists() else []

    notes_raw = (folder / f"{key}.md").read_text('utf-8') if (folder / f"{key}.md").exists() else ''
    sections  = parse_note_sections(notes_raw)

    venue_short_auto = make_venue_short(venue_full, year)
    venue_short = sections['venue'] or venue_short_auto
    keywords    = sections['keywords'] if sections['keywords'] else bib_keywords

    ai_raw = (folder / f"{key}_ai.md").read_text('utf-8') if (folder / f"{key}_ai.md").exists() else ''

    authors = fields.get('author', '')
    authors = re.sub(r'\{\\[a-zA-Z]+\s*([a-zA-Z])\}', r'\1', authors)
    authors = re.sub(r'\\([a-zA-Z])', r'\1', authors)

    order = bib_order()
    add_order = order.index(key) if key in order else 9999
    manual_order = manual_order_map().get(key, 100000 + add_order)

    return {
        "key":          key,
        "title":        fields.get('title', key),
        "authors":      authors,
        "year":         int(year) if str(year).isdigit() else year,
        "venue_short":      venue_short,
        "venue_short_auto": venue_short_auto,
        "venue_full":   venue_full,
        "doi":          fields.get('doi', ''),
        "abstract":     fields.get('abstract', ''),
        "abstract_hl":  sections['abstract'] or fields.get('abstract', ''),
        "keywords":       keywords,
        "keywords_bib":   bib_keywords,
        "affiliations": parse_affiliations(key),
        "quotes":       sections['quotes'],
        "thoughts":     sections['thoughts'],
        "apply":        sections['apply'],
        "tags":         sections['tags'],
        "ai":           ai_raw,
        "screenshots":  screenshots,
        "has_pdf":      (folder / f"{key}.pdf").exists(),
        "rating":       get_rating(key),
        "add_order":    add_order,
        "manual_order": manual_order,
    }

def all_papers():
    # The selected bib can hold candidate entries you haven't onboarded yet — a
    # paper only appears in the library (and the deployed site) once it has a
    # folder (created by `sync`/`new`). Deleting the folder un-publishes it
    # without touching the read-only bib.
    return [get_paper(k) for k in parse_bib() if (BASE_DIR / k).is_dir()]

def get_layout():
    if LAYOUT_FILE.exists():
        return normalize_layout(json.loads(LAYOUT_FILE.read_text()))
    return normalize_layout({})

def save_layout(data):
    LAYOUT_FILE.write_text(json.dumps(normalize_layout(data), indent=2), encoding='utf-8')


def get_active_bib_name():
    return get_layout().get("active_bib") or default_bib_name()


def set_active_bib_name(name):
    data = get_layout()
    data["active_bib"] = name if name in available_bib_files() else default_bib_name()
    save_layout(data)

def get_master_notes():
    path = master_notes_path()
    return path.read_text(encoding='utf-8') if path.exists() else ''

def save_master_notes(content):
    path = master_notes_path()
    path.write_text(content, encoding='utf-8')

def manual_order_map():
    layout = get_layout()
    orders = layout.get("orders") or {}
    order = orders.get(layout.get("active_bib"), []) or []
    return {k: i for i, k in enumerate(order)}


# ─── CSS ──────────────────────────────────────────────────────────────────────
NEW_CSS = """
[hidden] { display: none !important; }
@import url('https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,600;1,400&family=Inter:wght@400;500;600&display=swap');

:root {
  --bg:#f7f5f1; --bg2:#eeece6; --sidebar:#151827; --sidebar2:#1e2238;
  --ink:#1c1e2b; --ink2:#5a5d72; --border:#d8d5ce; --s-border:#2a2e42;
  --s-ink:#c8cce0; --s-ink2:#6b7094; --accent:#4f63d2; --accent2:#3a4db8;
  --tag-bg:#e8e5de; --star:#f5a623; color-scheme:light;
}
[data-theme="dark"] {
  --bg:#13141a; --bg2:#1a1b24; --ink:#e0e2f0; --ink2:#8085a8;
  --border:#2a2e42; --tag-bg:#22253a; color-scheme:dark;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
html,body{height:100%;overflow:hidden;font-family:'Inter',sans-serif;background:var(--bg);color:var(--ink);}

#shell{display:grid;grid-template-columns:272px 1fr;grid-template-rows:100vh;height:100vh;}
#shell{grid-template-rows:100dvh;height:100dvh;}
#shell.has-shots{grid-template-columns:272px 1fr 6px var(--shots-w, 220px);}

.shots-resizer{cursor:col-resize;position:relative;background:transparent;}
.shots-resizer::after{content:'';position:absolute;top:0;bottom:0;left:2px;width:2px;background:var(--border);}
.shots-resizer:hover::after,.shots-resizer.dragging::after{background:var(--accent);}

#sidebar{background:var(--sidebar);color:var(--s-ink);display:flex;flex-direction:column;overflow:hidden;border-right:1px solid var(--s-border);}
.sb-head{padding:18px 16px 10px;border-bottom:1px solid var(--s-border);flex-shrink:0;}
.sb-wordmark{font-size:10px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--s-ink2);margin-bottom:4px;}
.sb-title{font-family:'Spectral',serif;font-size:16px;font-weight:600;color:#e8eaf6;margin-bottom:10px;}
#search{width:100%;background:var(--sidebar2);border:1px solid var(--s-border);border-radius:6px;color:var(--s-ink);font-size:12px;padding:6px 10px;outline:none;}
#search::placeholder{color:var(--s-ink2);}

.bib-switcher{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:11px;color:var(--s-ink2);}
.bib-switcher label{flex-shrink:0;text-transform:uppercase;letter-spacing:.08em;font-weight:600;}
.bib-select{flex:1;min-width:0;background:var(--sidebar2);border:1px solid var(--s-border);border-radius:6px;color:var(--s-ink);font-size:11px;padding:5px 8px;outline:none;}
.bib-select:focus,.bib-browse:hover{border-color:var(--accent);}
.bib-browse{background:var(--sidebar2);border:1px solid var(--s-border);border-radius:6px;color:var(--s-ink);font-size:11px;padding:5px 8px;cursor:pointer;white-space:nowrap;}

.master-btn{width:100%;text-align:left;background:var(--sidebar2);border:1px solid var(--s-border);border-radius:6px;color:var(--s-ink);font-size:12px;font-weight:500;padding:8px 10px;margin-top:8px;cursor:pointer;display:flex;align-items:center;gap:6px;}
.master-btn:hover{border-color:var(--accent);}
.master-btn.active{background:#1e2a50;border-color:var(--accent);color:#fff;}
.master-btn.drop-target{border-color:var(--accent);border-style:dashed;}

.filter-toggle-btn{width:100%;text-align:left;background:none;border:none;color:var(--s-ink2);font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:6px;border-bottom:1px solid var(--s-border);}
.filter-toggle-btn:hover{color:var(--s-ink);}
.filter-arrow{display:inline-block;transition:transform .2s;}
.filter-toggle-btn.open .filter-arrow{transform:rotate(90deg);}

#filter-panel{border-bottom:1px solid var(--s-border);flex-shrink:0;overflow:hidden;max-height:0;transition:max-height .25s ease;}
#filter-panel.open{max-height:400px;}

.sb-sort{display:flex;gap:4px;flex-wrap:wrap;padding:10px 16px 8px;}
.sort-btn{background:none;border:1px solid var(--s-border);border-radius:4px;color:var(--s-ink2);font-size:11px;padding:3px 7px;cursor:pointer;}
.sort-btn.on{background:var(--accent);border-color:var(--accent);color:#fff;}

.filter-group{padding:6px 16px;}
.filter-label{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--s-ink2);margin-bottom:4px;}
.chip-row{display:flex;flex-wrap:wrap;gap:4px;}
.fchip{font-size:11px;padding:2px 8px;border-radius:12px;background:var(--sidebar2);color:var(--s-ink2);cursor:pointer;border:1px solid var(--s-border);}
.fchip:hover,.fchip.on{background:var(--accent);color:#fff;border-color:var(--accent);}

.active-filters{padding:0 16px;display:flex;flex-wrap:wrap;gap:4px;}
.active-filters.visible{padding:6px 16px;}
.af-chip{font-size:11px;background:#3a4060;color:#c0c4e0;padding:2px 6px;border-radius:10px;display:flex;align-items:center;gap:4px;}
.af-chip button{background:none;border:none;color:inherit;cursor:pointer;font-size:12px;line-height:1;}

.sb-count{font-size:10px;color:var(--s-ink2);padding:4px 16px 2px;flex-shrink:0;}

#paper-list{list-style:none;overflow-y:auto;flex:1;padding:6px 0 16px;}
#paper-list::-webkit-scrollbar{width:4px;}
#paper-list::-webkit-scrollbar-thumb{background:var(--s-border);border-radius:2px;}
.pl-item{padding:10px 16px;cursor:pointer;border-bottom:1px solid var(--s-border);transition:background .12s;outline:none;}
.pl-item:hover{background:var(--sidebar2);}
.pl-item.active{background:#1e2a50;border-left:3px solid var(--accent);}
.pl-item:focus{box-shadow:inset 0 0 0 2px var(--accent);}
.pl-item[draggable="true"]{cursor:grab;}
.pl-item.drag-over{border-top:2px solid var(--accent);}
.pl-meta{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;}
.pl-year{font-size:10px;color:var(--s-ink2);}
.pl-venue-tag{font-size:10px;background:var(--sidebar2);border:1px solid var(--s-border);padding:1px 6px;border-radius:8px;color:var(--s-ink2);}
.pl-title{font-size:12px;color:#e0e2f0;font-weight:500;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.pl-authors{font-size:10px;color:var(--s-ink2);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.pl-stars{font-size:10px;color:var(--star);margin-top:2px;}
.pl-empty{padding:20px 16px;color:var(--s-ink2);font-size:12px;text-align:center;}

#main{overflow:hidden;display:flex;flex-direction:column;background:var(--bg2);padding:24px;}
#welcome{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;text-align:center;padding:40px;}
#welcome svg{opacity:.2;}
#welcome h2{font-family:'Spectral',serif;font-size:22px;color:var(--ink);opacity:.45;}
#welcome p{font-size:13px;max-width:260px;line-height:1.6;color:var(--ink2);}
#paper-view{flex:1;overflow-y:auto;padding:32px 40px 60px;position:relative;width:100%;background:var(--bg);border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.08),0 8px 24px rgba(0,0,0,.06);}
#paper-view::-webkit-scrollbar{width:5px;}
#paper-view::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
.slide-counter{position:absolute;top:14px;right:16px;font-size:11px;color:var(--ink2);background:var(--tag-bg);padding:2px 9px;border-radius:10px;}

.pv-eyebrow{font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin-bottom:8px;}
.pv-title{font-family:'Spectral',serif;font-size:24px;font-weight:600;line-height:1.3;margin-bottom:12px;}
.pv-meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;align-items:center;}
.pill{font-size:12px;background:var(--tag-bg);border-radius:6px;padding:3px 10px;color:var(--ink2);}
a.pill{color:var(--accent);text-decoration:none;}
a.pill:hover{text-decoration:underline;}

.pv-rating{display:flex;align-items:center;gap:4px;margin-bottom:12px;}
.star-btn{background:none;border:none;cursor:pointer;font-size:20px;padding:0 1px;color:#ccc;transition:color .1s;line-height:1;}
.star-btn.on{color:var(--star);}
.star-btn:hover{color:var(--star);}

.aff-row{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}
.aff-tag{font-size:11px;background:#e8f0fe;color:#3050a0;border-radius:6px;padding:2px 8px;}
[data-theme="dark"] .aff-tag{background:#1e2a50;color:#7090d0;}
.kw-row{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px;}
.kw{font-size:11px;background:var(--tag-bg);color:var(--ink2);border-radius:10px;padding:2px 8px;}
.tag-row{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px;}
.mytag{font-size:11px;background:transparent;color:var(--accent);border:1px solid var(--accent);border-radius:10px;padding:1px 8px;}
.divider{border:none;border-top:1px solid var(--border);margin:14px 0;}

.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin-bottom:16px;}
.tab{background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;padding:7px 14px;font-size:13px;color:var(--ink2);margin-bottom:-1px;}
.tab.on{color:var(--accent);border-bottom-color:var(--accent);font-weight:500;}
.tab-pane{display:none;}
.tab-pane.on{display:block;}

.prose{font-size:14px;line-height:1.7;color:var(--ink);}
.prose h2{font-family:'Spectral',serif;font-size:18px;margin:20px 0 8px;}
.prose h3{font-size:14px;font-weight:600;margin:16px 0 6px;}
.prose p{margin-bottom:10px;}
.md-gap{height:1.4em;}
.prose ul{padding-left:20px;margin-bottom:10px;}
.prose li{margin-bottom:4px;}
.prose code{background:var(--tag-bg);padding:1px 5px;border-radius:3px;font-size:12px;}
.prose img{max-width:100%;border-radius:6px;margin:8px 0;cursor:zoom-in;}
.prose strong{font-weight:600;}
.prose hr{border:none;border-top:1px solid var(--border);margin:16px 0;}
.empty-note{color:var(--ink2);font-size:13px;padding:20px 0;}
.empty-note code{background:var(--tag-bg);padding:2px 6px;border-radius:3px;}
.empty-note-inline{color:var(--ink2);font-size:13px;opacity:.6;margin-bottom:10px;}
mark.hl{background:#fbc4c4;color:#5c1414;padding:0 2px;border-radius:2px;}
[data-theme="dark"] mark.hl{background:#6b2323;color:#ffd7d7;}

.cite-pill{display:inline-block;background:var(--tag-bg);color:var(--accent);border-radius:4px;padding:0 5px;font-size:.92em;font-weight:600;text-decoration:none;cursor:pointer;}
.cite-pill:hover{background:var(--accent);color:#fff;}

.edit-field{margin-bottom:16px;}
.edit-field label{display:block;font-size:12px;font-weight:600;color:var(--ink2);margin-bottom:4px;}
.edit-field .hl-hint{font-weight:400;color:var(--ink2);font-size:11px;}
.editor-ta{width:100%;height:16vh;font-family:monospace;font-size:13px;padding:10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--ink);resize:vertical;}
.editor-ta.drop-target{border-color:var(--accent);border-style:dashed;}

#shots-panel{border-left:1px solid var(--border);overflow-y:auto;background:var(--bg2);padding:12px 8px;display:flex;flex-direction:column;gap:8px;}
#shots-panel::-webkit-scrollbar{width:4px;}
#shots-panel::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}
.shot-card img{width:100%;border-radius:6px;cursor:zoom-in;border:1px solid var(--border);display:block;}
.shot-label{font-size:10px;color:var(--ink2);margin-top:3px;text-align:center;}
.shots-header{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--ink2);margin-bottom:4px;text-align:center;}

#theme-btn{position:fixed;bottom:16px;right:16px;background:var(--bg2);border:1px solid var(--border);border-radius:50%;width:32px;height:32px;cursor:pointer;font-size:15px;color:var(--ink2);z-index:10;}

#bib-warning{position:fixed;top:0;left:0;right:0;z-index:100;background:#fef3c7;color:#78350f;font-size:12px;padding:8px 16px;border-bottom:1px solid #f59e0b;display:flex;align-items:center;gap:10px;}
[data-theme="dark"] #bib-warning{background:#4a3a0a;color:#fde68a;border-bottom-color:#92700a;}
#bib-warning ul{margin:0;padding-left:18px;flex:1;}
#bib-warning button{background:none;border:1px solid currentColor;border-radius:4px;color:inherit;cursor:pointer;font-size:11px;padding:2px 8px;flex-shrink:0;}

.lightbox{position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:999;display:flex;align-items:center;justify-content:center;cursor:zoom-out;}
.lightbox img{max-width:90vw;max-height:90vh;border-radius:8px;}

@media(max-width:700px){
  #shell,#shell.has-shots{grid-template-columns:1fr;grid-template-rows:38vh 1fr;grid-template-rows:38dvh 1fr;}
  #sidebar{height:auto;}
  #shots-panel,.shots-resizer{display:none;}
  #main{padding:0;}
  #paper-view{padding:18px 18px 40px;max-width:100%;margin:0;border-radius:0;box-shadow:none;-webkit-overflow-scrolling:touch;}
  #paper-list{-webkit-overflow-scrolling:touch;}

  /* Bigger tap targets + 16px inputs so iOS Safari doesn't zoom in on focus */
  #search,.editor-ta,.master-btn{font-size:16px;}
  .master-btn{padding:12px 10px;}
  .sort-btn{padding:7px 12px;font-size:13px;}
  .fchip{padding:6px 12px;font-size:13px;}
  .tab{padding:11px 14px;font-size:14px;touch-action:manipulation;}
  .star-btn{padding:6px 4px;font-size:24px;touch-action:manipulation;}
  .pl-item{padding:13px 16px;touch-action:manipulation;}
  #theme-btn{width:40px;height:40px;font-size:17px;}
  .filter-toggle-btn{padding:11px 16px;}
  button{touch-action:manipulation;}
}
"""


# ─── HTML body ────────────────────────────────────────────────────────────────
NEW_HTML_BODY = """
<div id="bib-warning" hidden><ul id="bib-warning-list"></ul><button onclick="document.getElementById('bib-warning').hidden=true">Dismiss</button></div>
<div id="shell">
  <aside id="sidebar">
    <div class="sb-head">
      <div class="sb-wordmark">Research Library</div>
      <div class="sb-title">Paper Collection</div>
      <input id="search" type="search" placeholder="Search titles, authors, keywords..."
             oninput="Q.query=this.value; renderList()" autocomplete="off">
      <div class="bib-switcher">
        <label for="bib-select">Bib</label>
        <select id="bib-select" class="bib-select" onchange="switchBib(this.value)"></select>
        <button type="button" class="bib-browse" onclick="document.getElementById('bib-file').click()">Browse</button>
        <input id="bib-file" type="file" accept=".bib" hidden onchange="chooseBibFile(this.files && this.files[0])">
      </div>
      <button id="master-notes-btn" class="master-btn" onclick="openMaster()">&#x1f4dd; Master Notes</button>
    </div>
    <button class="filter-toggle-btn" id="filter-toggle" onclick="toggleFilters()">
      <span class="filter-arrow">&#x25B6;</span>&nbsp; Sort &amp; Filter
    </button>
    <div id="filter-panel">
      <div class="sb-sort">
        <button class="sort-btn on" data-s="added"     onclick="setSort(this,'added')">Added</button>
        <button class="sort-btn"    data-s="year_desc" onclick="setSort(this,'year_desc')">Year &#x2193;</button>
        <button class="sort-btn"    data-s="year_asc"  onclick="setSort(this,'year_asc')">Year &#x2191;</button>
        <button class="sort-btn"    data-s="title"     onclick="setSort(this,'title')">A&#x2013;Z</button>
        <button class="sort-btn"    data-s="rating"    onclick="setSort(this,'rating')">&#x2605; Stars</button>
        <button class="sort-btn"    data-s="custom"    onclick="setSort(this,'custom')">Custom</button>
      </div>
      <div class="filter-group">
        <div class="filter-label">Venue</div>
        <div class="chip-row" id="venue-chips"></div>
      </div>
      <div class="filter-group">
        <div class="filter-label">My Tags</div>
        <div class="chip-row" id="tag-chips"></div>
      </div>
    </div>
    <div class="active-filters" id="active-filters"></div>
    <div class="sb-count" id="sb-count"></div>
    <ul id="paper-list"></ul>
  </aside>
  <main id="main">
    <div id="welcome">
      <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
      </svg>
      <h2>Select a paper</h2>
      <p>Use the sidebar to browse, sort, and filter your collection.</p>
    </div>
    <div id="paper-view" hidden></div>
  </main>
  <div id="shots-resizer" class="shots-resizer" hidden></div>
  <div id="shots-panel" hidden></div>
</div>
<button id="theme-btn" onclick="toggleTheme()">&#x25D0;</button>
"""


# ─── Shared JS (raw string – no f-string) ─────────────────────────────────────
NEW_JS_COMMON = r"""
const Q = { query: '', sort: 'added', venues: new Set(), tags: new Set() };
let activeKey = null;
let activeTab = 'notes';
let lastPaperKey = null;
let PAPERS = [];
let customOrder = [];
let EDIT_MODE = false;
let BIBS = [];
let ACTIVE_BIB = '';

function initCustomOrder() {
  customOrder = [...PAPERS].sort((a, b) => (a.manual_order || 0) - (b.manual_order || 0)).map(p => p.key);
}

function populateBibSwitcher(bibs, activeBib) {
  BIBS = bibs || [];
  ACTIVE_BIB = activeBib || ACTIVE_BIB || '';
  const select = document.getElementById('bib-select');
  if (!select) return;
  select.innerHTML = BIBS.map(b => '<option value="' + escHtml(b) + '">' + escHtml(b) + '</option>').join('');
  if (ACTIVE_BIB && BIBS.includes(ACTIVE_BIB)) select.value = ACTIVE_BIB;
}

async function loadBibSwitcher() {
  const resp = await fetch('/api/bibs').catch(() => null);
  if (!resp) return;
  const data = await resp.json();
  populateBibSwitcher(data.bibs || [], data.active_bib || '');
}

async function switchBib(name) {
  if (!name || name === ACTIVE_BIB) return;
  const resp = await fetch('/api/layout', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active_bib: name })
  }).catch(() => null);
  if (!resp) return;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.ok === false) return;
  ACTIVE_BIB = name;
  await loadPapers();
  await openMaster();
}

function chooseBibFile(file) {
  if (!file || !file.name) return;
  switchBib(file.name);
  const picker = document.getElementById('bib-file');
  if (picker) picker.value = '';
}

function reorderCustom(draggedKey, targetKey) {
  const from = customOrder.indexOf(draggedKey);
  const to = customOrder.indexOf(targetKey);
  if (from < 0 || to < 0 || from === to) return;
  customOrder.splice(from, 1);
  customOrder.splice(to, 0, draggedKey);
}

function saveCustomOrder() {
  fetch('/api/layout', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order: customOrder, view: 'list' })
  }).catch(() => {});
}

function stripYear(v) { return v.replace(/\s*['`]?\d{2,4}$/, '').trim(); }

function filtered() {
  let list = [...PAPERS];
  const q = Q.query.toLowerCase().trim();
  if (q) list = list.filter(p =>
    p.title.toLowerCase().includes(q) ||
    p.authors.toLowerCase().includes(q) ||
    (p.keywords||[]).some(k => k.toLowerCase().includes(q)) ||
    (p.venue_short||'').toLowerCase().includes(q) ||
    (p.venue_full||'').toLowerCase().includes(q) ||
    (p.affiliations||[]).some(a => a.toLowerCase().includes(q)) ||
    String(p.year).includes(q)
  );
  if (Q.venues.size) list = list.filter(p => Q.venues.has(stripYear(p.venue_short||'')));
  if (Q.tags.size)   list = list.filter(p => (p.tags||[]).some(t => Q.tags.has(t)));
  const cmp = {
    added:     (a,b) => (a.add_order||0) - (b.add_order||0),
    year_desc: (a,b) => b.year - a.year,
    year_asc:  (a,b) => a.year - b.year,
    title:     (a,b) => a.title.localeCompare(b.title),
    venue:     (a,b) => (a.venue_short||'').localeCompare(b.venue_short||''),
    rating:    (a,b) => (b.rating||0) - (a.rating||0),
    custom:    (a,b) => customOrder.indexOf(a.key) - customOrder.indexOf(b.key),
  };
  list.sort(cmp[Q.sort] || cmp.added);
  return list;
}

function setSort(btn, key) {
  Q.sort = key;
  document.querySelectorAll('.sort-btn').forEach(b => b.classList.toggle('on', b.dataset.s === key));
  renderList();
}

function toggleFilters() {
  document.getElementById('filter-panel').classList.toggle('open');
  document.getElementById('filter-toggle').classList.toggle('open');
}

function toggleVenue(v) { Q.venues.has(v) ? Q.venues.delete(v) : Q.venues.add(v); renderList(); }
function toggleTag(t)   { Q.tags.has(t)   ? Q.tags.delete(t)   : Q.tags.add(t);   renderList(); }

function starsStr(n) {
  let s = '';
  for (let i = 1; i <= 3; i++) s += i <= n ? '●' : '○';
  return s;
}

function renderList() {
  const list = filtered();
  const ul = document.getElementById('paper-list');
  if (!list.length) {
    ul.innerHTML = '<li class="pl-empty">No papers match.</li>';
  } else {
    ul.innerHTML = list.map(p =>
      '<li class="pl-item' + (activeKey===p.key?' active':'') + '" tabindex="0" data-key="' + p.key + '" onclick="openPaper(\'' + p.key + '\')">' +
        '<div class="pl-meta">' +
          '<span class="pl-year">' + p.year + '</span>' +
          '<span class="pl-venue-tag">' + stripYear(p.venue_short||'') + '</span>' +
        '</div>' +
        '<div class="pl-title">' + escHtml(p.title) + '</div>' +
        '<div class="pl-authors">' + escHtml(p.authors||'') + '</div>' +
        '<div class="pl-stars">' + starsStr(p.rating||0) + '</div>' +
      '</li>'
    ).join('');
    if (EDIT_MODE) {
      ul.querySelectorAll('.pl-item').forEach(li => {
        li.draggable = true;
        li.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', li.dataset.key); });
        li.addEventListener('dragover', e => { e.preventDefault(); li.classList.add('drag-over'); });
        li.addEventListener('dragleave', () => li.classList.remove('drag-over'));
        li.addEventListener('drop', e => {
          e.preventDefault();
          li.classList.remove('drag-over');
          const draggedKey = e.dataTransfer.getData('text/plain');
          if (draggedKey === li.dataset.key) return;
          reorderCustom(draggedKey, li.dataset.key);
          if (Q.sort !== 'custom') {
            Q.sort = 'custom';
            document.querySelectorAll('.sort-btn').forEach(b => b.classList.toggle('on', b.dataset.s === 'custom'));
          }
          renderList();
          saveCustomOrder();
        });
      });
    }
  }
  document.getElementById('sb-count').textContent = list.length + ' of ' + PAPERS.length + ' papers';

  const af = document.getElementById('active-filters');
  af.innerHTML = '';
  const mkChip = (label, rmFn) => {
    const span = document.createElement('span'); span.className = 'af-chip';
    span.textContent = label + ' ';
    const btn = document.createElement('button'); btn.textContent = '\xd7';
    btn.addEventListener('click', rmFn);
    span.appendChild(btn); af.appendChild(span);
  };
  Q.venues.forEach(v => mkChip(v, () => { Q.venues.delete(v); renderList(); }));
  Q.tags.forEach(t => mkChip('#'+t, () => { Q.tags.delete(t); renderList(); }));
  af.className = 'active-filters' + (af.children.length ? ' visible' : '');
}

function buildFilterChips() {
  const baseVenues = [...new Set(PAPERS.map(p => stripYear(p.venue_short||'')))].sort();
  const vcRow = document.getElementById('venue-chips');
  vcRow.innerHTML = '';
  baseVenues.forEach(v => {
    const el = document.createElement('span');
    el.className = 'fchip'; el.dataset.v = v; el.textContent = v;
    el.addEventListener('click', () => toggleVenue(v));
    vcRow.appendChild(el);
  });
  const tagFreq = {};
  PAPERS.forEach(p => (p.tags||[]).forEach(t => { tagFreq[t] = (tagFreq[t]||0)+1; }));
  const topTags = Object.entries(tagFreq).sort((a,b) => b[1]-a[1]||a[0].localeCompare(b[0])).slice(0,16);
  const tagRow = document.getElementById('tag-chips');
  tagRow.innerHTML = '';
  topTags.forEach(([t,n]) => {
    const el = document.createElement('span');
    el.className = 'fchip'; el.dataset.t = t;
    el.innerHTML = escHtml(t) + (n>1 ? ' <small style="opacity:.6">'+n+'</small>' : '');
    el.addEventListener('click', () => toggleTag(t));
    tagRow.appendChild(el);
  });
}

function switchTab(btn, id) {
  btn.closest('.tabs').querySelectorAll('.tab').forEach(t => t.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('on'));
  document.getElementById('tab-'+id).classList.add('on');
  activeTab = id;
}

function activateTab(id) {
  const tabsWrap = document.querySelector('.tabs');
  if (!tabsWrap) return;
  const btn = tabsWrap.querySelector('[data-tab="'+id+'"]') || tabsWrap.querySelector('.tab');
  if (btn) switchTab(btn, btn.dataset.tab);
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function md(src) {
  if (!src) return '';
  src = src.replace(/<!--[\s\S]*?-->/g, '');
  src = src.replace(/^#{1,2} (.+)$/gm, '<h2>$1</h2>');
  src = src.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  src = src.replace(/==([\s\S]+?)==/g, '<mark class="hl">$1</mark>');
  src = src.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  src = src.replace(/\*(.+?)\*/g, '<em>$1</em>');
  src = src.replace(/`(.+?)`/g, '<code>$1</code>');
  src = src.replace(/^---+$/gm, '<hr>');
  src = src.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  // Split on blank lines, keeping the separators so that each *extra* blank
  // line (3+ newlines in a row) becomes a visible gap instead of collapsing.
  return src.split(/(\n{2,})/).map(b => {
    if (/^\n{2,}$/.test(b)) return '<div class="md-gap"></div>'.repeat(b.length - 2);
    b = b.trim(); if (!b) return '';
    if (/^<(h[123]|hr|li|ul)/.test(b)) return b.includes('<li>') ? '<ul>'+b+'</ul>' : b;
    return '<p>'+b.replace(/\n/g,' ')+'</p>';
  }).join('\n');
}

function lightbox(src) {
  const d = document.createElement('div');
  d.className = 'lightbox';
  const img = document.createElement('img'); img.src = src;
  d.appendChild(img); d.onclick = () => d.remove(); document.body.appendChild(d);
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('theme', next); } catch(e) {}
}

function renderShots(imgs, keyName, baseUrl) {
  const panel = document.getElementById('shots-panel');
  const shell = document.getElementById('shell');
  const resizer = document.getElementById('shots-resizer');
  if (!imgs || !imgs.length) {
    panel.hidden = true;
    if (resizer) resizer.hidden = true;
    shell.classList.remove('has-shots');
    return;
  }
  panel.hidden = false;
  if (resizer) resizer.hidden = false;
  shell.classList.add('has-shots');
  panel.innerHTML = '<div class="shots-header">Screenshots</div>' +
    imgs.map(function(s, i) {
      const src = baseUrl ? baseUrl + s : 'imgs/' + keyName + '/' + s;
      return '<div class="shot-card"><img src="' + src + '" onclick="lightbox(this.src)" alt="' + escHtml(s) + '">' +
        '<div class="shot-label">' + (i+1) + ' / ' + imgs.length + '</div></div>';
    }).join('');
}

function starsEditHtml(key, rating) {
  let h = '<div class="pv-rating">';
  for (let i = 1; i <= 3; i++) {
    const next = i === rating ? 0 : i; // clicking the active circle clears it back to 0
    h += '<button class="star-btn' + (i<=rating?' on':'') + '" onclick="setRating(\'' + key + '\',' + next + ')" title="' + i + '">' + (i<=rating?'●':'○') + '</button>';
  }
  h += '</div>';
  return h;
}

function sectionsHtml(p, renderer) {
  function block(title, content) {
    if (!content || !content.trim()) return '';
    return '<h3>' + title + '</h3><div class="prose">' + renderer(content) + '</div>';
  }
  return block('Quotes', p.quotes) + block('My Thoughts', p.thoughts) + block('Sense', p.apply);
}

function wireHighlight(ta) {
  if (!ta) return;
  ta.addEventListener('keydown', e => {
    if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'h') return;
    const s = ta.selectionStart, en = ta.selectionEnd;
    if (s === en) return;
    e.preventDefault();
    const val = ta.value;
    const sel = val.slice(s, en);
    let newVal, newStart, newEnd;
    if (sel.startsWith('==') && sel.endsWith('==') && sel.length >= 4) {
      const inner = sel.slice(2, -2);
      newVal = val.slice(0, s) + inner + val.slice(en);
      newStart = s; newEnd = s + inner.length;
    } else {
      newVal = val.slice(0, s) + '==' + sel + '==' + val.slice(en);
      newStart = s; newEnd = s + sel.length + 4;
    }
    ta.value = newVal;
    ta.setSelectionRange(newStart, newEnd);
    ta.dispatchEvent(new Event('input'));
  });
}

function citePill(key) {
  const p = PAPERS.find(function(x){ return x.key === key; });
  if (!p) return null;
  return '<a class="cite-pill" onclick="openPaper(\'' + key + '\')" title="' + escHtml(p.title) + '">[' + key + ']</a>';
}

function renderMasterView(content) {
  if (!content || !content.trim()) return '';
  let html = md(content);
  // LaTeX-style citations, written as ~\cite{key} (or \cite{a, b}) so the
  // notes paste straight into a .tex file. The ~ is LaTeX's non-breaking
  // space, so it renders as a plain space here.
  // The older [key] form still works. One combined pass, so a pill produced
  // for \cite{} isn't re-matched as [key].
  html = html.replace(/~?\\cite\{([^}]+)\}|\[([A-Za-z0-9_]+)\]/g, function(m, keys, single) {
    if (single !== undefined) return citePill(single) || m;
    const pills = keys.split(',').map(function(k){ return k.trim(); }).filter(Boolean)
      .map(function(k){ return citePill(k) || '[' + escHtml(k) + ']'; });
    return (m.charAt(0) === '~' ? ' ' : '') + pills.join(' ');
  });
  return '<div class="prose">' + html + '</div>';
}

function wireCitationDrop(ta) {
  if (!ta) return;
  ta.addEventListener('dragover', e => { e.preventDefault(); ta.classList.add('drop-target'); });
  ta.addEventListener('dragleave', () => ta.classList.remove('drop-target'));
  ta.addEventListener('drop', e => {
    e.preventDefault();
    ta.classList.remove('drop-target');
    const draggedKey = e.dataTransfer.getData('text/plain');
    if (!draggedKey) return;
    const pos = typeof ta.selectionStart === 'number' ? ta.selectionStart : ta.value.length;
    const insert = '~\\cite{' + draggedKey + '}';
    ta.value = ta.value.slice(0, pos) + insert + ta.value.slice(pos);
    const newPos = pos + insert.length;
    ta.focus();
    ta.setSelectionRange(newPos, newPos);
  });
}

function showBibWarnings(warnings) {
  const banner = document.getElementById('bib-warning');
  const list = document.getElementById('bib-warning-list');
  if (!banner || !list || !warnings || !warnings.length) return;
  list.innerHTML = warnings.map(w => '<li>&#x26a0; ' + escHtml(w) + '</li>').join('');
  banner.hidden = false;
}

document.addEventListener('keydown', e => {
  const tag = (document.activeElement && document.activeElement.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;

  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const list = filtered();
    if (!list.length) return;
    let idx = list.findIndex(p => p.key === activeKey);
    if (e.key === 'ArrowDown') idx = idx < 0 ? 0 : Math.min(list.length - 1, idx + 1);
    else idx = idx < 0 ? 0 : Math.max(0, idx - 1);
    e.preventDefault();
    openPaper(list[idx].key);
    const li = document.querySelector('.pl-item[data-key="' + list[idx].key + '"]');
    if (li) { li.focus(); if (li.scrollIntoView) li.scrollIntoView({ block: 'nearest' }); }
    return;
  }

  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    const tabsWrap = document.querySelector('.tabs');
    if (!tabsWrap) return;
    const btns = [...tabsWrap.querySelectorAll('.tab')];
    if (!btns.length) return;
    let idx = btns.findIndex(b => b.classList.contains('on'));
    if (idx < 0) idx = 0;
    idx = e.key === 'ArrowRight' ? Math.min(btns.length - 1, idx + 1) : Math.max(0, idx - 1);
    e.preventDefault();
    switchTab(btns[idx], btns[idx].dataset.tab);
    return;
  }

  if (e.key === 'Escape') {
    if (!activeKey) return;
    e.preventDefault();
    if (activeKey === '__master__') {
      if (lastPaperKey) openPaper(lastPaperKey);
    } else {
      openMaster();
    }
  }
});

function applyShotsWidth(w) {
  const shell = document.getElementById('shell');
  if (shell) shell.style.setProperty('--shots-w', w + 'px');
}

function initShotsResizer() {
  const resizer = document.getElementById('shots-resizer');
  if (!resizer) return;
  let saved = null;
  try { saved = localStorage.getItem('shotsWidth'); } catch (e) {}
  if (saved) applyShotsWidth(parseInt(saved, 10));

  resizer.addEventListener('mousedown', e => {
    e.preventDefault();
    const panel = document.getElementById('shots-panel');
    const startX = e.clientX;
    const startWidth = panel.getBoundingClientRect().width;
    resizer.classList.add('dragging');
    let currentWidth = startWidth;
    function onMove(ev) {
      const delta = startX - ev.clientX; // dragging left = wider panel
      currentWidth = Math.max(160, Math.min(560, startWidth + delta));
      applyShotsWidth(currentWidth);
    }
    function onUp() {
      resizer.classList.remove('dragging');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      try { localStorage.setItem('shotsWidth', String(Math.round(currentWidth))); } catch (e) {}
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

try {
  const t = localStorage.getItem('theme');
  if (t) document.documentElement.setAttribute('data-theme', t);
} catch(e) {}
"""


# ─── Server JS ────────────────────────────────────────────────────────────────
NEW_JS_SERVER = NEW_JS_COMMON + r"""
EDIT_MODE = true;

async function loadPapers() {
  await loadBibSwitcher();
  const resp = await fetch('/api/papers').catch(() => null);
  if (!resp) return;
  PAPERS = await resp.json();
  initCustomOrder();
  buildFilterChips();
  renderList();
  initShotsResizer();
  fetch('/api/warnings').then(r => r.json()).then(d => showBibWarnings(d.warnings)).catch(() => {});
}

function mdWithImages(src, key) {
  return md(src).replace(/<img src="([^"]+)"/g, function(_, href) {
    if (/^https?:\/\//.test(href)) return '<img src="'+href+'"';
    return '<img src="/file/'+key+'/'+href+'"';
  });
}

async function openPaper(key) {
  activeKey = key;
  lastPaperKey = key;
  const mb = document.getElementById('master-notes-btn');
  if (mb) mb.classList.remove('active');
  const resp = await fetch('/api/paper/' + key);
  const p = await resp.json();
  const idx = PAPERS.findIndex(x => x.key === key);
  if (idx >= 0) PAPERS[idx] = p;
  renderList();
  document.getElementById('welcome').hidden = true;
  const view = document.getElementById('paper-view');
  view.hidden = false;

  renderShots(p.screenshots || [], key, '/file/'+key+'/');

  const list = filtered();
  const posIdx = list.findIndex(x => x.key === key);
  const counterHtml = '<div class="slide-counter">' + (posIdx>=0 ? (posIdx+1)+' / '+list.length : '') + '</div>';

  const affHtml = (p.affiliations||[]).length
    ? '<div class="aff-row">'+p.affiliations.map(a=>'<span class="aff-tag">&#x1f3db; '+escHtml(a)+'</span>').join('')+'</div>' : '';
  const kwHtml = (p.keywords||[]).length
    ? '<div class="kw-row">'+p.keywords.map(k=>'<span class="kw">'+escHtml(k)+'</span>').join('')+'</div>' : '';
  const tagsHtml = (p.tags||[]).length
    ? '<div class="tag-row">'+p.tags.map(t=>'<span class="mytag">#'+escHtml(t)+'</span>').join('')+'</div>' : '';
  const doiHtml = p.doi ? '<a class="pill" href="https://doi.org/'+p.doi+'" target="_blank">&#x1f517; DOI</a>' : '';
  const pdfHtml = p.has_pdf ? '<a class="pill" href="/file/'+key+'/'+key+'.pdf" target="_blank">&#x1f4c4; PDF</a>' : '';
  const rating = p.rating || 0;

  view.innerHTML =
    counterHtml+
    '<div class="pv-eyebrow">'+escHtml(p.venue_full||p.venue_short||'')+'</div>'+
    '<h1 class="pv-title">'+escHtml(p.title)+'</h1>'+
    '<div class="pv-meta">'+
      '<span class="pill">&#x1f464; '+escHtml(p.authors)+'</span>'+
      '<span class="pill">&#x1f4c5; '+p.year+'</span>'+
      doiHtml+pdfHtml+
    '</div>'+
    starsEditHtml(key, rating)+
    affHtml+kwHtml+tagsHtml+
    '<hr class="divider">'+
    '<div class="tabs">'+
      '<button class="tab on" data-tab="notes" onclick="switchTab(this,\'notes\')">Notes</button>'+
      '<button class="tab" data-tab="abstract" onclick="switchTab(this,\'abstract\')">Abstract</button>'+
      '<button class="tab" data-tab="ai" onclick="switchTab(this,\'ai\')">AI Analysis</button>'+
      '<button class="tab" data-tab="edit" onclick="switchTab(this,\'edit\')">&#x270F; Edit</button>'+
    '</div>'+
    '<div id="tab-notes" class="tab-pane on">'+sectionsHtml(p, s => mdWithImages(s, key))+'</div>'+
    '<div id="tab-abstract" class="tab-pane">'+
      '<div style="display:flex;justify-content:flex-end;margin-bottom:8px">'+
        '<button onclick="toggleAbstractEdit()" style="background:none;border:1px solid var(--border);border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;color:var(--ink2)">&#x270F; Edit</button>'+
      '</div>'+
      '<div id="abstract-view"><div class="prose">'+md(p.abstract_hl||'')+'</div></div>'+
      '<div id="abstract-edit" hidden>'+
        '<textarea id="abstract-editor" class="editor-ta" style="height:40vh">'+escHtml(p.abstract_hl||'')+'</textarea>'+
        '<div style="display:flex;gap:8px;margin-top:8px">'+
          '<button onclick="saveAbstract(\''+key+'\')" style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:7px 16px;cursor:pointer;font-size:13px">Save</button>'+
          '<span id="abstract-save-status" style="font-size:12px;color:var(--ink2);align-self:center"></span>'+
        '</div>'+
      '</div>'+
    '</div>'+
    '<div id="tab-ai" class="tab-pane">'+
      '<div style="display:flex;justify-content:flex-end;margin-bottom:8px">'+
        '<button onclick="toggleAiEdit()" style="background:none;border:1px solid var(--border);border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;color:var(--ink2)">&#x270F; Edit</button>'+
      '</div>'+
      '<div id="ai-view">'+(p.ai ? '<div class="prose">'+mdWithImages(p.ai, key)+'</div>' : '')+
      '</div>'+
      '<div id="ai-edit" hidden>'+
        '<textarea id="ai-editor" class="editor-ta" style="height:50vh">'+escHtml(p.ai||'')+'</textarea>'+
        '<div style="display:flex;gap:8px;margin-top:8px">'+
          '<button onclick="saveAi(\''+key+'\')" style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:7px 16px;cursor:pointer;font-size:13px">Save</button>'+
          '<span id="ai-save-status" style="font-size:12px;color:var(--ink2);align-self:center"></span>'+
        '</div>'+
      '</div>'+
    '</div>'+
    '<div id="tab-edit" class="tab-pane">'+
      '<div class="edit-field"><label>Quotes <span class="hl-hint">(select text, Cmd/Ctrl+H to highlight)</span></label>'+
        '<textarea id="quotes-editor" class="editor-ta">'+escHtml(p.quotes||'')+'</textarea></div>'+
      '<div class="edit-field"><label>My Thoughts</label>'+
        '<textarea id="thoughts-editor" class="editor-ta">'+escHtml(p.thoughts||'')+'</textarea></div>'+
      '<div class="edit-field"><label>Sense</label>'+
        '<textarea id="apply-editor" class="editor-ta">'+escHtml(p.apply||'')+'</textarea></div>'+
      '<div class="edit-field"><label>Tags <span class="hl-hint">(comma-separated — for grouping into related-work sections later)</span></label>'+
        '<input id="tags-editor" class="editor-ta" style="height:auto;padding:8px 10px" value="'+escHtml((p.tags||[]).join(', '))+'"></div>'+
      '<div class="edit-field"><label>Venue (short) <span class="hl-hint">(overrides the auto-abbreviated "'+escHtml(p.venue_short_auto||'')+'" shown on the slide/sidebar)</span></label>'+
        '<input id="venue-editor" class="editor-ta" style="height:auto;padding:8px 10px" placeholder="'+escHtml(p.venue_short_auto||'')+'" value="'+escHtml(p.venue_short && p.venue_short !== p.venue_short_auto ? p.venue_short : '')+'"></div>'+
      '<div class="edit-field"><label>Keywords <span class="hl-hint">(comma-separated — overrides the bib keywords field; also searchable)</span></label>'+
        '<input id="keywords-editor" class="editor-ta" style="height:auto;padding:8px 10px" placeholder="'+escHtml((p.keywords_bib||[]).join(', '))+'" value="'+escHtml((p.keywords||[]).join(', ') !== (p.keywords_bib||[]).join(', ') ? (p.keywords||[]).join(', ') : '')+'"></div>'+
      '<div style="display:flex;gap:8px">'+
        '<button onclick="saveNotes(\''+key+'\')" style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:7px 16px;cursor:pointer;font-size:13px">Save</button>'+
        '<span id="save-status" style="font-size:12px;color:var(--ink2);align-self:center"></span>'+
      '</div>'+
    '</div>';

  ['quotes-editor','thoughts-editor','apply-editor','ai-editor','abstract-editor'].forEach(id => wireHighlight(document.getElementById(id)));
  activateTab(activeTab);
}

async function saveNotes(key) {
  const quotes   = document.getElementById('quotes-editor').value;
  const thoughts = document.getElementById('thoughts-editor').value;
  const apply    = document.getElementById('apply-editor').value;
  const tags     = document.getElementById('tags-editor').value;
  const venue    = document.getElementById('venue-editor').value;
  const keywords = document.getElementById('keywords-editor').value;
  const resp = await fetch('/api/paper/'+key+'/notes', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({quotes, thoughts, apply, tags, venue, keywords})
  });
  const r = await resp.json();
  if (r.ok) {
    await openPaper(key);
    buildFilterChips();
    const st = document.getElementById('save-status');
    if (st) { st.textContent = '✓ Saved'; setTimeout(() => { st.textContent = ''; }, 2000); }
  } else {
    const st = document.getElementById('save-status');
    if (st) st.textContent = '✗ Error';
  }
}

function toggleAbstractEdit() {
  const view = document.getElementById('abstract-view');
  const edit = document.getElementById('abstract-edit');
  if (!view || !edit) return;
  view.hidden = !view.hidden;
  edit.hidden = !edit.hidden;
}

async function saveAbstract(key) {
  const content = document.getElementById('abstract-editor').value;
  const resp = await fetch('/api/paper/'+key+'/abstract', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content})
  });
  const r = await resp.json();
  if (r.ok) {
    await openPaper(key);
  } else {
    const st = document.getElementById('abstract-save-status');
    if (st) st.textContent = '✗ Error';
  }
}

function toggleAiEdit() {
  const view = document.getElementById('ai-view');
  const edit = document.getElementById('ai-edit');
  if (!view || !edit) return;
  view.hidden = !view.hidden;
  edit.hidden = !edit.hidden;
}

async function saveAi(key) {
  const content = document.getElementById('ai-editor').value;
  const resp = await fetch('/api/paper/'+key+'/ai', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content})
  });
  const r = await resp.json();
  if (r.ok) {
    await openPaper(key);
  } else {
    const st = document.getElementById('ai-save-status');
    if (st) st.textContent = '✗ Error';
  }
}

async function openMaster() {
  activeKey = '__master__';
  renderList();
  const mb = document.getElementById('master-notes-btn');
  if (mb) mb.classList.add('active');
  const select = document.getElementById('bib-select');
  if (select && ACTIVE_BIB && select.value !== ACTIVE_BIB) select.value = ACTIVE_BIB;
  document.getElementById('welcome').hidden = true;
  const view = document.getElementById('paper-view');
  view.hidden = false;
  renderShots([], null, null);

  const resp = await fetch('/api/master');
  const data = await resp.json();
  const content = data.content || '';

  view.innerHTML =
    '<div class="pv-eyebrow">Master Notes <span style="opacity:.6">· ' + escHtml(ACTIVE_BIB || '') + '</span></div>'+ 
    '<hr class="divider">'+
    '<div class="tabs">'+
      '<button class="tab on" data-tab="notes" onclick="switchTab(this,\'notes\')">Notes</button>'+
      '<button class="tab" data-tab="edit" onclick="switchTab(this,\'edit\')">&#x270F; Edit</button>'+
    '</div>'+
    '<div id="tab-notes" class="tab-pane on">'+renderMasterView(content)+'</div>'+
    '<div id="tab-edit" class="tab-pane">'+
      '<div class="edit-field"><label>Scratchpad <span class="hl-hint">(drag a paper here to cite it; select text + Cmd/Ctrl+H to highlight)</span></label>'+
        '<textarea id="master-editor" class="editor-ta" style="height:55vh">'+escHtml(content)+'</textarea></div>'+
      '<div style="display:flex;gap:8px">'+
        '<button onclick="saveMaster()" style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:7px 16px;cursor:pointer;font-size:13px">Save</button>'+
        '<span id="master-save-status" style="font-size:12px;color:var(--ink2);align-self:center"></span>'+
      '</div>'+
    '</div>';

  const ta = document.getElementById('master-editor');
  wireHighlight(ta);
  wireCitationDrop(ta);
  activateTab(activeTab);
}

async function saveMaster() {
  const content = document.getElementById('master-editor').value;
  const resp = await fetch('/api/master', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content})
  });
  const r = await resp.json();
  if (r.ok) {
    await openMaster();
    const st = document.getElementById('master-save-status');
    if (st) { st.textContent = '✓ Saved'; setTimeout(() => { st.textContent = ''; }, 2000); }
  } else {
    const st = document.getElementById('master-save-status');
    if (st) st.textContent = '✗ Error';
  }
}

async function setRating(key, value) {
  await fetch('/api/paper/'+key+'/rating', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({rating: value})
  });
  const idx = PAPERS.findIndex(x => x.key === key);
  if (idx >= 0) PAPERS[idx].rating = value;
  const pv = document.querySelector('.pv-rating');
  if (pv) pv.outerHTML = starsEditHtml(key, value);
  const li = document.querySelector('.pl-item[data-key="'+key+'"] .pl-stars');
  if (li) li.textContent = starsStr(value);
}

loadPapers();
"""


# ─── Static JS template ───────────────────────────────────────────────────────
NEW_JS_STATIC_TPL = NEW_JS_COMMON + """
let MASTER_CONTENT = '';

(function() {
  function init(papers) {
    PAPERS = papers;
    initCustomOrder();
    buildFilterChips();
    renderList();
    initShotsResizer();
    const switcher = document.querySelector('.bib-switcher');
    if (switcher) switcher.remove();
  }
  fetch('papers.json')
    .then(function(r){ return r.json(); })
    .then(init)
    .catch(function() { init(/*PAPERS_JSON*/); });
  fetch('master.json')
    .then(function(r){ return r.json(); })
    .then(function(d){ MASTER_CONTENT = d.content || ''; })
    .catch(function() {});
  fetch('warnings.json')
    .then(function(r){ return r.json(); })
    .then(function(d){ showBibWarnings(d.warnings); })
    .catch(function() {});
})();

function setRating(key, value) { /* read-only in static mode */ }

function openMaster() {
  activeKey = '__master__';
  renderList();
  const mb = document.getElementById('master-notes-btn');
  if (mb) mb.classList.add('active');
  document.getElementById('welcome').hidden = true;
  const view = document.getElementById('paper-view');
  view.hidden = false;
  renderShots([], null, null);

  view.innerHTML =
    '<div class="pv-eyebrow">Master Notes</div>'+
    '<hr class="divider">'+
    '<div class="tabs">'+
      '<button class="tab on" data-tab="notes" onclick="switchTab(this,\\'notes\\')">Notes</button>'+
    '</div>'+
    '<div id="tab-notes" class="tab-pane on">'+renderMasterView(MASTER_CONTENT)+'</div>';
  activateTab(activeTab);
}

function openPaper(key) {
  activeKey = key;
  lastPaperKey = key;
  const mb = document.getElementById('master-notes-btn');
  if (mb) mb.classList.remove('active');
  const p = PAPERS.find(function(x){ return x.key === key; });
  if (!p) return;
  renderList();
  document.getElementById('welcome').hidden = true;
  const view = document.getElementById('paper-view');
  view.hidden = false;

  renderShots(p.imgs || [], key, null);

  const list = filtered();
  const posIdx = list.findIndex(function(x){ return x.key === key; });
  const counterHtml = '<div class="slide-counter">' + (posIdx>=0 ? (posIdx+1)+' / '+list.length : '') + '</div>';

  const affHtml = (p.affiliations||[]).length
    ? '<div class="aff-row">'+p.affiliations.map(function(a){ return '<span class="aff-tag">&#x1f3db; '+escHtml(a)+'</span>'; }).join('')+'</div>' : '';
  const kwHtml = (p.keywords||[]).length
    ? '<div class="kw-row">'+p.keywords.map(function(k){ return '<span class="kw">'+escHtml(k)+'</span>'; }).join('')+'</div>' : '';
  const tagsHtml = (p.tags||[]).length
    ? '<div class="tag-row">'+p.tags.map(function(t){ return '<span class="mytag">#'+escHtml(t)+'</span>'; }).join('')+'</div>' : '';
  const doiHtml = p.doi ? '<a class="pill" href="https://doi.org/'+p.doi+'" target="_blank">&#x1f517; DOI</a>' : '';
  const rating = p.rating || 0;

  const starsHtml2 = starsEditHtml(key, rating);

  view.innerHTML =
    counterHtml+
    '<div class="pv-eyebrow">'+escHtml(p.venue_full||p.venue_short||'')+'</div>'+
    '<h1 class="pv-title">'+escHtml(p.title)+'</h1>'+
    '<div class="pv-meta">'+
      '<span class="pill">&#x1f464; '+escHtml(p.authors)+'</span>'+
      '<span class="pill">&#x1f4c5; '+p.year+'</span>'+
      doiHtml+
    '</div>'+
    starsHtml2+
    affHtml+kwHtml+tagsHtml+
    '<hr class="divider">'+
    '<div class="tabs">'+
      '<button class="tab on" data-tab="notes" onclick="switchTab(this,\\'notes\\')">Notes</button>'+
      '<button class="tab" data-tab="abstract" onclick="switchTab(this,\\'abstract\\')">Abstract</button>'+
      '<button class="tab" data-tab="ai" onclick="switchTab(this,\\'ai\\')">AI Analysis</button>'+
    '</div>'+
    '<div id="tab-notes" class="tab-pane on">'+sectionsHtml(p, md)+'</div>'+
    '<div id="tab-abstract" class="tab-pane"><div class="prose">'+(p.abstract_hl ? md(p.abstract_hl) : '')+'</div></div>'+
    '<div id="tab-ai" class="tab-pane">'+(p.ai ? '<div class="prose">'+md(p.ai)+'</div>' : '')+
    '</div>';
  activateTab(activeTab);
}
"""

# ─── Server HTML ──────────────────────────────────────────────────────────────
def serve_index():
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"UTF-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>Paper Library</title>\n"
            "<style>" + NEW_CSS + "</style>\n"
            "</head>\n<body>\n"
            + NEW_HTML_BODY +
            "\n<script>\n" + NEW_JS_SERVER + "\n</script>\n</body>\n</html>")

# ─── Static site generator ────────────────────────────────────────────────────
def generate_static():
    site_dir = BASE_DIR / "site"
    site_dir.mkdir(exist_ok=True)
    papers = all_papers()

    static_papers = []
    imgs_dir = site_dir / "imgs"
    for p in papers:
        sp = {k: v for k, v in p.items() if k not in ('has_pdf', 'screenshots')}
        sp['imgs'] = p['screenshots']
        static_papers.append(sp)
        if p['screenshots']:
            dest = imgs_dir / p['key']
            dest.mkdir(parents=True, exist_ok=True)
            for fname in p['screenshots']:
                src = BASE_DIR / p['key'] / fname
                if src.exists():
                    shutil.copy2(src, dest / fname)

    papers_json = json.dumps(static_papers, ensure_ascii=False, indent=2)

    # Separate papers.json for GitHub Pages fetch
    (site_dir / "papers.json").write_text(papers_json, encoding='utf-8')

    master_json = json.dumps({"content": get_master_notes()}, ensure_ascii=False, indent=2)
    (site_dir / "master.json").write_text(master_json, encoding='utf-8')

    warnings_json = json.dumps({"warnings": bib_warnings() + cross_bib_warnings()}, ensure_ascii=False, indent=2)
    (site_dir / "warnings.json").write_text(warnings_json, encoding='utf-8')

    js = NEW_JS_STATIC_TPL.replace('/*PAPERS_JSON*/', papers_json)

    html = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"UTF-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>Paper Library</title>\n"
            "<style>" + NEW_CSS + "</style>\n"
            "</head>\n<body>\n"
            + NEW_HTML_BODY +
            "\n<script>\n" + js + "\n</script>\n</body>\n</html>")

    (site_dir / "index.html").write_text(html, encoding='utf-8')
    n_imgs = sum(len(p['screenshots']) for p in papers)
    print("Static site generated: site/index.html + site/papers.json (" +
          str(len(papers)) + " papers, " + str(n_imgs) + " screenshots)")


# ─── HTTP server ──────────────────────────────────────────────────────────────
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
import json as json_mod

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, code=200):
        body = json_mod.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            self.send_html(serve_index())
        elif path == '/api/papers':
            self.send_json(all_papers())
        elif path.startswith('/api/paper/') and not any(path.endswith(x) for x in ('/notes','/rating')):
            key = unquote(path.split('/api/paper/')[1])
            self.send_json(get_paper(key))
        elif path == '/api/layout':
          layout = get_layout()
          self.send_json({
            "active_bib": layout.get("active_bib"),
            "view": layout.get("view", "list"),
            "order": (layout.get("orders") or {}).get(layout.get("active_bib"), []),
            "bibs": available_bib_files(),
          })
        elif path == '/api/bibs':
          layout = get_layout()
          self.send_json({"active_bib": layout.get("active_bib"), "bibs": available_bib_files()})
        elif path == '/api/master':
          self.send_json({"content": get_master_notes(), "bib": get_active_bib_name()})
        elif path == '/api/warnings':
            self.send_json({"warnings": bib_warnings() + cross_bib_warnings()})
        elif path.startswith('/file/'):
            parts = path[6:].split('/', 1)
            if len(parts) == 2:
                key, fname = parts
                fpath = BASE_DIR / key / fname
                if fpath.exists() and fpath.is_file():
                    data = fpath.read_bytes()
                    mime = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', len(data))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_response(404); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path.endswith('.bib'):
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get('Content-Length', 0))
        body = json_mod.loads(self.rfile.read(length)) if length else {}

        if path.startswith('/api/paper/') and path.endswith('/notes'):
            key = unquote(path.split('/api/paper/')[1].replace('/notes', ''))
            save_note_sections(key, {
                'Quotes':      body.get('quotes', ''),
                'My Thoughts': body.get('thoughts', ''),
                'Sense':       body.get('apply', ''),
                'Tags':        body.get('tags', ''),
                'Venue':       body.get('venue', ''),
                'Keywords':    body.get('keywords', ''),
            })
            self.send_json({"ok": True})
        elif path.startswith('/api/paper/') and path.endswith('/abstract'):
            key = unquote(path.split('/api/paper/')[1].replace('/abstract', ''))
            save_note_sections(key, {'Abstract': body.get('content', '')})
            self.send_json({"ok": True})
        elif path.startswith('/api/paper/') and path.endswith('/ai'):
            key = unquote(path.split('/api/paper/')[1].replace('/ai', ''))
            ai_file = BASE_DIR / key / f"{key}_ai.md"
            if ai_file.exists():
                ai_file.write_text(body.get('content', ''), encoding='utf-8')
                self.send_json({"ok": True})
            else:
                self.send_json({"ok": False, "error": "file not found"}, 404)
        elif path.startswith('/api/paper/') and path.endswith('/rating'):
            key = unquote(path.split('/api/paper/')[1].replace('/rating', ''))
            set_rating(key, body.get('rating', 0))
            self.send_json({"ok": True})
        elif path == '/api/layout':
          layout = get_layout()
          if 'active_bib' in body and body['active_bib'] in available_bib_files():
            layout['active_bib'] = body['active_bib']
          if 'order' in body:
            layout.setdefault('orders', {})[layout.get('active_bib', default_bib_name())] = body.get('order') or []
          if 'view' in body:
            layout['view'] = body['view']
          save_layout(layout)
          self.send_json({"ok": True, "active_bib": get_active_bib_name(), "order": (get_layout().get('orders') or {}).get(get_active_bib_name(), [])})
        elif path == '/api/master':
            save_master_notes(body.get('content', ''))
            self.send_json({"ok": True})
        else:
            self.send_response(404); self.end_headers()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5050
    print("Paper Library  -->  http://localhost:" + str(port))
    print("   Ctrl+C to stop")
    HTTPServer(('', port), Handler).serve_forever()
