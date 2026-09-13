# 📚 papers-ultimate

Personal academic paper management system — organize PDFs, write notes, run AI analysis, and publish a research library website.

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
- Scans for loose PDFs in this folder, matches by title (metadata similarity)
- Creates `{key}/` folders, moves + renames PDFs to `{key}/{key}.pdf`
- Creates `{key}/{key}.md` (your notes template) and `{key}/{key}_ai.md` (AI stub)
- Warns about PDFs without a bib entry, and bib entries without a PDF
- Writes `status.md`

---

### `status` — Check library state
```bash
python papers.py status
```
- Prints a table: PDF ✓/✗, notes, AI analysis, screenshot count, affiliations
- Writes `status.md` with full details + warnings

---

### `analyze <key>` — AI analysis of one paper
```bash
python papers.py analyze chung2025wrighthere
python papers.py analyze chung2025wrighthere --show-prompt
```
- Sends the PDF to Claude (via Anthropic API) for deep analysis
- Writes result into `{key}/{key}_ai.md`
- Sections: Summary, Contributions, Methodology, Results, Limitations, Future Work, Affiliations
- `--show-prompt` prints the exact prompt sent to Claude (for transparency/debugging)

**Requires:** `ANTHROPIC_API_KEY` in `.env`

---

### `analyze-all` — AI analysis for all pending papers
```bash
python papers.py analyze-all
python papers.py analyze-all --show-prompt
```
- Runs `analyze` for every paper that doesn't have an AI analysis yet
- Skips papers that already have `{key}_ai.md` with real content
- `--show-prompt` prints the prompt (useful the first time to verify the prompt)

---

### `imgs` — Rename screenshots
```bash
python papers.py imgs                       # all papers
python papers.py imgs chung2025wrighthere   # one paper only
```
- Drop any `.png`/`.jpg`/`.jpeg` file into a paper's folder
- Running `imgs` renames them to `{key}_01.png`, `{key}_02.png`, …
- Updates the Screenshots section in `{key}_ai.md`

**Workflow:**
1. Take a screenshot of a figure/table
2. Move it into `{key}/`
3. Run `python papers.py imgs {key}` (or `imgs` for all)

---

### `new <key>` — Create an empty paper folder
```bash
python papers.py new cassell2001making
```
- Creates `{key}/` folder with `{key}.md` and `{key}_ai.md` stubs
- Useful before the PDF exists (pair with `sync` later)

---

