# job_applier — build log

Running record of what exists, what is next, and the decisions behind it.
Read this first when resuming after a break.

**Last updated:** 2026-11-12 (Asia/Singapore)
**Status:** Phase 1, Phase 2 and a round of defect fixes complete. 137/137 tests pass.

---

## The decisions already made

| Decision | Choice |
|---|---|
| Target roles | New grad full-time 2027 start; graduate / rotational programmes; open to overseas + remote |
| Autonomy | Agent discovers, drafts and fills; **you click submit.** Nothing auto-submits. |
| Grounding rule | Generation may only select and rephrase bullets that exist in `Context/profile.yaml`. It can never invent a claim. |
| Scraping stance | Public APIs only. Boards whose terms prohibit scraping go through your own browser. `robots.txt` is honoured; a 403 or a CAPTCHA is treated as "no". |

## Where to start when you come back

```bat
setup.bat                 REM one time
ja sources check          REM confirm every board still resolves
ja discover               REM find and queue roles
ja status --status discovered
ja apply -f jd.txt -c "Company" --title "Role"
ja fill <slug>
ja followup
```

The only thing still outstanding: paste an API key into `.env` on the
`ANTHROPIC_API_KEY=` line. Everything runs without it in no-model mode.

---

## Architecture

```
job_applier/
├── Context/
│   ├── Files/                  Resume + Transcript PDFs            (gitignored)
│   ├── profile.yaml            MASTER PROFILE — source of truth    (gitignored)
│   └── sources.yaml            where postings come from, screening thresholds
├── src/job_applier/
│   ├── config.py               paths + settings from .env, JA_DB_PATH override
│   ├── profile.py              loads + indexes the profile by bullet id
│   ├── lexicon.py              ~320 terms; checkable skills vs JD boilerplate
│   ├── jd.py                   posting intake + section tagging
│   ├── ats.py                  matching, gap report, hard-filter detection
│   ├── llm.py                  anthropic | ollama | none
│   ├── verify.py               grounding checks — the safety net
│   ├── tailor.py               bullet selection + rewriting, and a no-model mode
│   ├── cover_letter.py         letters under the same grounding rules
│   ├── render.py               ATS-safe DOCX / PDF / TXT / MD
│   ├── formfill.py             the human-readable form answer sheet
│   ├── fillplan.py             machine-readable fill plan for the browser agent
│   ├── tracker.py              SQLite tracker + event log
│   ├── net.py                  polite HTTP: robots.txt, rate limit, honest UA
│   ├── filters.py              new-grad screening, with reasons
│   ├── discover.py             fetch -> merge -> screen -> score -> rank -> queue
│   ├── search_urls.py          correct search URLs for browser-only boards
│   ├── followup.py             nudges off the tracker
│   ├── sources/                base, greenhouse, lever, ashby,
│   │                           mycareersfuture, browser, registry
│   └── cli.py                  13 commands
├── prompts/                    editable prompt templates
├── samples/                    example JD + example browser capture
├── tests/                      test_core.py (35) + test_phase2.py (72)
├── applications/               output, one folder per role               (gitignored)
└── data/tracker.db                                                      (gitignored)
```

---

## Build status

