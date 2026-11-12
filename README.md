# job_applier

**Find graduate jobs worth applying to, and get an honest, tailored application pack for each one.**

Point it at a job posting. It tells you how well you actually fit, writes a
resume and cover letter tailored to that posting, and hands you a filled-in
answer sheet for the online form. You read it. You submit it.

It cannot make things up. Every line on a generated resume is traced back to a
specific bullet in your own profile file and checked before it reaches a
document. Inflated numbers, invented tools, and real skills quietly attributed
to the wrong employer are all blocked automatically.

```
$ ja discover

Searching 4 source(s): mycareersfuture, greenhouse, lever, ashby
fetched 312 postings, 189 unique after merging, 11 worth applying to
178 screened out

 MUST    DUE  SOURCE           COMPANY                    TITLE
----------------------------------------------------------------------------------
 100%  12-04  mycareersfuture  EXAMPLE TECH PTE. LTD.     Security Engineer Graduate
  96%  12-31  greenhouse       Example Corp               Technical Graduate Programme
  81%  11-13  mycareersfuture  ANOTHER CO PTE. LTD.       Security Engineer, Graduate
               missing: code review
```

---

## Contents

- [What it does and does not do](#what-it-does-and-does-not-do)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Your profile is the whole point](#your-profile-is-the-whole-point)
- [The daily workflow](#the-daily-workflow)
- [Reading the fit report](#reading-the-fit-report)
- [Where postings come from](#where-postings-come-from)
- [Command reference](#command-reference)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Privacy](#privacy)
- [How it works](#how-it-works)
- [Contributing](#contributing)

---

## What it does and does not do

**It does:**

- Search public job APIs and rank openings by how well you genuinely match
- Screen out senior roles, expired postings and ones you are not eligible for
- Write a resume tailored to each posting, using only your real experience
- Write a short, specific cover letter
- Tell you honestly which required skills you do not have
- Fill in the repetitive parts of application forms
- Track every application and chase you when one goes quiet

**It does not:**

- **Submit applications.** The last click is always yours. An auto-submitted
  application is one you never read, sent under your name, and most job boards
  prohibit it in their terms.
- **Pad your resume.** If a posting needs a skill you lack, the report says so.
- **Scrape LinkedIn, Indeed, Glassdoor or JobStreet.** Those have no public API
  and their terms prohibit automated access. See
  [Where postings come from](#where-postings-come-from) for what happens instead.

---

## Requirements

- **Python 3.10 or newer** (`python --version` to check)
- Optional, for PDF output: **Microsoft Word** (Windows) or **LibreOffice**
  (any platform). Without either you still get `.docx`, which is what most
  application systems prefer anyway.
- Optional, for better wording: an **Anthropic API key**, or a local model via
  **Ollama**. Everything works without one — see
  [Do I need an API key?](#do-i-need-an-api-key)

---

## Quick start

### 1. Get the code

```bash
git clone https://github.com/cyrolite/automated-job-applier.git
cd automated-job-applier
```

### 2. Install

**Windows** — double-click `setup.bat`, or in a terminal:

```bat
setup.bat
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Create your profile

This is the one step you cannot skip.

```bat
copy Context\profile.example.yaml Context\profile.yaml     :: Windows
cp Context/profile.example.yaml Context/profile.yaml        # macOS/Linux
```

Now open `Context/profile.yaml` and replace the example person with yourself.
The template is commented throughout. Budget half an hour; you do it once, and
every application afterwards is built from it.

### 4. Check everything works

```bat
ja init
```

```
[ok] Folders ready: applications/, data/, prompts/
[ok] Created .env from .env.example
[ok] Profile loads: 9 bullets, 10 skills
[!] No LLM provider configured. Everything still runs in no-model mode.
    For tailored phrasing, put a key in .env:  ANTHROPIC_API_KEY=sk-ant-...
    Or run a local model instead:               JA_PROVIDER=ollama
[ok] Tracker ready at data\tracker.db
```

If you see your own bullet count, you are ready.

> `ja` is a small launcher in the repository root: `ja.bat` on Windows, `ja` on
> macOS and Linux. Run it from the repository folder as `ja <command>`
> (`./ja <command>` on macOS/Linux if `.` is not on your PATH). It is only a
> convenience — `PYTHONPATH=src python -m job_applier <command>` does the same
> thing from anywhere.

### 5. Try it on one posting

Save a job description to `jd.txt`, then:

```bat
ja score -f jd.txt
```

That prints a fit report and writes nothing. If it looks useful, build the full pack:

```bat
ja apply -f jd.txt -c "Example Corp" --title "Graduate Security Engineer"
```

---

## Your profile is the whole point

`Context/profile.yaml` is the single source of truth. The tool may only select
and rephrase bullets that exist in it, so **anything missing from that file can
never appear on a generated resume.**

Three things make it work:

**Every bullet has a stable id.**

```yaml
- id: bigco.b1
  text: "Analysed HTTP request patterns across production traffic to characterise
         automated abuse, covering roughly 500,000 requests per day."
  tags: [threat-detection, http, bot-detection]
  metrics: ["~500,000 requests/day"]
```

Generated documents cite those ids. That is what lets each line be traced back
and verified, and it is why a rewrite that drifts from the source gets caught.

**Real numbers belong in the text.** The verifier blocks any number not present
in the source bullet, so "over 10,000 packets" cannot quietly become 100,000.

**Tags decide relevance.** A security posting ranks security-tagged work above
work that merely shares a programming language. Tag honestly and the ranking
gets noticeably better.

**Skills carry a level and evidence:**

```yaml
- name: Cryptography
  level: working          # expert | proficient | working | exposure
  aliases: [crypto, encryption, aes, hashing, pki]
  tags: [security]
  evidence: [passwords.b1]
```

`aliases` are how postings actually spell things — this is what makes matching
work at all. `evidence` outranks a self-assessed level, so a skill you can point
at is treated as a strength and one you cannot is reported as "claim carefully".

**Keep it current.** Add every new project, internship and number as it happens.
Every future application picks it up for free.

---

## The daily workflow

### Find roles

```bat
ja discover
```

Hits the public job APIs, scores everything against your profile, and queues
what fits. Add `--show-rejected` to see what was screened out and why — the
rejections are often more informative than the matches.

For LinkedIn, JobStreet, Indeed and Glassdoor:

```bat
ja urls
```

That prints correct search links with the filters already applied. Open them
yourself, save the results as JSON, then:

```bat
ja ingest -s linkedin -f capture.json
```

### Look at the queue

```bat
ja status --status discovered
```

### Build an application

For a role discovery already found, no copy-paste needed:

```bat
ja apply --from-queue example-tech-security-engineer-graduate
```

For a posting you have as text:

```bat
ja apply -f jd.txt -c "Example Corp" --title "Graduate Security Engineer" --deadline 2027-01-15
```

You get a folder under `applications/`:

| File | What it is |
|---|---|
| `fit-report.md` | How well you match, what to surface, what you genuinely lack |
| `resume.docx` | The file to upload. One column, no tables, no images — parser-friendly |
| `resume.pdf` | Same, if Word or LibreOffice is available |
| `resume.txt` | Plain text, for "paste your resume" boxes |
| `cover-letter.docx` / `.txt` | Short and specific |
| `form-answers.md` | Every field the form will ask for, already answered |
| `fill-plan.json` | Machine-readable version, after you run `ja fill` |
| `grounding.md` | Which claims were checked, and anything that failed |
| `jd.txt` | The posting, kept for the record |

### Fill the form

```bat
ja fill example-tech-security-engineer-graduate
```

Writes `fill-plan.json`: every answer, the field labels each one matches, the
files to upload, and platform-specific hints for Greenhouse, Lever, Ashby and
Workday. Use it as your own checklist, or hand it to a browser agent.

It stops before the submit button. Always.

### Keep track

```bat
ja mark example-tech-security-engineer-graduate applied
ja followup
```

```
2 thing(s) need attention:

  Example Corp — Graduate Security Engineer  [discovered]  closes soon and you
      have not drafted it yet (2d left)
  Another Co — Data Engineer Graduate  [applied]  no reply since you applied — worth
      a polite follow-up (20d)
```

Statuses run `discovered` → `drafted` → `applied` → `screening` → `interview` →
`offer` / `rejected` / `withdrawn`.

---

## Reading the fit report

The percentage is the least interesting part. The three lists are the product.

```markdown
**Must-have coverage: 81.2%**  ·  overall keyword coverage 74.7%

## Hard requirements
- **[OK]** grad_year: targets [2027] — you graduate 2027

## Surface these — you have real evidence
- Python **[required]**  _(evidence: bigco.b2, scanner.b1)_
- Network Security **[required]**  _(evidence: scanner.b1)_

## Claim carefully — thin evidence
- C++ **[required]** (self-assessed: working)

## Genuine gaps — do not claim these
- code review **[required]**

> Required and missing: code review. Address these in the cover letter as
> adjacent experience, or treat the role as a stretch.

## Requirements the matcher could not read
Judge these by hand. They are not counted in the score either way:
- Comfortable operating in ambiguous, fast-moving environments
```

- **Surface these** — the posting asks for it and you can prove it. These must
  appear on your resume.
- **Claim carefully** — some exposure, thin evidence. Be ready to back it up.
- **Genuine gaps** — not in your profile. Do not claim them. If one is required,
  the report says so.
- **Requirements the matcher could not read** — the honest part. The matcher
  works from a fixed vocabulary, so when a posting uses wording it does not
  know, it tells you rather than quietly scoring around it.

It also checks the hard filters that silently disqualify people: years of
experience, degree level, graduation-year windows, work authorisation, and
security clearance.

**A low score is a useful answer.** 40% on a blockchain-heavy role when you
have never touched blockchain is correct, and it saves you an evening.

---

## Where postings come from

Three tiers, configured in `Context/sources.yaml`.

### Tier 1 — public APIs, fully automated

| Source | Why it is fair game |
|---|---|
| **MyCareersFuture** | Singapore's national portal (Workforce Singapore). Public, keyless. The richest source for local roles: a real skills taxonomy, salary bands, position levels, and expiry dates that work as true deadlines. |
| **Greenhouse** | Each company's own public board feed. |
| **Lever** | Same, and it returns plain-text descriptions. |
| **Ashby** | Same. |

Every response shape was verified against live data, and each adapter pins it
in its docstring. Run `ja sources check` to confirm your configured boards still
resolve — a wrong company token is the usual cause of a silent empty result.

**SmartRecruiters is deliberately absent**: its postings API is disallowed by
`robots.txt`, so the tool does not touch it. **Workday** is absent too — it needs
per-tenant configuration that cannot be guessed.

#### Adding companies you care about

```bat
ja sources add "Example Holdings Pte Ltd"
```

It strips legal suffixes to guess the board slug, asks Greenhouse, Lever and
Ashby whether it exists, and reports what it finds. `--write` adds the winner to
`sources.yaml`, leaving your comments intact.

No board found usually means the company runs Workday, SmartRecruiters or its
own portal, or posts only to LinkedIn and MyCareersFuture. The command says so
rather than failing silently.

### Tier 2 — your own browser

LinkedIn, JobStreet, Glassdoor and Indeed publish no job-search API, and their
terms prohibit automated scraping. So this tool does not scrape them.

1. `ja urls` builds the correct search URL with filters applied — for LinkedIn
   that means the real parameters (`f_E` for experience level, `f_TPR` for
   recency, `f_WT` for remote/hybrid, `sortBy=DD` for newest first).
2. You open it in your own signed-in browser and read the results.
3. Save them as JSON and `ja ingest` scores them exactly like the API sources.

Nothing here solves a CAPTCHA, works around a bot check, or logs in for you. A
403, a 429 or a challenge is treated as the site saying no, and that source is
skipped.

One practical note: LinkedIn treats its own filter parameters as hints and
returns roles that do not match them, so every posting is re-screened for
seniority after it arrives rather than trusted.

The capture format is documented at the top of
`src/job_applier/sources/browser.py`. Only `title` is required; JSON, JSON
Lines, CSV and TSV all work.

### Tier 3 — paste it

`ja apply -f jd.txt` always works, for the posting a friend forwarded you.

---

## Command reference

| Command | What it does |
|---|---|
| `ja init` | Check setup, create `.env` |
| `ja discover` | Search the public APIs, score, queue what fits |
| `ja urls` | Search links for the browser-only boards |
| `ja ingest -s <board> -f <file>` | Score postings captured from your browser |
| `ja sources list` | Show configured sources |
| `ja sources check` | Verify each configured board resolves |
| `ja sources add "Company"` | Find which job board a company runs on |
| `ja score -f jd.txt` | Fit report only. No documents, no API key needed |
| `ja apply -f jd.txt` | Full application pack |
| `ja apply --from-queue <slug>` | Same, for a discovered role — no paste needed |
| `ja fill <slug>` | Form fill plan that stops at submit |
| `ja status [--status X]` | The tracker |
| `ja show <slug>` | One application, with its history |
| `ja due [--days N]` | Deadlines coming up |
| `ja followup [--days N]` | What has gone quiet or is about to close |
| `ja mark <slug> <status>` | Update a status |

Useful flags for `apply`: `--pages 2` (keep more content), `--no-llm` (skip the
model), `--no-cover-letter`, `--no-pdf`, `--deadline YYYY-MM-DD`.

Useful flags for `discover` and `ingest`: `--show-rejected`, `--dry-run`,
`--min-score N`, `--max-years N`. `discover` also takes `--limit N` and
`--keep-blocked` (show roles with a hard blocker anyway).

---

## Configuration

### `.env` — secrets and output settings

```ini
JA_PROVIDER=anthropic          # anthropic | ollama | none
ANTHROPIC_API_KEY=             # paste a key here, or leave blank
JA_MODEL=claude-sonnet-5-5
JA_MAX_PAGES=1                 # resume page target, enforced
JA_BULLETS_PER_ROLE=3
JA_OLLAMA_HOST=http://localhost:11434
JA_DB_PATH=                    # optional: move the tracker off a synced drive
```

### Do I need an API key?

No. Without one the tool runs in **no-model mode**: it still scores fit, still
picks the right bullets for each posting, still builds every document — it just
reuses your original wording instead of rewriting it per role. The gap reports
are identical.

With a key, bullets get rephrased to match the posting's language (within the
grounding rules) and you get a real cover letter.

Prefer to keep everything local? Set `JA_PROVIDER=ollama` and run `ollama serve`.
Nothing leaves your machine.

### `Context/sources.yaml` — where to search

```yaml
search_terms:
  - security engineer graduate
  - data engineer graduate

screening:
  max_years_experience: 2      # drop postings asking for more
  min_required_score: 45       # drop postings below this coverage
  max_per_source: 300

company_boards:
  - ats: greenhouse
    token: example-corp
    company: Example Corp
```

Tune `min_required_score` to taste. Too high and you miss stretch roles worth a
shot; too low and you drown. Start at 45 and adjust once you have seen a week of
results.

### Page length

`JA_MAX_PAGES` is a constraint, not a wish. The resume is rendered, the PDF is
measured, and if it runs over, content is trimmed and measured again.

Trimming only ever **removes** — nothing is reworded — so a fitted resume is
exactly as truthful as the full one. What goes first is what a reader values
least, and a whole irrelevant role goes before a bullet is shaved off a relevant
one:

```
summary → extra activities → extra projects → the least relevant whole role
→ bullets on weaker roles → courses, coursework, languages
```

The two most recent roles keep at least two bullets each while anything else can
still be given up. Everything removed is listed, so you can see the cost:

```
[ok] Resume is 1 page(s), after trimming 12 item(s) to reach 1
     trimmed to fit: activity: Example CTF; project: Chatbot; role: Tuition Teacher ...
     keep it all with: --pages 2
```

---

## Troubleshooting

**`Profile not found` / `ja init` fails**
You have not created `Context/profile.yaml` yet. Copy
`Context/profile.example.yaml` and fill it in.

**`ja discover` returns nothing**
Run `ja sources check`. A company board with a wrong token fails silently during
discovery but is reported there. Also try `--show-rejected` — your
`min_required_score` may simply be too high.

**`ja sources add` finds no board**
That company probably uses Workday, SmartRecruiters or its own portal. Open
their careers page, follow the redirect, and read the slug out of the URL.

**No PDF is produced**
No converter is installed. Install LibreOffice, or just upload the `.docx` —
most application systems prefer it. Page length will be estimated rather than
measured, and the output says so.

**`Documents are saved, but the tracker could not be updated`**
SQLite cannot lock files on some network and synced drives. Set `JA_DB_PATH` in
`.env` to a local path.

**A posting scores lower than it should**
The matcher works from a fixed vocabulary. Check the "Requirements the matcher
could not read" section — if the posting's wording is unusual, that is why.
Adding good `aliases` to your skills helps a lot.

**A generated bullet reverted to my original wording**
That rewrite failed the grounding check. `grounding.md` says exactly which claim
and why. This is the system working.

---

## Privacy

Your resume, transcript, profile, generated documents, tracker and API key are
all gitignored and never leave your machine, except for job-description text
sent to your configured model provider — or nothing at all, if you use Ollama or
no model.

If you fork this, check `git status` before your first commit. `profile.yaml`
holds your phone number and email.

---

## How it works

```
job_applier/
├── Context/
│   ├── Files/                  your resume + transcript           (gitignored)
│   ├── profile.yaml            YOUR PROFILE — source of truth     (gitignored)
│   ├── profile.example.yaml    the template to copy
│   └── sources.yaml            where to search, screening thresholds
├── src/job_applier/
│   ├── profile.py              loads and indexes your profile by bullet id
│   ├── lexicon.py              technical vocabulary for matching
│   ├── jd.py                   posting intake and section tagging
│   ├── ats.py                  matching, gap report, hard filters
│   ├── filters.py              new-grad screening, with reasons
│   ├── verify.py               the grounding checks
│   ├── tailor.py               bullet selection and rewriting
│   ├── cover_letter.py         letter generation
│   ├── render.py               DOCX / PDF / TXT / MD output
│   ├── pagefit.py              measures and enforces the page target
│   ├── formfill.py             human-readable answer sheet
│   ├── fillplan.py             machine-readable fill plan
│   ├── discover.py             fetch → merge → screen → score → rank → queue
│   ├── net.py                  polite HTTP: robots.txt, rate limits
│   ├── boardlookup.py          finds a company's job board
│   ├── followup.py             deadline and silence nudges
│   ├── tracker.py              SQLite tracker and event log
│   ├── sources/                one adapter per job board
│   └── cli.py                  the commands
├── prompts/                    prompt templates, editable
├── samples/                    example job description and capture file
└── applications/               your output                        (gitignored)
```

The pipeline is deterministic end to end except for the optional rewriting step:
the same postings always produce the same queue, and every rejection carries a
reason you can read back.

---

## Contributing

```bash
python -m unittest discover -s tests
```

137 tests. The ones that matter most:

- **Grounding tests** — these stop a fabricated claim reaching a document. If
  you change `verify.py`, these are the contract.
- **Source parser fixtures** — copied from live API responses, so a provider
  changing its shape fails here rather than mid-run.

If you add a job board, subclass `sources.base.Source`, normalise into
`Posting`, and add a fixture test from a real response. If the board has no
public API, it belongs in the browser-assisted tier — do not add a scraper.
