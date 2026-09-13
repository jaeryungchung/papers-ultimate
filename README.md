# 📚 papers-ultimate

Personal academic paper management system — organize PDFs, take structured notes, run AI analysis, and publish a slide-style research library website.

---

## Setup

```bash
# Install dependencies
pip install anthropic pypdf

# Add your Anthropic API key
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# First run: read your bib file, create folders, match PDFs
python papers.py sync
```

Place `template.bib` in this folder with your BibTeX entries.

---

## Commands

### `sync` — Organize everything
```bash
python papers.py sync
```
- Reads `template.bib` for all entries
- Scans **`000_new_pdfs/`** (drop new PDFs here) and this folder for loose PDFs, and matches each to a bib entry by:
  1. PDF metadata title vs. bib title
  2. filename vs. bib key / title
  3. **DOI** — a lot of publisher downloads are just named after the DOI (e.g. `3706598.3713435.pdf` for `10.1145/3706598.3713435`); this is checked too
- Creates `{key}/` folders, moves + renames matched PDFs to `{key}/{key}.pdf`
- Creates `{key}/{key}.md` (empty Quotes/My Thoughts/Sense/Tags template) and `{key}/{key}_ai.md` (empty — stays that way until you run `analyze`)
- Warns about PDFs without a bib entry, and bib entries without a PDF
- Warns about malformed `template.bib` entries (see **Bib validation** below)
- Writes `status.md`

A bib entry only shows up in `serve`/the deployed site once it has a `{key}/` folder — `sync` (or `new`) is what "admits" it. Delete a paper's folder to remove it from the library/site without touching the read-only `template.bib`.

---

### `status` — Check library state
```bash
python papers.py status
```
- Prints a table: PDF ✓/✗, notes, AI analysis, screenshot count, affiliations
- Writes `status.md` with full details + warnings (missing PDFs, unmatched loose PDFs, malformed bib entries)

---

### `analyze <key>` — AI analysis of one paper
```bash
python papers.py analyze chung2025wrighthere
python papers.py analyze chung2025wrighthere --show-prompt
```
- Sends the PDF to Claude (via Anthropic API) for deep analysis
- Your own notes (`{key}.md` — Quotes/My Thoughts/Sense) are included as context so the analysis reflects what you already think, but they aren't echoed back as a separate visible section
- Writes result into `{key}/{key}_ai.md`: Summary, Affiliations, Core Contributions, Methodology, Key Findings, Limitations & Future Work, Related Work Cited
- Won't overwrite a manually-fixed Affiliations tag on re-run (see **`{key}_ai.md` is a master file** below)
- `--show-prompt` prints the exact prompt sent to Claude (for transparency/debugging)

**Requires:** `ANTHROPIC_API_KEY` in `.env`

---

### `analyze-all` — AI analysis for all pending papers
```bash
python papers.py analyze-all
python papers.py analyze-all --show-prompt
```
- Runs `analyze` for every paper that doesn't have AI analysis yet (i.e. `{key}_ai.md` is still empty)
- `--show-prompt` prints the prompt (useful the first time to verify the prompt)

---

### `imgs` — Rename screenshots
```bash
python papers.py imgs                       # all papers
python papers.py imgs chung2025wrighthere   # one paper only
```
- Drop any `.png`/`.jpg`/`.jpeg` file into a paper's folder
- Running `imgs` renames them to `{key}_01.png`, `{key}_02.png`, …
- Updates the Screenshots section in `{key}_ai.md` (once it exists — i.e. after `analyze` has run at least once)

**Workflow:**
1. Take a screenshot of a figure/table
2. Move it into `{key}/`
3. Run `python papers.py imgs {key}` (or `imgs` for all)

---

### `new <key>` — Create an empty paper folder
```bash
python papers.py new cassell2001making
```
- Creates `{key}/` folder with an empty `{key}.md` template and an empty `{key}_ai.md`
- Useful before the PDF exists (pair with `sync` later)

---