### Phase 1 — done
Master profile (34 ID'd bullets, 28 skills with evidence links), ATS matcher and
gap report, grounded tailoring with a verifier that blocks inflated numbers and
invented tools, ATS-safe DOCX/PDF/TXT rendering, form answer sheet, SQLite
tracker, CLI, setup scripts. Verified end to end against a real posting.

### Phase 2 — done

- [x] **`net.py`** — every request honours `robots.txt`, spaces out per host,
      and identifies itself. 401/403/429/451 raise `Blocked` and the source is
      skipped, never retried or worked around.
- [x] **Four source adapters**, each verified against live API responses:
      MyCareersFuture (Singapore's national portal — skills taxonomy, SGD
      salary bands, real deadlines), Greenhouse, Lever, Ashby.
- [x] **`filters.py`** — new-grad screening by title seniority, level markers
      and stated experience. Understands that "under 2 years" is a ceiling, not
      a requirement. Every decision carries a reason.
- [x] **`discover.py`** — fetch, merge duplicates across boards, screen, score,
      drop blockers and weak fits, rank, write to the tracker. No model involved,
      so the same postings always give the same queue.
- [x] **`search_urls.py`** — correct search URLs for LinkedIn (verified filter
      codes: `f_E`, `f_TPR`, `f_WT`, `f_JT`, `sortBy=DD`), JobStreet, Indeed,
      Glassdoor, MyCareersFuture web.
- [x] **`sources/browser.py`** — the browser-assisted path. Builds URLs, refuses
      to fetch, and normalises captured JSON/JSONL/CSV/TSV into the same model.
- [x] **`fillplan.py`** — machine-readable fill plan with label patterns, field
      kinds, file paths and per-ATS selector hints. `stop_before_submit` always
      true, plus an explicit `never_do` list.
- [x] **`followup.py`** — deadline and silence nudges off the tracker.
- [x] **CLI** — added `discover`, `urls`, `ingest`, `sources`, `fill`, `followup`.
- [x] **Tests** — 72 new, 107 total.
- [x] **Verified on live data** — real MyCareersFuture results for 2027 graduate
      security roles were run through the real pipeline end to end.

### Post-Phase-2 defect fixes — done

Found by auditing the working system rather than by adding features.

- [x] **Discovery threw away the job description it had just fetched.** The
      tracker had nowhere to put it, so `apply` made you paste the same text
      back by hand. Added a `postings` table and `ja apply --from-queue <slug>`:
      a queued role now goes straight to documents. On the real ByteDance
      posting this also showed the earlier caveat was right — scoring the full
      description gives 81%, where the skills list alone gave 50%.
- [x] **`JA_MAX_PAGES` was a wish, not a constraint.** It was passed into the
      prompt and never measured; the generated resume was 2 pages. Added
      `pagefit.py`: render, measure the PDF with pypdf, trim the least valuable
      content, measure again. Trimming only removes, never rewords, so a fitted
      resume stays as truthful as the full one. Everything cut is reported, and
      `--pages 2` / `--no-fit` override it.
- [x] **Ranking scored a Java address-book project above an AI security project
      on a security posting**, because both merely said "Java". Added domain
      affinity: a posting's subject area is derived from the lexicon group of
      every term it matches — including terms the candidate lacks, since a
      posting demanding smart contracts is a blockchain posting either way.
      Security work now outranks generic work on security postings. On the
      crypto role, PassManager (AES) went from 5th to 1st and the AI pentest
      assistant from 7th to 2nd.
- [x] **Security boilerplate was excluded from domain detection.** Phrases like
      "security testing" and "security governance" prove nothing about a
      candidate — correct to keep out of gap reports — but they are the clearest
      signal that a posting is a security posting. Split out so they inform the
      domain without ever appearing as a claimed skill.
- [x] **`sources.yaml` shipped with three placeholder companies**, so discovery
      stayed weak until tokens were hand-found. Added `ja sources add "Company"`:
      strips legal suffixes, probes Greenhouse/Lever/Ashby, and with `--write`
      inserts the result while preserving every comment in the file. Verified
      against a live board — guessing "stripe" from "Stripe" finds 159 postings.
- [x] **A 404 was reported as an error.** A company that runs no board on a
      platform is a normal answer, so `net.NotFound` is now distinct from
      `Blocked`, and `ja sources check` says "no board at this token".

### Deliberately excluded
- **SmartRecruiters** — its postings API is disallowed by `robots.txt`.
- **Workday** — needs per-tenant configuration that cannot be guessed. The fill
  plan still supports Workday forms (match on visible label, not selector).
- **Auto-submit** — out of scope by design, not by omission.

### Bugs found and fixed
Phase 1: generic-term weighting compounded across terms on one line; evidence
ranking was order-dependent; JD boilerplate was reported as missing skills;
singular/plural counted twice; a tracker failure could abort `apply` after
documents were written; `init` crashed when `JA_DB_PATH` sat outside the project;
LibreOffice temp files were left behind.

Phase 2: the fill plan referenced a profile key that never existed, so the
transcript was never attached — now read from `Context/Files`.

---

## Phase 3 — candidates, in rough value order

- [ ] **LLM requirement extraction** (biggest remaining win). Scoring rests on a
      ~320-term lexicon, so a posting phrased unusually scores on the terms it
      happens to share. `unmatched` reports the blind spot honestly, and domain
      affinity softens it, but the real fix is: when a provider is configured,
      have the model extract the requirement list from the JD and match against
      that, falling back to the lexicon when there is no key. Everything
      downstream — ranking, trimming, the gap report — gets better at once.
- [ ] **Interview prep sheet** — likely questions from the JD crossed with the
      evidence bullets that answer them, written into the application folder.
      Cheap, and the material is already assembled by then.
- [ ] **Scheduled discovery** — a recurring task that runs `ja discover` and
      pushes only genuinely new high-fit roles, so a deadline like the
      ByteDance one (found with two days left) surfaces on the day it appears.
- [ ] **Outcome learning** — once there are enough applied/rejected outcomes,
      check which fit-score bands actually convert and recalibrate
      `min_required_score` from data instead of a guess.
- [ ] **Referral finder** — surface NUS alumni at a target company from your own
      LinkedIn connections, through the browser, for a warm intro.
- [ ] **Cover-letter gap handling** — when a required skill is genuinely missing,
      the letter should name the nearest real adjacent experience explicitly.
      The prompt allows it; nothing verifies it happened.

---

## Notes to self
- Windows machine: all paths stay `pathlib`-based.
- `Context/profile.yaml` is the one file worth editing by hand. Add every new
  project, number and internship there; all future applications pick it up.
- `Context/sources.yaml` is the second. Add the companies you actually target,
  then run `ja sources check` — a wrong token fails silently otherwise.
- The fit score is not the product. The three lists — surface these, claim
  carefully, genuine gaps — are. A low score on a crypto-native or Go-heavy role
  is the correct, useful answer.
- Scores depend on how much JD text a source gives. A skills-list-only posting
  scores lower than the same role with its full description, so `ja apply -f`
  with the full text is always the better read before deciding.
- `applications/` holds sample runs plus two stray LibreOffice files
  (`.~lock.resume.pdf#`, `lu44hr1f.tmp`) that the build environment could not
  delete. Safe to delete the whole folder.
