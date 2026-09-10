#!/usr/bin/env python3
"""
papers.py – Academic Paper Management CLI

Commands:
  sync               Read bib + scan PDFs → organize, warn mismatches, write status.md
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

# ─── pdf utils ───────────────────────────────────────────────────────────────
def get_pdf_title(pdf_path):
    for mod in ('pypdf', 'PyPDF2'):
        try:
            m = __import__(mod)
            r = m.PdfReader(str(pdf_path))
            t = (r.metadata or {}).get('/Title') or (r.metadata or {}).get('title')
            if t: return t
        except Exception:
            pass
    return None

def word_overlap(a, b):
    if not a or not b: return 0.0
    wa = set(re.findall(r'[a-z]+', a.lower()))
    wb = set(re.findall(r'[a-z]+', b.lower()))
    return len(wa & wb) / max(len(wa), len(wb)) if wa and wb else 0.0

def find_loose_pdfs():
    return list(BASE_DIR.glob("*.pdf"))

def match_pdf_to_entries(pdf_path, entries):
    pdf_title = get_pdf_title(pdf_path) or ""
    best_key, best_score = None, 0.0
    for key, f in entries.items():
        score = max(
            word_overlap(pdf_title, f.get("title", "")),
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
        venue = f.get("booktitle") or f.get("journal", "")
        md.write_text(
            f"# {f.get('title', key)}\n\n"
            f"**Authors:** {f.get('author', '')}\n"
            f"**Year:** {f.get('year', '')}\n"
            f"**Venue:** {venue}\n"
            f"**DOI:** {f.get('doi', '')}\n\n"
            f"---\n\n## Notes\n\n\n\n## Key Points\n\n- \n\n## Relevance\n\n\n",
            encoding="utf-8"
        )
        print(f"    📝  {key}/{key}.md")

    ai = folder / f"{key}_ai.md"
    if not ai.exists():
        title = f.get("title", key)
        author = f.get("author", "")
        ai.write_text(
            f"<!-- AI Analysis: {key} -->\n"
            f"<!-- See also: [{key}.md]({key}.md) -->\n\n"
            f"# AI Analysis: {title}\n\n"
            f"_User notes: [{key}.md]({key}.md)_ · [Full PDF]({key}.pdf)\n\n"
            f"---\n\n"
            f"## Affiliations\n\n"
            f"<!-- Tag each author's institution: <MIT> <KAIST> <Aalborg> etc. -->\n"
            f"<!-- Authors: {author[:120]} -->\n"
            f"<unknown>\n\n"
            f"---\n\n"
            f"## Summary\n\n"
            f"_Run `python papers.py analyze {key}` to generate AI analysis._\n\n"
            f"## Screenshots\n\n"
            f"_Drop screenshots here, then run `python papers.py imgs {key}` or `python papers.py imgs`_\n\n"
            f"---\n",
            encoding="utf-8"
        )
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
ANALYSIS_PROMPT = """You are analyzing an academic paper. The user has provided their own reading notes below.

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

## Connection to User Notes
How this paper relates to the notes the user wrote (if notes are empty, say so).

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

    # parse affiliations from analysis and write into the Affiliations section
    pat = _named_pattern(key)
    imgs = sorted(f2.name for f2 in folder.iterdir() if pat.match(f2.name))
    img_md = '\n\n'.join(f'![{s}]({s})' for s in imgs) or '_No screenshots yet._'

    ai_file.write_text(
        f"<!-- AI Analysis: {key} – {datetime.now():%Y-%m-%d %H:%M} -->\n"
        f"<!-- See also: [{key}.md]({key}.md) -->\n\n"
        f"# AI Analysis: {title}\n\n"
        f"_User notes: [{key}.md]({key}.md)_ · [Full PDF]({key}.pdf)\n\n"
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
    has_ai  = sum(1 for k in entries if (BASE_DIR/k/f"{k}_ai.md").exists()
                  and "python papers.py analyze" not in (BASE_DIR/k/f"{k}_ai.md").read_text(encoding="utf-8"))
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
    warnings = []
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
        ai_file = folder/f"{k}_ai.md"
        ai_ok = ai_file.exists() and "python papers.py analyze" not in ai_file.read_text(encoding="utf-8") if ai_file.exists() else False
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

def cmd_sync(args):
    entries = parse_bib()
    loose   = find_loose_pdfs()
    print(f"Bib entries: {len(entries)}  |  Loose PDFs: {len(loose)}\n")

    used = set()
    for key in entries:
        folder = BASE_DIR / key
        print(f"📚  {key}")
        if (folder/f"{key}.pdf").exists():
            init_paper_folder(key, entries)
        else:
            matched = None
            for pdf in loose:
                if pdf in used: continue
                mk, score = match_pdf_to_entries(pdf, {key: entries[key]})
                if mk == key:
                    print(f"    ↳ matched {pdf.name} (score {score:.2f})")
                    matched = pdf; used.add(pdf); break
            init_paper_folder(key, entries, pdf_src=matched)
            if not matched and not (folder/f"{key}.pdf").exists():
                print(f"    ⚠️  No PDF — add as {key}/{key}.pdf")

    orphans = [p for p in loose if p not in used]
    if orphans:
        print("\n⚠️  PDFs with no matching bib entry (add to template.bib):")
        for p in orphans: print(f"    - {p.name}")

    write_status_md(entries, loose_orphans=orphans)

def cmd_status(args):
    entries = parse_bib()
    orphans = find_loose_pdfs()

    print(f"\n{'Key':<26} {'PDF':^5} {'MD':^5} {'AI':^5} {'Imgs':^5} {'Affiliations':<18}  Title")
    print("─"*95)
    for key, f in entries.items():
        folder = BASE_DIR / key
        n_imgs = len(list(folder.glob(f"{key}_*.png"))+list(folder.glob(f"{key}_*.jpg"))) if folder.exists() else 0
        ai_ok = False
        ai_f = folder/f"{key}_ai.md"
        if ai_f.exists(): ai_ok = "python papers.py analyze" not in ai_f.read_text(encoding="utf-8")
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
    pending = []
    for key in entries:
        ai = BASE_DIR / key / f"{key}_ai.md"
        if not ai.exists() or "python papers.py analyze" in ai.read_text(encoding="utf-8"):
            pending.append(key)
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

    sub.add_parser("sync",   help="Organize PDFs, create stubs, write status.md")
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
