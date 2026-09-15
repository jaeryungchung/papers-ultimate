#!/usr/bin/env python3
"""
papers.py – Academic Paper Management CLI

Commands:
  sync               Read bib + scan PDFs → organize, warn mismatches, write status.md
                     Loose PDFs are matched by DOI (filename or printed in the PDF),
                     arXiv id, or title; for folders still missing a PDF it asks you
                     to pick one from the loose PDFs (--no-pick to skip the prompt).
  status             Print + write status.md
  analyze <key>      AI summary for one paper (shows prompt)
  analyze-all        AI summary for all papers missing analysis
  imgs               Rename screenshots across ALL paper folders
  imgs <key>         Rename screenshots in one paper folder
  new <key>          Init empty paper folder
  serve [port]       Local web server with note editing (default 5050)
  export             Write site/index.html static site

Env: put ANTHROPIC_API_KEY=... in .env next to papers.py
"""

import os, re, sys, json, shutil, argparse, subprocess, base64, textwrap
from pathlib import Path
from datetime import datetime

BASE_DIR  = Path(__file__).parent
BIB_FILE  = BASE_DIR / "template.bib"
LAYOUT    = BASE_DIR / "layout.json"
STATUS_MD = BASE_DIR / "status.md"
PDF_DIR   = BASE_DIR / "000_new_pdfs"  # drop new PDFs here for `sync` to pick up

# ─── .env loader ─────────────────────────────────────────────────────────────
def load_env():
    env = BASE_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

load_env()

# ─── bib parser ──────────────────────────────────────────────────────────────
# NOTE: template.bib is the source of truth and must stay read-only from this
# codebase — only ever .read_text() it here, never .write_text().
def parse_bib(bib_path=BIB_FILE):
    text = bib_path.read_text(encoding="utf-8")
    entries = {}
    for m in re.finditer(r'@(\w+)\{(\w+),(.*?)(?=\n@|\Z)', text, re.DOTALL):
        etype, key, body = m.group(1), m.group(2), m.group(3)
        f = {"_type": etype.lower()}
        for fm in re.finditer(r'(\w+)\s*=\s*\{(.*?)\}(?=\s*,|\s*\n\s*[}\w])', body, re.DOTALL):
            f[fm.group(1).lower()] = re.sub(r'\s+', ' ', fm.group(2)).strip()
        entries[key] = f
    return entries

