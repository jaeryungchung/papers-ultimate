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

### `serve [port]` — Local web server with editing
```bash
python papers.py serve           # default port 5050
python papers.py serve 8080      # custom port
```
- Opens a browser at `http://localhost:{port}`
- Full paper list with search, sort, venue/keyword filters
- Click a paper → see abstract, your notes, AI analysis, screenshots
- **Edit notes** directly in the browser (saved back to `{key}.md` on disk)
- Images served from `{key}/` at `/file/{key}/{filename}`

---

### `export` — Generate static site
```bash
python papers.py export
```
- Writes `site/index.html` — a self-contained static HTML page
- Embeds all paper data (titles, abstracts, notes, AI analysis, images)
- Ready to deploy to GitHub Pages, Netlify, etc.

---

## File layout

```
papers-ultimate/
├── template.bib              ← your BibTeX (source of truth)
├── .env                      ← ANTHROPIC_API_KEY=... (never commit!)
├── papers.py                 ← CLI
├── web_server.py             ← local server
├── status.md                 ← auto-generated status report
├── site/
│   └── index.html            ← generated static site (deploy this)
└── {key}/
    ├── {key}.pdf             ← the paper PDF
    ├── {key}.md              ← your personal notes (edit freely)
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

```bash
# After making changes:
python papers.py export          # regenerate site/index.html
git add -A
git commit -m "Update papers"
git push
```

GitHub Actions automatically deploys `site/` to GitHub Pages on every push.

Live at: **https://jaeryungchung1.github.io/jaeryungchung1/**  
_(or the path configured in Settings → Pages)_

---

## Tips

- **Add a paper:** Paste bib entry into `template.bib`, drop PDF in this folder, run `sync`
- **Quick analysis:** `analyze-all` only runs on papers missing analysis — safe to run repeatedly  
- **Batch screenshots:** Drop all PNGs into their folders, then run `imgs` once
- **Share your library:** Run `export`, then push to GitHub — the site updates automatically
?
# jaeryungchung1
# jaeryungchung1
