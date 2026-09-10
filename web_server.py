#!/usr/bin/env python3
"""web_server.py – Local paper viewer/editor server + static site generator"""

import sys, re, json, mimetypes, base64, shutil, os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
LAYOUT_FILE  = BASE_DIR / "layout.json"
RATINGS_FILE = BASE_DIR / "ratings.json"

# ─── bib parser ───────────────────────────────────────────────────────────────
def parse_bib():
    text = (BASE_DIR / "template.bib").read_text(encoding='utf-8')
    entries = {}
    for m in re.finditer(r'@(\w+)\{(\w+),(.*?)(?=\n@|\Z)', text, re.DOTALL):
        etype, key, body = m.group(1), m.group(2), m.group(3)
        fields = {'_type': etype.lower()}
        for fm in re.finditer(r'(\w+)\s*=\s*\{(.*?)\}(?=\s*,|\s*\n\s*[}\w])', body, re.DOTALL):
            fields[fm.group(1).lower()] = re.sub(r'\s+', ' ', fm.group(2)).strip()
        entries[key] = fields
    return entries

def bib_order():
    text = (BASE_DIR / "template.bib").read_text(encoding='utf-8')
    return re.findall(r'@\w+\{(\w+),', text)

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
def parse_affiliations(key):
    ai_file = BASE_DIR / key / f"{key}_ai.md"
    if not ai_file.exists(): return []
    text = ai_file.read_text(encoding='utf-8')
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    found = []
    for m in re.finditer(r'<([A-Za-z][^<>\n]{1,60})>', text):
        tag = m.group(1).strip()
        if tag and tag not in found:
            found.append(tag)
    return found[:5]

# ─── ratings ──────────────────────────────────────────────────────────────────
def load_ratings():
    if RATINGS_FILE.exists():
        return json.loads(RATINGS_FILE.read_text(encoding='utf-8'))
    return {}

def save_ratings(ratings):
    RATINGS_FILE.write_text(json.dumps(ratings, indent=2, ensure_ascii=False), encoding='utf-8')

def get_rating(key):
    return load_ratings().get(key, 4)

def set_rating(key, value):
    r = load_ratings()
    r[key] = max(1, min(5, int(value)))
    save_ratings(r)

# ─── paper data ───────────────────────────────────────────────────────────────
def get_paper(key):
    entries = parse_bib()
    fields = entries.get(key, {})
    folder = BASE_DIR / key

    venue_full  = fields.get('booktitle') or fields.get('journal', '')
    year        = fields.get('year', '')
    venue_short = make_venue_short(venue_full, year)

    raw_kw   = fields.get('keywords', '')
    keywords = [k.strip() for k in re.split(r'[,;]', raw_kw) if k.strip()] if raw_kw else []

    named = re.compile(rf'^{re.escape(key)}_\d+\.(png|jpg|jpeg)$', re.I)
    screenshots = sorted(
        f.name for f in folder.iterdir() if named.match(f.name)
    ) if folder.exists() else []

    notes_raw   = (folder / f"{key}.md").read_text('utf-8') if (folder / f"{key}.md").exists() else ''
    notes_clean = re.sub(r'^(# .+\n)(\*\*[^\n]+\n)*(\n?---\n)?', '', notes_raw).strip()

    ai_raw = (folder / f"{key}_ai.md").read_text('utf-8') if (folder / f"{key}_ai.md").exists() else ''

    authors = fields.get('author', '')
    authors = re.sub(r'\{\\[a-zA-Z]+\s*([a-zA-Z])\}', r'\1', authors)
    authors = re.sub(r'\\([a-zA-Z])', r'\1', authors)

    order = bib_order()
    add_order = order.index(key) if key in order else 9999

    return {
        "key":          key,
        "title":        fields.get('title', key),
        "authors":      authors,
        "year":         int(year) if str(year).isdigit() else year,
        "venue_short":  venue_short,
        "venue_full":   venue_full,
        "doi":          fields.get('doi', ''),
        "abstract":     fields.get('abstract', ''),
        "keywords":     keywords,
        "affiliations": parse_affiliations(key),
        "notes":        notes_clean,
        "ai":           ai_raw,
        "screenshots":  screenshots,
        "has_pdf":      (folder / f"{key}.pdf").exists(),
        "rating":       get_rating(key),
        "add_order":    add_order,
    }