def bib_warnings(bib_path=BIB_FILE):
    """Sanity-check template.bib for mistakes that make an entry silently
    vanish or render with missing data (a malformed entry just fails the
    parse_bib() regex with no error otherwise)."""
    text = bib_path.read_text(encoding="utf-8")
    warnings = []

    starts = re.findall(r'@\w+\s*\{\s*([^,\s}]*)', text)
    parsed = parse_bib(bib_path)
    missing = [k for k in starts if k and k not in parsed]
    if missing:
        warnings.append(
            "template.bib: " + ", ".join(sorted(set(missing))) +
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

    return warnings

# ─── pdf utils ───────────────────────────────────────────────────────────────
_PDF_INFO_CACHE = {}

def _pdf_reader(pdf_path):
    import logging
    for mod in ('pypdf', 'PyPDF2'):
        try:
            logging.getLogger(mod).setLevel(logging.ERROR)   # font/xref chatter
            return __import__(mod).PdfReader(str(pdf_path))
        except ImportError:
            continue
        except Exception:
            return None
    return None

_DOI_RE = re.compile(r'10\.\d{4,9}/[^\s"<>\)\]]+', re.I)

def _norm_doi(doi):
    doi = (doi or "").strip().lower()
    doi = re.sub(r'^(https?://)?(dx\.)?doi\.org/', '', doi)
    return doi.rstrip('.,;')

def _norm_text(t):
    return re.sub(r'[^a-z0-9]+', ' ', (t or "").lower()).strip()

def pdf_info(pdf_path):
    """Everything we can cheaply learn about a PDF for matching: metadata
    title, the first couple of pages of text, and any DOIs printed in that
    text (publisher PDFs almost always stamp the DOI on page 1). Cached
    because sync asks about the same loose PDF once per bib entry."""
    key = str(pdf_path)
    if key in _PDF_INFO_CACHE:
        return _PDF_INFO_CACHE[key]
    info = {"title": "", "text": "", "dois": set()}
    r = _pdf_reader(pdf_path)
    if r is not None:
        try:
            meta = r.metadata or {}
            t = meta.get('/Title') or meta.get('title') or ""
            # Word/LaTeX leave junk like "Microsoft Word - out.doc" here
            if t and not re.match(r'^(microsoft word|untitled|sigchi|acm|doi:)', t.strip().lower()):
                info["title"] = str(t)
        except Exception:
            pass
        try:
            info["text"] = "\n".join((pg.extract_text() or "") for pg in r.pages[:2])
        except Exception:
            pass
        info["dois"] = {_norm_doi(d) for d in _DOI_RE.findall(info["text"])}
        info["dois"] |= {_norm_doi(d) for d in _DOI_RE.findall(str(t or ""))}
        info["dois"].discard("")
    _PDF_INFO_CACHE[key] = info
    return info

def get_pdf_title(pdf_path):
    return pdf_info(pdf_path)["title"] or None

def pdf_display_title(pdf_path):
    """Best human-readable guess at what a PDF is, for the sync picker."""
    info = pdf_info(pdf_path)
    if info["title"]:
        return info["title"]
    for line in info["text"].splitlines():
        line = line.strip(" :\t-–—")
        # skip running headers like "Published as a conference paper at ICLR 2026"
        # or "Int. J. Human-Computer Studies 58 (2003) 583–603"
        if len(line) > 12 and not re.search(
                r'proceedings|published as|conference|journal|vol\.|\(\d{4}\)|\d{4}\s*$|^chi\s', line.lower()):
            return line
    return ""

def word_overlap(a, b):
    if not a or not b: return 0.0
    wa = set(re.findall(r'[a-z]+', a.lower()))
    wb = set(re.findall(r'[a-z]+', b.lower()))
    return len(wa & wb) / max(len(wa), len(wb)) if wa and wb else 0.0

def find_loose_pdfs():
    PDF_DIR.mkdir(exist_ok=True)
    return sorted(PDF_DIR.glob("*.pdf")) + sorted(BASE_DIR.glob("*.pdf"))

def doi_variants(doi):
    """Publisher-downloaded PDFs are often just named after the DOI (with '/'
    swapped for a separator, or just the suffix after it) — e.g. a DOI of
    10.1145/3706598.3713435 shows up as a file named 3706598.3713435.pdf."""
    doi = _norm_doi(doi)
    if not doi:
        return []
    variants = {doi, doi.replace('/', '.'), doi.replace('/', '_'), doi.replace('/', '-')}
    if '/' in doi:
        variants.add(doi.split('/', 1)[1])
    return [v for v in variants if v]

def entry_doi(f):
    """DOI from the `doi` field, falling back to a doi.org `url`."""
    doi = _norm_doi(f.get("doi", ""))
    if not doi:
        m = _DOI_RE.search(f.get("url", "") or "")
        doi = _norm_doi(m.group(0)) if m else ""
    return doi

def entry_arxiv_id(f):
    """arXiv id (e.g. 2405.07089) from eprint/url/journal, since arXiv PDFs
    download as <id>v<n>.pdf."""
    blob = " ".join(f.get(k, "") or "" for k in ("eprint", "arxivid", "url", "journal", "note", "archiveprefix"))
    if "arxiv" not in blob.lower() and not f.get("eprint"):
        return ""
    m = re.search(r'(\d{4}\.\d{4,5})(?:v\d+)?', blob)
    return m.group(1) if m else ""

def match_pdf_to_entries(pdf_path, entries):
    """Score a loose PDF against bib entries. Strongest → weakest:
      1.00  DOI in the filename, or the same DOI printed inside the PDF
      0.95  arXiv id in the filename
      0.90  the bib title appears verbatim in the PDF's first pages
      ≤1.0  word overlap between PDF metadata title / first line and bib title
      ≤0.7  word overlap between filename and bib key / title"""
    info = pdf_info(pdf_path)
    stem_lower = pdf_path.stem.lower()
    text_norm = _norm_text(info["text"])
    best_key, best_score = None, 0.0
    for key, f in entries.items():
        doi = entry_doi(f)
        score = 0.0
        if doi:
            if any(v in stem_lower for v in doi_variants(doi)) or doi in info["dois"]:
                score = 1.0
        if score < 0.95:
            axid = entry_arxiv_id(f)
            if axid and axid in stem_lower:
                score = 0.95
        if score < 0.9:
            title_norm = _norm_text(f.get("title", ""))
            if len(title_norm) >= 20 and title_norm in text_norm:
                score = 0.9
        if score < 0.9:
            score = max(
                score,
                word_overlap(info["title"], f.get("title", "")),
                word_overlap(pdf_display_title(pdf_path), f.get("title", "")) * 0.9,
                word_overlap(pdf_path.stem, key) * 0.7,
                word_overlap(pdf_path.stem, f.get("title", "")) * 0.4,
            )
        if score > best_score:
            best_score, best_key = score, key
    return (best_key, best_score) if best_score >= 0.15 else (None, 0.0)

# ─── folder init ─────────────────────────────────────────────────────────────
def init_paper_folder(key, entries, pdf_src=None):
    folder = BASE_DIR / key
    folder.mkdir(exist_ok=True)
    f = entries.get(key, {})

    if pdf_src and pdf_src.exists():
        dest = folder / f"{key}.pdf"
        if not dest.exists():
            shutil.move(str(pdf_src), str(dest))
            print(f"    📄  {pdf_src.name} → {key}/{key}.pdf")

    md = folder / f"{key}.md"
    if not md.exists():
        # No title/author/venue header here — that's already on the slide
        # from template.bib. The Edit-tab Save in web_server.py rewrites this
        # file as just these four sections, so keep the on-disk template in
        # sync with that shape.
        md.write_text(
            "## Quotes\n\n\n\n## My Thoughts\n\n\n\n## Sense\n\n\n\n## Tags\n\n\n",
            encoding="utf-8"
        )
        print(f"    📝  {key}/{key}.md")

    ai = folder / f"{key}_ai.md"
    if not ai.exists():
        # Left completely empty — the AI Analysis tab only shows something
        # once `analyze` actually writes real content (Summary, Affiliations,
        # etc). No placeholder boilerplate to display or to accidentally
        # treat as "already analyzed".
        ai.write_text("", encoding="utf-8")
        print(f"    🤖  {key}/{key}_ai.md")

    return folder

# ─── screenshot renaming ──────────────────────────────────────────────────────
def _named_pattern(key):
    return re.compile(rf'^{re.escape(key)}_\d+\.(png|jpg|jpeg)$', re.I)

def rename_screenshots_for(key, verbose=True):
    folder = BASE_DIR / key
    if not folder.exists(): return 0
    pat = _named_pattern(key)
    new_files = sorted(
        [f for f in folder.iterdir()
         if f.suffix.lower() in ('.png','.jpg','.jpeg') and not pat.match(f.name)],
        key=lambda x: x.stat().st_mtime
    )
    if not new_files: return 0
    next_n = len([f for f in folder.iterdir() if pat.match(f.name)]) + 1
    for i, f in enumerate(new_files, next_n):
        new = f"{key}_{i:02d}{f.suffix.lower()}"
        f.rename(folder / new)
        if verbose: print(f"    🖼  {f.name} → {new}")
    _update_ai_screenshots(key)
    return len(new_files)

def _update_ai_screenshots(key):
    ai = BASE_DIR / key / f"{key}_ai.md"
    if not ai.exists(): return
    pat = _named_pattern(key)
    imgs = sorted(f.name for f in (BASE_DIR/key).iterdir() if pat.match(f.name))
    img_md = '\n\n'.join(f'![{s}]({s})' for s in imgs) or '_No screenshots yet._'
    content = ai.read_text(encoding="utf-8")
    content = re.sub(
        r'## Screenshots\n\n.*?(?=\n---|\Z)',
        f'## Screenshots\n\n{img_md}\n\n',
        content, flags=re.DOTALL
    )
    ai.write_text(content, encoding="utf-8")

# ─── AI-analysis status ────────────────────────────────────────────────────────
def has_ai_analysis(key):
    """True once `_ai.md` actually has content — it starts empty and only gets
    written by `analyze`, so file-exists alone isn't enough."""
    ai = BASE_DIR / key / f"{key}_ai.md"
    return ai.exists() and bool(ai.read_text(encoding="utf-8").strip())

# ─── affiliation parser ───────────────────────────────────────────────────────
def parse_affiliations(key):
    """Extract <Tag> style affiliations from _ai.md Affiliations section.
    Strips HTML comments first so template hints don't pollute results."""
    ai = BASE_DIR / key / f"{key}_ai.md"
    if not ai.exists(): return []
    m = re.search(r'## Affiliations\n(.*?)(?=\n##|\n---|\Z)', ai.read_text(encoding="utf-8"), re.DOTALL)
    if not m: return []
    section = re.sub(r'<!--.*?-->', '', m.group(1), flags=re.DOTALL)
    tags = re.findall(r'<([^/!>][^>]*)>', section)
    return [t.strip() for t in tags if t.strip().lower() not in ('unknown','br','p','em','strong','a')]

# ─── AI analysis ─────────────────────────────────────────────────────────────
ANALYSIS_PROMPT = """You are analyzing an academic paper. The user has provided their own reading notes below —
use them to inform your analysis (e.g. what to emphasize in Summary/Core Contributions), but don't write a
separate section calling out the connection; just fold that understanding into the sections below.

## User Notes
{notes}

---

Please write a structured Markdown analysis with these exact sections:

## Summary
2–3 sentences covering the core idea and contribution.

## Affiliations
List the authors and their institutions exactly as they appear in the paper.
Format each institution as a tag on its own line: <InstitutionName> (e.g. <MIT> <KAIST> <Aalborg University>)

## Core Contributions
Bullet points of the main technical/scientific contributions.

## Methodology
How the study was conducted (system built, study design, participants, metrics).

## Key Findings
Main results and takeaways.

## Limitations & Future Work
What the authors acknowledge as limitations, and directions they suggest.

## Related Work Cited
3–5 key cited works most relevant to the paper's contribution (title + authors, no need for full ref).

Keep each section concise and researcher-useful. Format clean Markdown."""

def analyze_paper(key, show_prompt=False):
    try:
        import anthropic
    except ImportError:
        print(f"anthropic not found — installing with {sys.executable}...")
        import subprocess
        r = subprocess.run([sys.executable, "-m", "pip", "install", "anthropic"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌  Install failed:\n{r.stderr}")
            return
        print("✓  anthropic installed — retrying")
        import anthropic  # noqa: F401

    folder = BASE_DIR / key
    pdf_file = folder / f"{key}.pdf"
    md_file  = folder / f"{key}.md"
    ai_file  = folder / f"{key}_ai.md"

    if not pdf_file.exists():
        print(f"  ✗  No PDF: {key}/{key}.pdf"); return

    entries = parse_bib()
    f = entries.get(key, {})
    notes = md_file.read_text(encoding="utf-8") if md_file.exists() else "(no user notes yet)"
    title = f.get("title", key)

    prompt = ANALYSIS_PROMPT.format(notes=notes)

    if show_prompt:
        print("\n" + "─"*60)
        print("📝  Prompt sent to Claude:")
        print("─"*60)
        print(prompt)
        print("─"*60 + "\n")

    print(f"  ⏳  Calling Claude API for {key}…")
    # NOTE: the bundled httpx2 asks for brotli/zstd responses, but old system
    # brotli builds reject its `output_buffer_limit` kwarg — the resulting
    # TypeError surfaces as a misleading `APIConnectionError: Connection error.`
    # Sticking to gzip keeps the response decodable on any environment.
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        default_headers={"accept-encoding": "gzip, deflate"},
    )
    pdf_b64 = base64.standard_b64encode(pdf_file.read_bytes()).decode()

    resp = client.beta.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        betas=["pdfs-2024-09-25"],
        messages=[{"role": "user", "content": [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text": prompt}
        ]}]
    )
    analysis = resp.content[0].text

    # ai_file.md is a master file the user can hand-edit (e.g. fixing a
    # wrong/missing Affiliations tag) — don't let a re-run of `analyze`
    # clobber a manually-corrected affiliation with a fresh "<unknown>".
    old_affiliations = parse_affiliations(key)
    if old_affiliations and ai_file.exists():
        old_block_m = re.search(r'(## Affiliations\n.*?)(?=\n## |\n---|\Z)', ai_file.read_text(encoding="utf-8"), re.DOTALL)
        if old_block_m:
            analysis = re.sub(r'## Affiliations\n.*?(?=\n## |\Z)', old_block_m.group(1).strip() + '\n\n', analysis, count=1, flags=re.DOTALL)

    # parse affiliations from analysis and write into the Affiliations section
    pat = _named_pattern(key)
    imgs = sorted(f2.name for f2 in folder.iterdir() if pat.match(f2.name))
    img_md = '\n\n'.join(f'![{s}]({s})' for s in imgs) or '_No screenshots yet._'

    ai_file.write_text(
        f"<!-- AI Analysis: {key} – {datetime.now():%Y-%m-%d %H:%M} -->\n"
        f"<!-- See also: [{key}.md]({key}.md) -->\n\n"
        f"# AI Analysis: {title}\n\n"
        f"[Full PDF]({key}.pdf)\n\n"
        f"---\n\n"
        f"{analysis}\n\n"
        f"---\n\n"
        f"## Screenshots\n\n{img_md}\n\n"
        f"---\n_Generated {datetime.now():%Y-%m-%d} by Claude (model: claude-opus-4-5)_\n",
        encoding="utf-8"
    )
    print(f"  ✅  {key}/{key}_ai.md written")

# ─── status.md writer ────────────────────────────────────────────────────────
def write_status_md(entries, loose_orphans=None):
    """Write status.md with current library state."""
    lines = [
        "# Paper Library — Status",
        f"_Last updated: {datetime.now():%Y-%m-%d %H:%M}_\n",
        "---\n",
        "## Summary\n",
    ]

    total = len(entries)
    has_pdf = sum(1 for k in entries if (BASE_DIR/k/f"{k}.pdf").exists())
    has_ai  = sum(1 for k in entries if has_ai_analysis(k))
    has_imgs = sum(
        len(list((BASE_DIR/k).glob(f"{k}_*.png")) + list((BASE_DIR/k).glob(f"{k}_*.jpg")))
        for k in entries if (BASE_DIR/k).exists()
    )

    lines += [
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total papers (bib entries) | {total} |",
        f"| PDFs present | {has_pdf} / {total} |",
        f"| AI analysis done | {has_ai} / {total} |",
        f"| Total screenshots indexed | {has_imgs} |",
        "",
    ]

    # warnings
    warnings = [f"⚠️  **template.bib**: {w}" for w in bib_warnings()]
    if loose_orphans:
        for p in loose_orphans:
            warnings.append(f"⚠️  **Unmatched PDF** (no bib entry found): `{p.name}` — add a `@article{{...}}` entry to `template.bib`")
    for k in entries:
        if not (BASE_DIR/k/f"{k}.pdf").exists():
            warnings.append(f"⚠️  **Missing PDF** for `{k}` — save as `{k}/{k}.pdf`")

    if warnings:
        lines += ["## ⚠️ Warnings\n"] + [f"- {w}" for w in warnings] + [""]

    lines += ["## Papers\n"]

    for k, f in entries.items():
        folder = BASE_DIR / k
        pdf_ok = (folder/f"{k}.pdf").exists()
        ai_ok = has_ai_analysis(k)
        pat = _named_pattern(k)
        n_imgs = len(list(folder.glob(f"{k}_*.png"))+list(folder.glob(f"{k}_*.jpg"))) if folder.exists() else 0
        aff = parse_affiliations(k)
        aff_str = " ".join(f"`<{a}>`" for a in aff) if aff else "_unknown_"

        status_icon = "✅" if pdf_ok else "🔴"
        lines += [
            f"### {status_icon} `{k}`\n",
            f"**{f.get('title', k)}**  ",
            f"_{f.get('author','')}_  ",
            f"{f.get('year','')} · {f.get('booktitle') or f.get('journal','')}\n",
            f"| | |",
            f"|-|-|",
            f"| PDF | {'✓' if pdf_ok else '✗ missing — add to `'+k+'/'+k+'.pdf`'} |",
            f"| Notes | {'✓' if (folder/f'{k}.md').exists() else '✗'} |",
            f"| AI Analysis | {'✓' if ai_ok else '✗ — run `python papers.py analyze '+k+'`'} |",
            f"| Screenshots | {n_imgs} file(s) |",
            f"| Affiliations | {aff_str} |",
            "",
        ]

    if loose_orphans:
        lines += ["## Unmatched PDFs (no bib entry)\n"]
        for p in loose_orphans:
            lines += [
                f"- `{p.name}`  ",
                f"  Add a bib entry to `template.bib` and run `python papers.py sync`",
            ]
        lines.append("")

    lines += [
        "---",
        "_Generated by `python papers.py status`_",
    ]

    STATUS_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"  📋  status.md updated")