### `serve [port]` — Local web server with editing (slide view, edit mode)
```bash
python papers.py serve           # default port 5050
python papers.py serve 8080      # custom port
```
- Opens a browser at `http://localhost:{port}` — this is the **edit mode**; the deployed GitHub Pages site is always **view-only** (see below)
- Full paper list with search, sort, venue/keyword/tag filters
- Click a paper (or use **↑ / ↓ arrow keys**, Figma/Keynote-style, to page through the sidebar list). **← / →** switches between the Notes/Abstract/AI Analysis/Edit tabs — whichever tab you're on carries over to the next paper you page to
- Each paper renders as a slide: title, authors, venue, year, keywords — all pulled straight from `template.bib`
- **Notes tab** shows sections meant for sharing with your advisor/co-workers — **Quotes**, **My Thoughts**, **Sense** (how you'd use this paper) — and your own **Tags** as chips (e.g. `#CST`, for later sorting into related-work sections). A section only shows up if it has content
- **Edit tab**: edit those fields directly (saved back to `{key}.md` on disk). Select text in Quotes/My Thoughts/Sense and press **Cmd/Ctrl+H** to wrap it in a highlight (`==like this==`, rendered as `<mark>`); press it again on the same selection to remove the highlight
- **AI Analysis tab**: `{key}_ai.md` is a master file — the pencil icon lets you hand-edit it too (e.g. fixing a wrong/missing Affiliations tag), not just view what `analyze` generated. Re-running `analyze` won't clobber a manually-fixed affiliation
- **Reorder papers**: press-and-hold and drag any sidebar row up/down to set your own order — this auto-switches Sort to "Custom" and saves the order to `layout.json`. "Added" and "A–Z" sort are unaffected
- **Screenshots panel**: drag the thin divider on its left edge to resize it (remembered per-browser)
- Images served from `{key}/` at `/file/{key}/{filename}`

---

### `export` — Generate static site
```bash
python papers.py export
```
- Writes `site/index.html` + `site/papers.json` — a self-contained, **view-only** static site (no Edit tab, no drag-reorder, ratings/highlights are read-only)
- Embeds all paper data (titles, abstracts, quotes/thoughts/how-to-apply, AI analysis, images) plus your custom sort order from `layout.json`
- Ready to deploy to GitHub Pages, Netlify, etc.

---

## File layout

```
papers-ultimate/
├── template.bib              ← your BibTeX (source of truth — read-only, chmod 444, never written by this code)
├── .env                      ← ANTHROPIC_API_KEY=... (never commit!)
├── layout.json               ← custom sidebar order (commit this — see GitHub Pages deployment)
├── ratings.json              ← star ratings (commit this too)
├── papers.py                 ← CLI
├── web_server.py             ← local server
├── status.md                 ← auto-generated status report
├── site/
│   ├── index.html            ← generated static site (deploy this)
│   └── papers.json           ← generated static data
└── {key}/
    ├── {key}.pdf             ← the paper PDF (optional — DOI link works without it)
    ├── {key}.md              ← Quotes / My Thoughts / Sense / Tags (edit freely, or via `serve`)
    ├── {key}_ai.md           ← AI analysis + screenshots
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

These are parsed by `status` and shown in the web UI.  
Claude also tries to extract affiliations from the PDF during `analyze`.

---

## GitHub Pages deployment

**Important:** the GitHub Action rebuilds `site/` from exactly whatever is committed to `main` — nothing you only did locally (reordering, ratings, quotes, highlights, notes) reaches the deployed page until it's committed and pushed. `site/` itself is gitignored and rebuilt fresh every push, so don't commit it by hand.

```bash
# After a local editing session:
python papers.py export          # regenerate site/index.html + site/papers.json (sanity check locally)
git add -A                       # picks up layout.json, ratings.json, {key}/{key}.md, template.bib, etc.
git status                       # double-check nothing unexpected is staged
git commit -m "Update papers"
git push
```

GitHub Actions then runs `python papers.py export` itself and deploys `site/` to GitHub Pages.

Live at: **https://jaeryungchung1.github.io/jaeryungchung1/**  
_(or the path configured in Settings → Pages)_

The deployed site is always **view-only** — no Edit tab, ratings/drag-reorder are inert — local `serve` is the only place you edit anything.

---

## Tips

- **Add a paper:** Paste bib entry into `template.bib`, drop PDF in this folder, run `sync`. `template.bib` is chmod 444 (read-only) on purpose — edit it in your editor as usual (`chmod 644` first if your editor refuses), the app itself will never write to it
- **Quick analysis:** `analyze-all` only runs on papers missing analysis — safe to run repeatedly  
- **Batch screenshots:** Drop all PNGs into their folders, then run `imgs` once
- **Navigate like slides:** click a paper, then use ↑/↓ to page through the (filtered/sorted) list; ←/→ switches tabs and that choice carries over as you page
- **Highlight a quote:** select text in the Quotes/My Thoughts/Sense boxes (Edit tab), press Cmd/Ctrl+H
- **Reorder papers:** drag a sidebar row up/down — it saves to `layout.json` and switches Sort to "Custom" automatically
- **Share your library:** commit `layout.json`, `ratings.json`, and any changed `{key}/{key}.md` / `template.bib`, then push to GitHub — the site updates automatically
?
# jaeryungchung1
# jaeryungchung1