def all_papers():
    return [get_paper(k) for k in parse_bib()]

def get_layout():
    if LAYOUT_FILE.exists():
        return json.loads(LAYOUT_FILE.read_text())
    return {"order": [], "view": "list"}

def save_layout(data):
    LAYOUT_FILE.write_text(json.dumps(data, indent=2))


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
#shell.has-shots{grid-template-columns:272px 1fr 220px;}

#sidebar{background:var(--sidebar);color:var(--s-ink);display:flex;flex-direction:column;overflow:hidden;border-right:1px solid var(--s-border);}
.sb-head{padding:18px 16px 10px;border-bottom:1px solid var(--s-border);flex-shrink:0;}
.sb-wordmark{font-size:10px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--s-ink2);margin-bottom:4px;}
.sb-title{font-family:'Spectral',serif;font-size:16px;font-weight:600;color:#e8eaf6;margin-bottom:10px;}
#search{width:100%;background:var(--sidebar2);border:1px solid var(--s-border);border-radius:6px;color:var(--s-ink);font-size:12px;padding:6px 10px;outline:none;}
#search::placeholder{color:var(--s-ink2);}

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
.pl-item{padding:10px 16px;cursor:pointer;border-bottom:1px solid var(--s-border);transition:background .12s;}
.pl-item:hover{background:var(--sidebar2);}
.pl-item.active{background:#1e2a50;border-left:3px solid var(--accent);}
.pl-meta{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;}
.pl-year{font-size:10px;color:var(--s-ink2);}
.pl-venue-tag{font-size:10px;background:var(--sidebar2);border:1px solid var(--s-border);padding:1px 6px;border-radius:8px;color:var(--s-ink2);}
.pl-title{font-size:12px;color:#e0e2f0;font-weight:500;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.pl-authors{font-size:10px;color:var(--s-ink2);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.pl-stars{font-size:10px;color:var(--star);margin-top:2px;}
.pl-empty{padding:20px 16px;color:var(--s-ink2);font-size:12px;text-align:center;}

#main{overflow:hidden;display:flex;flex-direction:column;}
#welcome{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;text-align:center;padding:40px;}
#welcome svg{opacity:.2;}
#welcome h2{font-family:'Spectral',serif;font-size:22px;color:var(--ink);opacity:.45;}
#welcome p{font-size:13px;max-width:260px;line-height:1.6;color:var(--ink2);}
#paper-view{flex:1;overflow-y:auto;padding:32px 40px 60px;}
#paper-view::-webkit-scrollbar{width:5px;}
#paper-view::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}

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
.rating-label{font-size:11px;color:var(--ink2);margin-left:6px;}

.aff-row{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}
.aff-tag{font-size:11px;background:#e8f0fe;color:#3050a0;border-radius:6px;padding:2px 8px;}
[data-theme="dark"] .aff-tag{background:#1e2a50;color:#7090d0;}
.kw-row{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px;}
.kw{font-size:11px;background:var(--tag-bg);color:var(--ink2);border-radius:10px;padding:2px 8px;}
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
.prose ul{padding-left:20px;margin-bottom:10px;}
.prose li{margin-bottom:4px;}
.prose code{background:var(--tag-bg);padding:1px 5px;border-radius:3px;font-size:12px;}
.prose img{max-width:100%;border-radius:6px;margin:8px 0;cursor:zoom-in;}
.prose strong{font-weight:600;}
.prose hr{border:none;border-top:1px solid var(--border);margin:16px 0;}
.empty-note{color:var(--ink2);font-size:13px;padding:20px 0;}
.empty-note code{background:var(--tag-bg);padding:2px 6px;border-radius:3px;}

#shots-panel{border-left:1px solid var(--border);overflow-y:auto;background:var(--bg2);padding:12px 8px;display:flex;flex-direction:column;gap:8px;}
#shots-panel::-webkit-scrollbar{width:4px;}
#shots-panel::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}
.shot-card img{width:100%;border-radius:6px;cursor:zoom-in;border:1px solid var(--border);display:block;}
.shot-label{font-size:10px;color:var(--ink2);margin-top:3px;text-align:center;}
.shots-header{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--ink2);margin-bottom:4px;text-align:center;}

#theme-btn{position:fixed;bottom:16px;right:16px;background:var(--bg2);border:1px solid var(--border);border-radius:50%;width:32px;height:32px;cursor:pointer;font-size:15px;color:var(--ink2);z-index:10;}

.lightbox{position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:999;display:flex;align-items:center;justify-content:center;cursor:zoom-out;}
.lightbox img{max-width:90vw;max-height:90vh;border-radius:8px;}

@media(max-width:700px){
  #shell,#shell.has-shots{grid-template-columns:1fr;}
  #sidebar{height:40vh;}
  #shots-panel{display:none;}
  #paper-view{padding:18px 18px 40px;}
}
"""


# ─── HTML body ────────────────────────────────────────────────────────────────
NEW_HTML_BODY = """
<div id="shell">
  <aside id="sidebar">
    <div class="sb-head">
      <div class="sb-wordmark">Research Library</div>
      <div class="sb-title">Paper Collection</div>
      <input id="search" type="search" placeholder="Search titles, authors, keywords..."
             oninput="Q.query=this.value; renderList()" autocomplete="off">
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
      </div>
      <div class="filter-group">
        <div class="filter-label">Venue</div>
        <div class="chip-row" id="venue-chips"></div>
      </div>
      <div class="filter-group">
        <div class="filter-label">Keywords</div>
        <div class="chip-row" id="kw-chips"></div>
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
  <div id="shots-panel" hidden></div>
</div>
<button id="theme-btn" onclick="toggleTheme()">&#x25D0;</button>
"""


# ─── Shared JS (raw string – no f-string) ─────────────────────────────────────
NEW_JS_COMMON = r"""
const Q = { query: '', sort: 'added', venues: new Set(), kws: new Set() };
let activeKey = null;
let PAPERS = [];

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
  if (Q.kws.size)    list = list.filter(p => (p.keywords||[]).some(k => Q.kws.has(k)));
  const cmp = {
    added:     (a,b) => (a.add_order||0) - (b.add_order||0),
    year_desc: (a,b) => b.year - a.year,
    year_asc:  (a,b) => a.year - b.year,
    title:     (a,b) => a.title.localeCompare(b.title),
    venue:     (a,b) => (a.venue_short||'').localeCompare(b.venue_short||''),
    rating:    (a,b) => (b.rating||4) - (a.rating||4),
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
function toggleKw(k)    { Q.kws.has(k)    ? Q.kws.delete(k)    : Q.kws.add(k);    renderList(); }

function starsStr(n) {
  let s = '';
  for (let i = 1; i <= 5; i++) s += i <= n ? '★' : '☆';
  return s;
}

function renderList() {
  const list = filtered();
  const ul = document.getElementById('paper-list');
  if (!list.length) {
    ul.innerHTML = '<li class="pl-empty">No papers match.</li>';
  } else {
    ul.innerHTML = list.map(p =>
      '<li class="pl-item' + (activeKey===p.key?' active':'') + '" data-key="' + p.key + '" onclick="openPaper(\'' + p.key + '\')">' +
        '<div class="pl-meta">' +
          '<span class="pl-year">' + p.year + '</span>' +
          '<span class="pl-venue-tag">' + stripYear(p.venue_short||'') + '</span>' +
        '</div>' +
        '<div class="pl-title">' + escHtml(p.title) + '</div>' +
        '<div class="pl-authors">' + escHtml(p.authors||'') + '</div>' +
        '<div class="pl-stars">' + starsStr(p.rating||4) + '</div>' +
      '</li>'
    ).join('');
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
  Q.kws.forEach(k => mkChip(k, () => { Q.kws.delete(k); renderList(); }));
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
  const freq = {};
  PAPERS.forEach(p => (p.keywords||[]).forEach(k => { freq[k] = (freq[k]||0)+1; }));
  const topKws = Object.entries(freq).sort((a,b) => b[1]-a[1]||a[0].localeCompare(b[0])).slice(0,16);
  const kwRow = document.getElementById('kw-chips');
  kwRow.innerHTML = '';
  topKws.forEach(([k,n]) => {
    const el = document.createElement('span');
    el.className = 'fchip'; el.dataset.k = k;
    el.innerHTML = escHtml(k) + (n>1 ? ' <small style="opacity:.6">'+n+'</small>' : '');
    el.addEventListener('click', () => toggleKw(k));
    kwRow.appendChild(el);
  });
}

function switchTab(btn, id) {
  btn.closest('.tabs').querySelectorAll('.tab').forEach(t => t.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('on'));
  document.getElementById('tab-'+id).classList.add('on');
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
  src = src.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  src = src.replace(/\*(.+?)\*/g, '<em>$1</em>');
  src = src.replace(/`(.+?)`/g, '<code>$1</code>');
  src = src.replace(/^---+$/gm, '<hr>');
  src = src.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  return src.split(/\n\n+/).map(b => {
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
  if (!imgs || !imgs.length) {
    panel.hidden = true;
    shell.classList.remove('has-shots');
    return;
  }
  panel.hidden = false;
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
  for (let i = 1; i <= 5; i++) {
    h += '<button class="star-btn' + (i<=rating?' on':'') + '" onclick="setRating(\'' + key + '\',' + i + ')" title="' + i + ' star' + (i>1?'s':'') + '">' + (i<=rating?'★':'☆') + '</button>';
  }
  h += '<span class="rating-label">' + rating + ' / 5</span></div>';
  return h;
}

try {
  const t = localStorage.getItem('theme');
  if (t) document.documentElement.setAttribute('data-theme', t);
} catch(e) {}
"""


# ─── Server JS ────────────────────────────────────────────────────────────────
NEW_JS_SERVER = NEW_JS_COMMON + r"""
async function loadPapers() {
  const resp = await fetch('/api/papers').catch(() => null);
  if (!resp) return;
  PAPERS = await resp.json();
  buildFilterChips();
  renderList();
}

function mdWithImages(src, key) {
  return md(src).replace(/<img src="([^"]+)"/g, function(_, href) {
    if (/^https?:\/\//.test(href)) return '<img src="'+href+'"';
    return '<img src="/file/'+key+'/'+href+'"';
  });
}

async function openPaper(key) {
  activeKey = key;
  const resp = await fetch('/api/paper/' + key);
  const p = await resp.json();
  const idx = PAPERS.findIndex(x => x.key === key);
  if (idx >= 0) PAPERS[idx] = p;
  renderList();
  document.getElementById('welcome').hidden = true;
  const view = document.getElementById('paper-view');
  view.hidden = false;

  renderShots(p.screenshots || [], key, '/file/'+key+'/');

  const affHtml = (p.affiliations||[]).length
    ? '<div class="aff-row">'+p.affiliations.map(a=>'<span class="aff-tag">&#x1f3db; '+escHtml(a)+'</span>').join('')+'</div>' : '';
  const kwHtml = (p.keywords||[]).length
    ? '<div class="kw-row">'+p.keywords.map(k=>'<span class="kw">'+escHtml(k)+'</span>').join('')+'</div>' : '';
  const doiHtml = p.doi ? '<a class="pill" href="https://doi.org/'+p.doi+'" target="_blank">&#x1f517; DOI</a>' : '';
  const pdfHtml = p.has_pdf ? '<a class="pill" href="/file/'+key+'/'+key+'.pdf" target="_blank">&#x1f4c4; PDF</a>' : '';
  const rating = p.rating || 4;

  const notesHtml = p.notes
    ? '<div class="prose">'+mdWithImages(p.notes, key)+'</div>'
    : '<div class="empty-note"><strong>No notes yet.</strong> Click the Edit tab to add notes.</div>';

  view.innerHTML =
    '<div class="pv-eyebrow">'+escHtml(p.venue_full||p.venue_short||'')+'</div>'+
    '<h1 class="pv-title">'+escHtml(p.title)+'</h1>'+
    '<div class="pv-meta">'+
      '<span class="pill">&#x1f464; '+escHtml(p.authors)+'</span>'+
      '<span class="pill">&#x1f4c5; '+p.year+'</span>'+
      doiHtml+pdfHtml+
    '</div>'+
    starsEditHtml(key, rating)+
    affHtml+kwHtml+
    '<hr class="divider">'+
    '<div class="tabs">'+
      '<button class="tab on" onclick="switchTab(this,\'notes\')">Notes</button>'+
      '<button class="tab" onclick="switchTab(this,\'abstract\')">Abstract</button>'+
      '<button class="tab" onclick="switchTab(this,\'ai\')">AI Analysis</button>'+
      '<button class="tab" onclick="switchTab(this,\'edit\')">&#x270F; Edit</button>'+
    '</div>'+
    '<div id="tab-notes" class="tab-pane on">'+notesHtml+'</div>'+
    '<div id="tab-abstract" class="tab-pane"><div class="prose"><p>'+escHtml(p.abstract||'')+'</p></div></div>'+
    '<div id="tab-ai" class="tab-pane">'+(p.ai
      ? '<div class="prose">'+mdWithImages(p.ai, key)+'</div>'
      : '<div class="empty-note"><strong>No AI analysis yet.</strong><br>Run: <code>python papers.py analyze '+key+'</code></div>')+
    '</div>'+
    '<div id="tab-edit" class="tab-pane">'+
      '<textarea id="notes-editor" style="width:100%;height:60vh;font-family:monospace;font-size:13px;padding:10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--ink);resize:vertical">'+escHtml(p.notes||'')+'</textarea>'+
      '<div style="margin-top:8px;display:flex;gap:8px">'+
        '<button onclick="saveNotes(\''+key+'\')" style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:7px 16px;cursor:pointer;font-size:13px">Save</button>'+
        '<span id="save-status" style="font-size:12px;color:var(--ink2);align-self:center"></span>'+
      '</div>'+
    '</div>';
}

async function saveNotes(key) {
  const content = document.getElementById('notes-editor').value;
  const st = document.getElementById('save-status');
  st.textContent = 'Saving...';
  const resp = await fetch('/api/paper/'+key+'/notes', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content})
  });
  const r = await resp.json();
  st.textContent = r.ok ? '✓ Saved' : '✗ Error';
  setTimeout(() => { st.textContent = ''; }, 2000);
  const idx = PAPERS.findIndex(x => x.key === key);
  if (idx >= 0) PAPERS[idx].notes = content;
}

async function setRating(key, value) {
  await fetch('/api/paper/'+key+'/rating', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({rating: value})
  });
  const idx = PAPERS.findIndex(x => x.key === key);
  if (idx >= 0) PAPERS[idx].rating = value;
  document.querySelectorAll('.star-btn').forEach(function(btn, i) {
    btn.classList.toggle('on', i < value);
    btn.textContent = i < value ? '★' : '☆';
  });
  const rl = document.querySelector('.rating-label');
  if (rl) rl.textContent = value + ' / 5';
  const li = document.querySelector('.pl-item[data-key="'+key+'"] .pl-stars');
  if (li) li.textContent = starsStr(value);
}

loadPapers();
"""


# ─── Static JS template ───────────────────────────────────────────────────────
NEW_JS_STATIC_TPL = NEW_JS_COMMON + """
(function() {
  function init(papers) {
    PAPERS = papers;
    buildFilterChips();
    renderList();
  }
  fetch('papers.json')
    .then(function(r){ return r.json(); })
    .then(init)
    .catch(function() { init(/*PAPERS_JSON*/); });
})();

function setRating(key, value) { /* read-only in static mode */ }

function openPaper(key) {
  activeKey = key;
  const p = PAPERS.find(function(x){ return x.key === key; });
  if (!p) return;
  renderList();
  document.getElementById('welcome').hidden = true;
  const view = document.getElementById('paper-view');
  view.hidden = false;

  renderShots(p.imgs || [], key, null);

  const affHtml = (p.affiliations||[]).length
    ? '<div class="aff-row">'+p.affiliations.map(function(a){ return '<span class="aff-tag">&#x1f3db; '+escHtml(a)+'</span>'; }).join('')+'</div>' : '';
  const kwHtml = (p.keywords||[]).length
    ? '<div class="kw-row">'+p.keywords.map(function(k){ return '<span class="kw">'+escHtml(k)+'</span>'; }).join('')+'</div>' : '';
  const doiHtml = p.doi ? '<a class="pill" href="https://doi.org/'+p.doi+'" target="_blank">&#x1f517; DOI</a>' : '';
  const rating = p.rating || 4;

  const starsHtml2 = starsEditHtml(key, rating);

  view.innerHTML =
    '<div class="pv-eyebrow">'+escHtml(p.venue_full||p.venue_short||'')+'</div>'+
    '<h1 class="pv-title">'+escHtml(p.title)+'</h1>'+
    '<div class="pv-meta">'+
      '<span class="pill">&#x1f464; '+escHtml(p.authors)+'</span>'+
      '<span class="pill">&#x1f4c5; '+p.year+'</span>'+
      doiHtml+
    '</div>'+
    starsHtml2+
    affHtml+kwHtml+
    '<hr class="divider">'+
    '<div class="tabs">'+
      '<button class="tab on" onclick="switchTab(this,\\'notes\\')">Notes</button>'+
      '<button class="tab" onclick="switchTab(this,\\'abstract\\')">Abstract</button>'+
      '<button class="tab" onclick="switchTab(this,\\'ai\\')">AI Analysis</button>'+
    '</div>'+
    '<div id="tab-notes" class="tab-pane on">'+(p.notes
      ? '<div class="prose">'+md(p.notes)+'</div>'
      : '<div class="empty-note"><strong>No notes yet.</strong><br>Run <code>python papers.py serve</code> to add notes.</div>')+
    '</div>'+
    '<div id="tab-abstract" class="tab-pane"><div class="prose"><p>'+escHtml(p.abstract||'<em>No abstract.</em>')+'</p></div></div>'+
    '<div id="tab-ai" class="tab-pane">'+(p.ai
      ? '<div class="prose">'+md(p.ai)+'</div>'
      : '<div class="empty-note"><strong>No AI analysis yet.</strong><br>Run: <code>python papers.py analyze '+key+'</code></div>')+
    '</div>';
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
            self.send_json(get_layout())
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
        length = int(self.headers.get('Content-Length', 0))
        body = json_mod.loads(self.rfile.read(length)) if length else {}

        if path.startswith('/api/paper/') and path.endswith('/notes'):
            key = unquote(path.split('/api/paper/')[1].replace('/notes', ''))
            md_file = BASE_DIR / key / f"{key}.md"
            if md_file.exists():
                md_file.write_text(body.get('content', ''), encoding='utf-8')
                self.send_json({"ok": True})
            else:
                self.send_json({"ok": False, "error": "file not found"}, 404)
        elif path.startswith('/api/paper/') and path.endswith('/rating'):
            key = unquote(path.split('/api/paper/')[1].replace('/rating', ''))
            set_rating(key, body.get('rating', 4))
            self.send_json({"ok": True})
        elif path == '/api/layout':
            save_layout(body)
            self.send_json({"ok": True})
        else:
            self.send_response(404); self.end_headers()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5050
    print("Paper Library  -->  http://localhost:" + str(port))
    print("   Ctrl+C to stop")
    HTTPServer(('', port), Handler).serve_forever()
