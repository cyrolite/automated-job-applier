# job_applier

Job application tooling that drafts and fills, and stops at the submit button.

Point it at a job posting. It tells you honestly how well you fit, writes a resume
and cover letter tailored to that posting, and gives you a copy-paste sheet for the
online form. You read it, you submit it.

**It cannot make things up.** Every line on a generated resume is traced back to a
specific bullet in `Context/profile.yaml` and checked before it reaches a document.
Inflated numbers, invented tools and skills attributed to the wrong employer are
blocked automatically, and the original wording is used instead.

---

## Setup

Double-click **`setup.bat`**, or from a terminal in this folder:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m job_applier init
```

Then open `.env` and paste an API key on the `ANTHROPIC_API_KEY=` line
(get one at https://console.anthropic.com/settings/keys).

You do not have to. Without a key the tool runs in **no-model mode**: it still
scores fit, still picks the right bullets for each role, still builds the
documents — it just reuses your original wording rather than rewriting it.
If you would rather keep everything local, set `JA_PROVIDER=ollama` in `.env`
and run `ollama serve`.

---

## Using it

```bat
REM 1. Find roles. Hits the public job APIs, scores each against your
REM    profile, queues what fits.
ja discover

REM 2. Boards that need your own browser (LinkedIn, JobStreet, Indeed,
REM    Glassdoor). This prints the search links; you open them.
ja urls
ja ingest -s linkedin -f capture.json

REM 3. See the queue, best fit first
ja status --status discovered

REM 4. Is one worth applying to?
ja score -f jd.txt

REM 5. Build the full pack
ja apply -f jd.txt -c "Acme Corp" --title "Security Engineer" --deadline 2026-12-15

REM 6. Get a form fill plan for it
ja fill acme-corp-security-engineer

REM 7. What has gone quiet or is about to close
ja followup