# ─── commands ─────────────────────────────────────────────────────────────────

AUTO_MATCH_MIN = 0.5   # move a loose PDF into a folder without asking above this

def _pick_loose_pdf(key, f, candidates):
    """Interactive picker for a bib entry whose folder has no PDF. Shows the
    remaining loose PDFs (best guess first) and lets the user choose one.
    Returns the chosen Path, None to skip, or 'stop' to stop asking."""
    scored = []
    for pdf in candidates:
        _, score = match_pdf_to_entries(pdf, {key: f})
        scored.append((score, pdf))
    scored.sort(key=lambda t: (-t[0], t[1].name.lower()))

    print(f"    ❓  No PDF for {key} — {f.get('title', '')[:70]}")
    print(f"        Pick a loose PDF (number), Enter = skip, q = stop asking:")
    for i, (score, pdf) in enumerate(scored, 1):
        hint = pdf_display_title(pdf)[:60]
        tag  = f"  ({score:.2f})" if score > 0 else ""
        print(f"        {i:>2}) {pdf.name}{tag}")
        if hint:
            print(f"             {hint}")
    while True:
        try:
            ans = input("        > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "stop"
        if ans == "":
            return None
        if ans in ("q", "quit"):
            return "stop"
        if ans.isdigit() and 1 <= int(ans) <= len(scored):
            return scored[int(ans) - 1][1]
        print("        (enter a number from the list, Enter to skip, or q)")

def cmd_sync(args):
    entries = parse_bib()
    loose   = find_loose_pdfs()
    print(f"Bib entries: {len(entries)}  |  Loose PDFs: {len(loose)}\n")

    bwarn = bib_warnings()
    if bwarn:
        print("⚠️  template.bib issues:")
        for w in bwarn:
            print(f"    - {w}")
        print()

    # Pass 1 — confident automatic matches (DOI / arXiv id / title in PDF text).
    # Each loose PDF goes to the entry it scores highest against, so two entries
    # with similar titles don't fight over the same file.
    used = set()
    auto = {}   # key -> pdf
    for pdf in loose:
        mk, score = match_pdf_to_entries(pdf, entries)
        if mk and score >= AUTO_MATCH_MIN and not (BASE_DIR / mk / f"{mk}.pdf").exists():
            prev = auto.get(mk)
            if prev is None or score > prev[1]:
                auto[mk] = (pdf, score)

    missing = []
    for key in entries:
        folder = BASE_DIR / key
        print(f"📚  {key}")
        if (folder/f"{key}.pdf").exists():
            init_paper_folder(key, entries)
            continue
        pdf, score = auto.get(key, (None, 0.0))
        if pdf is not None and pdf not in used:
            print(f"    ↳ matched {pdf.name} (score {score:.2f})")
            used.add(pdf)
            init_paper_folder(key, entries, pdf_src=pdf)
        else:
            init_paper_folder(key, entries)
            missing.append(key)

    # Pass 2 — folders that exist but still have no PDF: let the user pick one
    # of the remaining loose PDFs (only when running in a terminal).
    remaining = [p for p in loose if p not in used]
    pick = missing and remaining and sys.stdin.isatty() and not getattr(args, "no_pick", False)
    if pick:
        print(f"\n{len(missing)} entries without a PDF, {len(remaining)} loose PDFs left.")
        for key in missing:
            if not remaining:
                break
            choice = _pick_loose_pdf(key, entries[key], remaining)
            if choice == "stop":
                break
            if choice is None:
                continue
            used.add(choice)
            remaining.remove(choice)
            init_paper_folder(key, entries, pdf_src=choice)
        print()

    for key in missing:
        if not (BASE_DIR / key / f"{key}.pdf").exists():
            print(f"    ⚠️  {key}: No PDF — add as {key}/{key}.pdf")

    orphans = [p for p in loose if p not in used]
    if orphans:
        print("\n⚠️  PDFs with no matching bib entry (add to template.bib):")
        for p in orphans:
            hint = pdf_display_title(p)
            print(f"    - {p.name}" + (f"  —  {hint[:70]}" if hint else ""))

    write_status_md(entries, loose_orphans=orphans)

def cmd_status(args):
    entries = parse_bib()
    orphans = find_loose_pdfs()

    print(f"\n{'Key':<26} {'PDF':^5} {'MD':^5} {'AI':^5} {'Imgs':^5} {'Affiliations':<18}  Title")
    print("─"*95)
    for key, f in entries.items():
        folder = BASE_DIR / key
        n_imgs = len(list(folder.glob(f"{key}_*.png"))+list(folder.glob(f"{key}_*.jpg"))) if folder.exists() else 0
        ai_ok = has_ai_analysis(key)
        aff = parse_affiliations(key)
        aff_str = ",".join(aff[:2]) if aff else "-"
        print(f"  {key:<24}"
              f"{'✓' if (folder/f'{key}.pdf').exists() else '✗':^5}"
              f"{'✓' if (folder/f'{key}.md').exists() else '✗':^5}"
              f"{'✓' if ai_ok else '✗':^5}"
              f"{n_imgs:^5}"
              f"  {aff_str:<18}"
              f"  {f.get('title','')[:40]}")

    write_status_md(entries, loose_orphans=orphans)

def cmd_analyze(args):
    show = getattr(args, 'show_prompt', False)
    analyze_paper(args.key, show_prompt=show)

def cmd_analyze_all(args):
    show = getattr(args, 'show_prompt', False)
    entries = parse_bib()
    pending = [key for key in entries if not has_ai_analysis(key)]
    if not pending:
        print("✅  All papers already have AI analysis."); return
    print(f"Found {len(pending)} paper(s) to analyze: {', '.join(pending)}\n")
    for key in pending:
        print(f"\n📖  {key}")
        analyze_paper(key, show_prompt=show)

def cmd_imgs(args):
    key = getattr(args, 'key', None)
    if key:
        n = rename_screenshots_for(key)
        print(f"  Renamed {n} screenshot(s) in {key}/")
    else:
        # all papers
        entries = parse_bib()
        total = 0
        for k in entries:
            n = rename_screenshots_for(k, verbose=True)
            if n: print(f"  {k}: {n} renamed")
            total += n
        print(f"\n✅  Total: {total} screenshot(s) renamed across all papers")

def cmd_new(args):
    entries = parse_bib()
    if args.key not in entries:
        print(f"Warning: '{args.key}' not in template.bib (continuing anyway)")
    init_paper_folder(args.key, entries)

def cmd_serve(args):
    port = getattr(args, 'port', None) or 5050
    subprocess.run([sys.executable, str(BASE_DIR/"web_server.py"), str(port)])

def cmd_export(args):
    sys.path.insert(0, str(BASE_DIR))
    import web_server
    web_server.generate_static()

# ─── main ────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="papers.py – paper management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python papers.py sync
          python papers.py analyze chung2025wrighthere --show-prompt
          python papers.py analyze-all --show-prompt
          python papers.py imgs                        # all papers
          python papers.py imgs chung2025wrighthere    # one paper
          python papers.py status
          python papers.py serve 5050
        """)
    )
    sub = p.add_subparsers(dest="cmd")

    p_sync = sub.add_parser("sync",   help="Organize PDFs, create stubs, write status.md")
    p_sync.add_argument("--no-pick", action="store_true",
                        help="Don't interactively ask which loose PDF belongs to a folder without one")
    sub.add_parser("status", help="Print status + write status.md")
    sub.add_parser("export", help="Generate site/index.html")

    p_a = sub.add_parser("analyze", help="AI summary for one paper")
    p_a.add_argument("key")
    p_a.add_argument("--show-prompt", action="store_true", help="Print the prompt sent to Claude")

    p_aa = sub.add_parser("analyze-all", help="AI summary for all pending papers")
    p_aa.add_argument("--show-prompt", action="store_true")

    p_i = sub.add_parser("imgs", help="Rename screenshots (all papers if no key given)")
    p_i.add_argument("key", nargs="?", help="Paper key (omit for all papers)")

    p_n = sub.add_parser("new", help="Init empty paper folder")
    p_n.add_argument("key")

    p_s = sub.add_parser("serve", help="Local web server")
    p_s.add_argument("port", nargs="?", type=int, default=5050)

    args = p.parse_args()
    {
        "sync": cmd_sync, "status": cmd_status,
        "analyze": cmd_analyze, "analyze-all": cmd_analyze_all,
        "imgs": cmd_imgs, "new": cmd_new,
        "serve": cmd_serve, "export": cmd_export,
    }.get(args.cmd, lambda _: p.print_help())(args)

if __name__ == "__main__":
    main()