### `serve [port]` — Local web server (slide view, edit mode)
```bash
python papers.py serve           # default port 5050
python papers.py serve 8080      # custom port
```
Opens a browser at `http://localhost:{port}` — this is the **edit mode**. The deployed GitHub Pages site is always **view-only** (see below).

**Navigating**
- Click a paper, or use **↑ / ↓** (Figma/Keynote-style) to page through the sidebar list — whichever tab you're on carries over to the next paper
- **← / →** switches between the Notes / Abstract / AI Analysis / Edit tabs
- **Esc** toggles between the paper you're viewing and **Master Notes** (see below), and back again
- Search box matches title, authors, venue, affiliations, and **keywords** — a bib keyword doesn't need to appear in the title to be found (e.g. searching "llm" finds a paper whose bib `keywords` field includes LLM even if the title doesn't)
- Sort: Added / Year ↑↓ / A–Z / ★ Stars / Custom. Filter by Venue or your own Tags in the sidebar panel

**Each paper is a slide**
- Title, authors, venue, year, keywords — pulled straight from `template.bib`
- **Notes tab**: **Quotes**, **My Thoughts**, **Sense** (how you'd use this paper), and your own **Tags** as chips (e.g. `#CST`, for sorting into related-work sections later). A section only renders if it has content — nothing shows for an untouched paper
- **Abstract tab**: shows the bib abstract; the pencil icon lets you edit and highlight it too (see below) — your edited copy is saved separately from the read-only bib and takes over as the display
- **AI Analysis tab**: empty until you run `analyze`. `{key}_ai.md` is a master file — the pencil icon lets you hand-edit it afterwards too (e.g. fixing a wrong/missing Affiliations tag); re-running `analyze` won't clobber a manual fix
- **Edit tab**: edit Quotes / My Thoughts / Sense / Tags directly (saved back to `{key}.md`)

**Highlighting** — in the Edit tab's Quotes/My Thoughts/Sense boxes, or the Abstract tab's edit box: select text and press **Cmd/Ctrl+H** to wrap it in a highlight (stored as `==like this==`, rendered as a light-red `<mark>`); press it again on the same selection to remove it.

**Reordering** — press-and-hold and drag any sidebar row up/down to set your own order. This auto-switches Sort to "Custom" and saves the order to `layout.json`; "Added" and "A–Z" are unaffected.

**Rating** — a 0–3 circle scale (○○○ → ●●●) next to the title, defaulting to unrated (0). Click a circle to set it; click the currently-active circle again to clear it back to 0. Stored in `ratings.json`.

**Screenshots panel** — drag the thin divider on its left edge to resize it (remembered per-browser).

**Master Notes** — a scratchpad that isn't a paper. Click "📝 Master Notes" above the search box (or press Esc from any paper). Write freely, and drag a paper from the sidebar into the Edit box to drop in a citation like `[van2021human]` at your cursor; the Notes tab renders that as a clickable pill that jumps straight to the paper — handy for drafting something like a related-work section while browsing. Stored in `master_notes.md`; included read-only in the deployed static site too.

**Bib validation** — if `template.bib` has a mistake that would otherwise make a paper silently vanish or render with missing data (a typo dropping the comma after a key, an entry missing title/author/year, unbalanced braces in a field), a dismissible warning banner appears at the top of the page naming exactly which entry and what's wrong.

- Images served from `{key}/` at `/file/{key}/{filename}`

---

### `export` — Generate static site
```bash
python papers.py export
```
- Writes `site/index.html` + `site/papers.json` + `site/master.json` + `site/warnings.json` — a self-contained, **view-only** static site (no Edit tab, no drag-reorder; ratings/highlights/tags are read-only, but still visible)
- Only includes bib entries that have a `{key}/` folder — see the folder-gating note under `sync` above
- Embeds all paper data (titles, abstracts, quotes/thoughts/sense/tags, AI analysis, images), your custom sort order from `layout.json`, your Master Notes scratchpad, and any bib warnings
- Ready to deploy to GitHub Pages, Netlify, etc.

---

## File layout

```
papers-ultimate/
├── template.bib              ← your BibTeX (source of truth — read-only, chmod 444, never written by this code)
├── .env                      ← ANTHROPIC_API_KEY=... (never commit!)
├── layout.json               ← custom sidebar order (commit this — see GitHub Pages deployment)
├── ratings.json              ← star ratings (commit this too)
├── master_notes.md           ← Master Notes scratchpad (commit this too)
├── 000_new_pdfs/             ← drop new PDFs here; `sync` matches (title or DOI) + moves them into {key}/
├── papers.py                 ← CLI
├── web_server.py             ← local server
├── status.md                 ← auto-generated status report
├── site/
│   ├── index.html            ← generated static site (deploy this)
│   ├── papers.json           ← generated static paper data
│   ├── master.json           ← generated static Master Notes data
│   └── warnings.json         ← generated static bib-warning data
└── {key}/
    ├── {key}.pdf             ← the paper PDF (optional — DOI link works without it)
    ├── {key}.md              ← Quotes / My Thoughts / Sense / Tags / Abstract override (edit freely, or via `serve`)
    ├── {key}_ai.md           ← empty until `analyze` runs; then Summary/Affiliations/etc, plus screenshots
    ├── {key}_01.png          ← screenshots (renamed by `imgs`)
    └── {key}_02.png
```

---

## Affiliation tags

In `{key}_ai.md`, under `## Affiliations`, add institution tags:

```markdown
## Affiliations
<KAIST> <MIT Media Lab>
```

These are parsed by `status` and shown in the web UI as badges — a bare `<unknown>` placeholder is filtered out and shows nothing rather than an "unknown" badge.
Claude also tries to extract affiliations from the PDF during `analyze`; if you hand-correct one afterwards, re-running `analyze` preserves your fix instead of overwriting it.

---

## GitHub Pages deployment

**Important:** the GitHub Action rebuilds `site/` from exactly whatever is committed to `main` — nothing you only did locally (reordering, ratings, quotes, highlights, notes, tags, Master Notes) reaches the deployed page until it's committed and pushed. `site/` itself is gitignored and rebuilt fresh every push, so don't commit it by hand.

```bash
# After a local editing session:
python papers.py export          # regenerate site/ (sanity check locally)
git add -A                       # picks up layout.json, ratings.json, master_notes.md, {key}/{key}.md, template.bib, etc.
git status                       # double-check nothing unexpected is staged
git commit -m "Update papers"
git push
```

GitHub Actions then runs `python papers.py export` itself and deploys `site/` to GitHub Pages.

Live at: **https://jaeryungchung1.github.io/jaeryungchung1/**  
_(or the path configured in Settings → Pages)_

The deployed site is always **view-only** — no Edit tab, ratings/drag-reorder/highlighting are inert — local `serve` is the only place you edit anything.

---

## Tips

- **Add a paper:** paste the bib entry into `template.bib`, drop the PDF in `000_new_pdfs/` (or this folder), run `sync`. `template.bib` is chmod 444 (read-only) on purpose — edit it in your editor as usual (`chmod 644` first if your editor refuses), the app itself will never write to it
- **Quick analysis:** `analyze-all` only runs on papers missing analysis — safe to run repeatedly
- **Batch screenshots:** drop all PNGs into their folders, then run `imgs` once
- **Navigate like slides:** click a paper, then ↑/↓ to page through the (filtered/sorted) list; ←/→ switches tabs and that choice carries over; Esc jumps to/from Master Notes
- **Search by keyword, not just title:** the search box already checks bib keywords — no separate keyword-chip list to dig through
- **Highlight anything editable:** Quotes/My Thoughts/Sense (Edit tab) and the Abstract (its own pencil icon) — select text, Cmd/Ctrl+H
- **Reorder papers:** drag a sidebar row up/down — it saves to `layout.json` and switches Sort to "Custom" automatically
- **Watch for the warning banner:** if a bib entry stops showing up after an edit, check the top of the page — a parse problem in `template.bib` is likely called out there
- **Share your library:** commit `layout.json`, `ratings.json`, `master_notes.md`, and any changed `{key}/{key}.md` / `template.bib`, then push to GitHub — the site updates automatically