REM 8. After you hit submit
ja mark acme-corp-security-engineer applied
```

Without the `ja.bat` wrapper, every command is `python -m job_applier ...`
with `PYTHONPATH` set to `src`.

### What `apply` produces

One folder per application under `applications/`:

| File | What it is |
|---|---|
| `fit-report.md` | Must-have coverage, what to surface, what you genuinely lack |
| `resume.docx` | The file to upload. ATS-safe: one column, no tables, no images |
| `resume.pdf` | Same, converted if Word or LibreOffice is available |
| `resume.txt` | Plain text, for "paste your resume" boxes |
| `resume.md` | Quick read |
| `cover-letter.docx` / `.txt` | Short, specific, no filler |
| `form-answers.md` | Every field the form will ask for, filled in |
| `grounding.md` | Which claims were checked, and anything that failed |
| `jd.txt` | The posting, kept for the record |

---

## The fit report

The score is not the point. The three lists are:

- **Surface these** — the posting asks for it and you have real evidence. These
  must appear on the resume.
- **Claim carefully** — you have some exposure but thin evidence.
- **Genuine gaps** — not in your profile. Do not claim these. If one is required,
  the report says so, and the cover letter addresses the nearest real adjacent
  experience instead.

It also checks the hard filters that silently disqualify people: years of
experience, degree level, graduation year window, work authorisation, security
clearance.

---

## `Context/profile.yaml`

The one file worth editing by hand. Everything else is generated from it.

Every bullet has a stable id (`tiktok.b2`, `pentest_ai.b1`). Generated documents
cite those ids, which is what makes verification possible. Skills carry a
self-assessed level and an `evidence` list pointing at the bullets that prove
them — a skill with evidence outranks one with only a level.

When something changes — a new project, a new internship, a better number —
add it here and every future application picks it up.

---

## Layout

```
job_applier/
├── Context/
│   ├── Files/              your resume + transcript PDFs
│   └── profile.yaml        MASTER PROFILE — source of truth
├── src/job_applier/
│   ├── config.py           paths + settings from .env
│   ├── profile.py          loads and indexes the profile
│   ├── lexicon.py          281-term technical vocabulary
│   ├── jd.py               posting intake and sectioning
│   ├── ats.py              matching + gap report (no model needed)
│   ├── llm.py              anthropic | ollama | none
│   ├── tailor.py           bullet selection and rewriting
│   ├── cover_letter.py     letter generation
│   ├── verify.py           the grounding checks
│   ├── render.py           DOCX / PDF / TXT / MD output
│   ├── formfill.py         the form answer sheet
│   ├── tracker.py          SQLite application tracker
│   └── cli.py              commands
├── prompts/                prompt templates, editable
├── applications/           output, one folder per role
├── data/tracker.db         the tracker
├── PROGRESS.md             build log — read this when resuming
└── .env                    your settings (gitignored)
```

---

## Where postings come from

Three tiers, in `Context/sources.yaml`.

### Tier 1 — public APIs, fully automated

| Source | Endpoint | Why it is fair game |
|---|---|---|
| **MyCareersFuture** | `api.mycareersfuture.gov.sg/v2/jobs` | Singapore's national portal (Workforce Singapore). Public, keyless. The richest source for local roles: a real skills taxonomy, SGD salary bands, position levels and an expiry date that works as a true deadline. |
| **Greenhouse** | `boards-api.greenhouse.io/v1/boards/{token}/jobs` | Each company's own public board feed. |
| **Lever** | `api.lever.co/v0/postings/{token}` | Same, and it returns plain-text descriptions. |
| **Ashby** | `api.ashbyhq.com/posting-api/job-board/{token}` | Same. |

Every response shape above was checked against live data, and the adapters
pin it in their docstrings. Run `ja sources check` to confirm each configured
board still resolves — a wrong company token is the usual cause of a silent
empty result.

**SmartRecruiters is deliberately absent.** Its postings API is disallowed by
`robots.txt`, so the tool does not touch it. Workday is absent too: it needs
per-tenant configuration that cannot be guessed.

### Tier 2 — your own browser

LinkedIn, JobStreet, Glassdoor and Indeed publish no job-search API, and their
terms of use prohibit automated scraping. So this tool does not scrape them.
What it does instead:

1. `ja urls` builds the correct search URL, filters and all. For LinkedIn that
   means the real parameters — `f_E=1,2` for internship and entry level,
   `f_TPR=r604800` for the past week, `f_WT` for on-site/remote/hybrid,
   `sortBy=DD` for newest first.
2. You open it in your own signed-in browser, or the browser agent does, at
   human pace, reading pages you are entitled to see.
3. The postings come back as JSON and `ja ingest` scores them exactly like the
   API sources.

Nothing in the tool solves a CAPTCHA, works around a bot check or logs in for
you. A 403, a 429 or a challenge is treated as the site saying no, and that
source is skipped. One practical note: LinkedIn treats its own filter
parameters as hints and returns roles that do not match them, so every posting
is re-screened for seniority after it arrives rather than trusted.

The capture format is documented at the top of `src/job_applier/sources/browser.py`.
Only `title` is required; JSON, JSON Lines, CSV and TSV all work.

### Tier 3 — paste it

`ja apply -f jd.txt` always works, for the posting a friend forwarded you.

---

## Screening

No board filters new-grad roles reliably, so the tool judges each posting
itself, and every decision carries a reason you can read back:

- **Title seniority** — "Senior", "Staff", "Head of", "Manager", "Engineer III"
  are dropped, unless the title also says graduate.
- **Stated experience** — anything above `max_years_experience` goes. The
  parser understands that "under 2 years of full-time experience" is a
  *ceiling* on a graduate posting, not a two-year requirement.
- **Hard blockers** — a graduation-year window you miss, a clearance you
  cannot hold.
- **Fit threshold** — below `min_required_score` must-have coverage, it is not
  worth your evening.

`ja discover --show-rejected` lists everything that was screened out and why,
so you can argue with it. Both numbers live in `Context/sources.yaml`.

## Duplicates

The same role shows up on four boards. They collapse into one entry, and
merging **adds** information rather than losing it: the surviving posting keeps
the most direct apply link (a company ATS over an aggregator), takes the
richest description found anywhere, and fills blank fields — deadline, salary,
employment type — from whichever board knew them. `also on: indeed, linkedin`
tells you where else it appeared.

## Page length

`JA_MAX_PAGES` is a constraint, not a wish. The resume is rendered, the PDF is
measured, and if it runs over, content is trimmed and it is measured again.

Trimming only ever **removes**; nothing is reworded, so a fitted resume is
exactly as truthful as the full one. What goes first is what a reader values
least, and a whole irrelevant role goes before a bullet is shaved off a
relevant one:

```
summary -> extra activities -> extra projects -> the least relevant whole role
-> bullets on weaker roles -> courses, coursework, languages
```

The two most recent roles keep at least two bullets each while anything else
can still be given up. Everything removed is listed, so you can see what one
page costs:

```
[ok] Resume is 1 page(s), after trimming 12 item(s) to reach 1
     trimmed to fit: activity: STANDCON CTF; project: Scooby Chatbot; ...
     keep it all with: --pages 2
```

`--pages 2` or `--no-fit` overrides it. If no PDF converter is installed the
length is estimated and the output says so rather than implying a measurement
that never happened.

## Finding a company's board

`sources.yaml` is only as useful as the company tokens in it, and finding those
by hand means opening a careers page, following a redirect and reading a slug
out of a URL.

```bat
ja sources add "Shopee Singapore Private Limited"
```

It strips legal suffixes (`Pte Ltd`, `Private Limited`, `Holdings Inc`) to guess
the slug, then asks Greenhouse, Lever and Ashby whether it exists — a handful of
rate-limited requests. `--write` adds the winner to `sources.yaml`, leaving every
comment in place.

No board found usually means the company runs Workday, SmartRecruiters or its own
portal, or posts only to LinkedIn and MyCareersFuture. The command says so rather
than failing silently.

## The fill plan

`ja fill <slug>` writes `fill-plan.json` into the application folder: every
answer, the labels each one should be matched against, the field kind, the
files to upload, and per-platform selector hints for Greenhouse, Lever, Ashby
and Workday.

`stop_before_submit` is always true. The plan also carries a `never_do` list —
no submitting, no consent checkboxes, no demographic questions, no CAPTCHA
solving, no account creation. Hand the file to the browser agent, or use it as
your own checklist.

The last click is yours. That is not a missing feature: an auto-submitted
application is one you never read, sent under your name, and most boards'
terms prohibit it.

---

## What this deliberately does not do

It does not submit applications. Auto-submitting means sloppy applications going
out under your name, and it breaches the terms of most job boards. The agent gets
you to a filled form you can check in a few seconds.

It does not pad your resume. If you lack a required skill, the report says so.

---

## Commands

| Command | What it does |
|---|---|
| `ja init` | Check setup, create `.env` |
| `ja sources list` / `check` | Show configured sources, or verify each one resolves |
| `ja discover` | Search the public APIs, score, queue what fits |
| `ja urls` | Search links for the browser-only boards |
| `ja ingest -s <board> -f <file>` | Score postings captured from your browser |
| `ja score -f jd.txt` | Gap report only, no documents, no model needed |
| `ja apply -f jd.txt` | Full application pack |
| `ja apply --from-queue <slug>` | Same, for a role already discovered — no paste |
| `ja sources add "Company"` | Find which job board a company runs on |
| `ja fill <slug>` | Form fill plan that stops at submit |
| `ja status [--status X]` | The tracker |
| `ja show <slug>` | One application, with history |
| `ja due [--days N]` | Deadlines coming up |
| `ja followup [--days N]` | What has gone quiet or is about to close |
| `ja mark <slug> <status>` | Update status |

Statuses: `discovered` → `drafted` → `applied` → `screening` → `interview` →
`offer` / `rejected` / `withdrawn`.

## Tests

```bat
python -m unittest discover -s tests
```

137 tests. The ones that matter most are the grounding checks, which stop a
fabricated claim reaching a document, and the source-parser fixtures, which are
copied from live API responses so a provider changing its shape fails here
rather than mid-run.
