"""Command line interface.

    python -m job_applier init
    python -m job_applier score  --file jd.txt
    python -m job_applier apply  --file jd.txt --company "Acme" --title "Security Engineer"
    python -m job_applier status
    python -m job_applier mark acme-security-engineer applied
    python -m job_applier show acme-security-engineer
    python -m job_applier due --days 7
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

from . import ats, boardlookup, discover as discovery, fillplan, formfill, followup, pagefit, render, search_urls
from .config import settings
from .cover_letter import CoverLetter
from .cover_letter import write as write_cover_letter
from .jd import JobDescription
from .llm import LLMUnavailable, get_client
from .net import NotFound
from .profile import Profile
from .sources.browser import BROWSER_BOARDS, load_capture
from .sources.registry import SourceConfig
from .tailor import TailoredResume, tailor, tailor_deterministic
from .tracker import STATUSES, Tracker

OK, WARN, BAD = "[ok]", "[!]", "[x]"


def _rel(path: Path) -> str:
    """Show a short path when it is inside the project, else the full one.
    JA_DB_PATH may legitimately point somewhere else entirely."""
    try:
        return str(Path(path).relative_to(settings.root))
    except ValueError:
        return str(path)


# ----------------------------------------------------------------------
def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h[1-6]>", "\n", html)
    html = re.sub(r"(?i)<li[^>]*>", "- ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = (
        text.replace("&amp;", "&").replace("&nbsp;", " ")
        .replace("&lt;", "<").replace("&gt;", ">")
        .replace("&#39;", "'").replace("&quot;", '"')
    )
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
    return "\n".join(l for l in lines if l)


def _jd_from_queue(slug: str) -> tuple[JobDescription, dict]:
    """Rebuild a JD from a posting discovery already fetched."""
    data = Tracker().get_posting(slug)
    if data is None:
        print(f"{BAD} No stored posting for {slug!r}.")
        print("    `apply --from-queue` only works for roles found by `ja discover`")
        print("    or `ja ingest`. See: ja status --status discovered")
        sys.exit(2)
    body = data.get("description") or data.get("title") or ""
    if not body.strip():
        print(f"{BAD} The stored posting for {slug!r} has no text to work from.")
        sys.exit(2)
    jd = JobDescription.from_text(
        body,
        title=data.get("title") or "",
        company=data.get("company") or "",
        location=data.get("location") or "",
        url=data.get("url") or data.get("apply_url") or "",
    )
    return jd, data


def _load_jd(args: argparse.Namespace) -> JobDescription:
    if getattr(args, "from_queue", None):
        jd, _ = _jd_from_queue(args.from_queue)
        return jd
    kw = dict(title=args.title or "", company=args.company or "",
              location=args.location or "", url=args.url or "")
    if args.file:
        jd = JobDescription.from_file(args.file, **kw)
    elif args.text:
        jd = JobDescription.from_text(args.text, **kw)
    elif args.url:
        print(f"Fetching {args.url} ...")
        try:
            req = urllib.request.Request(
                args.url, headers={"User-Agent": "Mozilla/5.0 (job_applier)"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", errors="replace")
            body = _strip_html(html)
            if len(body) < 400:
                raise ValueError("page returned too little text (likely JavaScript-rendered)")
            jd = JobDescription.from_text(body, **kw)
        except Exception as e:
            print(f"{BAD} Could not read the posting: {e}")
            print("    Most job boards render with JavaScript. Copy the posting text")
            print("    into a file and use --file instead.")
            sys.exit(2)
    elif not sys.stdin.isatty():
        jd = JobDescription.from_text(sys.stdin.read(), **kw)
    else:
        print(f"{BAD} Give a job description: --file jd.txt, --text \"...\", --url ..., or pipe it in.")
        sys.exit(2)

    if not jd.full_text.strip():
        print(f"{BAD} The job description is empty.")
        sys.exit(2)
    return jd


def _resolve_client(no_llm: bool):
    if no_llm:
        return None
    if not settings.llm_available():
        print(f"{WARN} No LLM provider configured, so falling back to no-model mode.")
        print("    Your bullets keep their original wording, re-ordered for the role.")
        print("    Run: python -m job_applier init    to set a provider up.")
        return None
    try:
        return get_client()
    except LLMUnavailable as e:
        print(f"{WARN} {e}")
        print("    Falling back to no-model mode.")
        return None


# ----------------------------------------------------------------------
def cmd_init(args: argparse.Namespace) -> int:
    settings.ensure_dirs()
    print(f"{OK} Folders ready: applications/, data/, prompts/")

    env = settings.root / ".env"
    example = settings.root / ".env.example"
    if not env.exists() and example.exists():
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"{OK} Created .env from .env.example")
    elif env.exists():
        print(f"{OK} .env already exists")

    try:
        p = Profile.load()
        print(f"{OK} Profile loads: {len(p.bullets)} bullets, {len(p.skills)} skills")
    except Exception as e:
        print(f"{BAD} Profile problem: {e}")
        return 1

    if settings.llm_available():
        print(f"{OK} LLM provider: {settings.provider} ({settings.model})")
    else:
        print(f"{WARN} No LLM provider configured. Everything still runs in no-model mode.")
        print("    For tailored phrasing, put a key in .env:  ANTHROPIC_API_KEY=sk-ant-...")
        print("    Or run a local model instead:               JA_PROVIDER=ollama")

    Tracker()
    print(f"{OK} Tracker ready at {_rel(settings.db_path)}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    jd = _load_jd(args)
    report = ats.match(jd, Profile.load())
    print()
    print(report.to_markdown())
    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.to_markdown(), encoding="utf-8")
        print(f"{OK} Saved to {out}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    profile = Profile.load()

    queued: dict = {}
    if getattr(args, "from_queue", None):
        jd, queued = _jd_from_queue(args.from_queue)
        # Keep the slug the queue already uses, so the folder, the tracker row
        # and the posting all stay pointing at the same thing.
        args.slug = args.slug or args.from_queue
        args.deadline = args.deadline or (queued.get("deadline") or None)
        print(f"{OK} Using the posting discovery already fetched "
              f"({len(jd.full_text)} characters, from {queued.get('source','?')})")
    else:
        jd = _load_jd(args)

    report = ats.match(jd, profile)

    slug = args.slug or jd.slug()
    folder = settings.applications_dir / f"{date.today().isoformat()}-{slug}"
    folder.mkdir(parents=True, exist_ok=True)

    print(f"\n{OK} {jd.company or '(company)'} — {jd.title or '(role)'}")
    print(f"    must-have coverage {report.required_score}%  ·  overall {report.score}%")
    for h in report.hard_requirements:
        mark = {"ok": OK, "check": WARN, "blocker": BAD}[h.verdict]
        print(f"    {mark} {h.kind}: {h.detail}")

    missing_required = [m.term for m in report.by_status(ats.MISSING) if m.required]
    if missing_required:
        print(f"    {WARN} required but missing: {', '.join(missing_required)}")

    client = _resolve_client(args.no_llm)

    # --- resume ---
    if client:
        print("\nTailoring resume ...")
        try:
            tailored: TailoredResume = tailor(jd, profile, client, report)
        except Exception as e:
            print(f"{WARN} Generation failed ({e}). Falling back to no-model mode.")
            tailored = tailor_deterministic(jd, profile, report)
    else:
        tailored = tailor_deterministic(jd, profile, report)

    # --- cover letter ---
    letter: CoverLetter | None = None
    if client and not args.no_cover_letter:
        print("Writing cover letter ...")
        try:
            letter = write_cover_letter(jd, profile, client, report)
        except Exception as e:
            print(f"{WARN} Cover letter failed: {e}")

    # --- write everything out ---
    (folder / "jd.txt").write_text(jd.full_text, encoding="utf-8")
    (folder / "fit-report.md").write_text(report.to_markdown(), encoding="utf-8")

    target_pages = args.pages or settings.max_resume_pages
    fit = None
    if args.no_fit:
        resume_docx = render.render_resume_docx(tailored, profile, folder / "resume.docx")
        pdf = None if args.no_pdf else render.to_pdf(resume_docx)
    else:
        # Trim to the page target before writing the text versions, so every
        # format shows the same resume.
        fit = pagefit.render_fitted(
            tailored, profile, folder / "resume.docx",
            max_pages=target_pages, want_pdf=not args.no_pdf,
        )
        resume_docx, pdf = fit.docx, fit.pdf

    resume_text = render.render_resume_text(tailored, profile)
    (folder / "resume.txt").write_text(resume_text, encoding="utf-8")
    (folder / "resume.md").write_text(
        render.render_resume_markdown(tailored, profile), encoding="utf-8"
    )

    if letter:
        render.render_cover_letter_docx(letter, profile, jd, folder / "cover-letter.docx")
        (folder / "cover-letter.txt").write_text(letter.to_text(), encoding="utf-8")
        if not args.no_pdf:
            render.to_pdf(folder / "cover-letter.docx")

    (folder / "form-answers.md").write_text(
        formfill.build(jd, profile, tailored, letter, resume_text), encoding="utf-8"
    )

    grounding = tailored.verification
    if letter:
        grounding.extend(letter.verification)
    (folder / "grounding.md").write_text(grounding.to_markdown(), encoding="utf-8")

    # --- tracker ---
    # The documents are already on disk at this point, so a tracker problem is
    # reported and stepped over rather than allowed to lose the work.
    try:
        tr = Tracker()
        tr.upsert(
            slug,
            company=jd.company,
            title=jd.title,
            location=jd.location,
            url=jd.url,
            status="drafted",
            fit_score=report.score,
            required_score=report.required_score,
            folder=_rel(folder),
            deadline=args.deadline,
        )
        tr.log(slug, "drafted", f"{tailored.bullet_count} bullets, {len(tailored.all_sections)} sections")
    except Exception as e:
        print(f"\n{WARN} Documents are saved, but the tracker could not be updated: {e}")
        print("    If this folder is on a network or synced drive, SQLite cannot lock there.")
        print("    Set JA_DB_PATH in .env to a local path, e.g. %USERPROFILE%\\job_applier.db")

    # --- summary ---
    print(f"\n{OK} Documents in {_rel(folder)}")
    for name in sorted(p.name for p in folder.iterdir()):
        print(f"    {name}")

    if fit is not None:
        print()
        print(f"{OK if fit.fitted else WARN} {fit.message()}")
        if fit.trimmed:
            print(f"    trimmed to fit: {'; '.join(fit.trimmed[:6])}"
                  + (" ..." if len(fit.trimmed) > 6 else ""))
            print(f"    keep it all with: --pages 2")

    if grounding.errors:
        print(f"\n{WARN} {len(grounding.errors)} claim(s) failed the grounding check and were")
        print("    replaced with your original wording. See grounding.md.")
    else:
        print(f"\n{OK} Grounding check passed — every claim traces back to your profile.")
    if grounding.warnings:
        print(f"{WARN} {len(grounding.warnings)} item(s) worth eyeballing in grounding.md")
    if tailored.notes:
        print(f"\nNote: {tailored.notes}")

    print(f"\nNext: read fit-report.md, check resume.docx, then apply and run")
    print(f"    python -m job_applier mark {slug} applied")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    tr = Tracker()
    apps = tr.list(status=args.status)
    if not apps:
        print("Nothing tracked yet. Run: python -m job_applier apply --file jd.txt")
        return 0

    counts = tr.counts()
    print("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    print()
    head = f"{'STATUS':<11} {'MUST':>5} {'DUE':>6}  {'COMPANY':<22} TITLE"
    print(head)
    print("-" * min(len(head) + 28, 100))
    for a in apps:
        d = a.days_to_deadline
        due = "-" if d is None else (f"{d}d" if d >= 0 else "past")
        must = "-" if a.required_score is None else f"{a.required_score:.0f}%"
        print(f"{a.status:<11} {must:>5} {due:>6}  {(a.company or '?')[:22]:<22} {(a.title or '?')[:40]}")
        print(f"{'':<11} {'':>5} {'':>6}  slug: {a.slug}")
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    tr = Tracker()
    try:
        tr.set_status(args.slug, args.status, args.note or "")
    except (KeyError, ValueError) as e:
        print(f"{BAD} {e}")
        return 1
    print(f"{OK} {args.slug} -> {args.status}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    tr = Tracker()
    a = tr.get(args.slug)
    if not a:
        print(f"{BAD} No application with slug {args.slug!r}")
        return 1
    print(f"{a.company} — {a.title}")
    print(f"  status:    {a.status}")
    print(f"  must-have: {a.required_score}%   overall: {a.fit_score}%")
    print(f"  location:  {a.location or '-'}")
    print(f"  url:       {a.url or '-'}")
    print(f"  deadline:  {a.deadline or '-'}" + (f" ({a.days_to_deadline}d)" if a.deadline else ""))
    print(f"  folder:    {a.folder or '-'}")
    print(f"  applied:   {a.applied_at or '-'}")
    if a.notes:
        print(f"  notes:     {a.notes}")
    print("\n  history:")
    for e in tr.events(args.slug):
        print(f"    {e['ts']}  {e['kind']}  {e['detail']}")
    return 0


def cmd_due(args: argparse.Namespace) -> int:
    tr = Tracker()
    apps = tr.due_soon(args.days)
    if not apps:
        print(f"{OK} Nothing due in the next {args.days} days that you have not applied to.")
        return 0
    print(f"Due within {args.days} days:\n")
    for a in apps:
        print(f"  {a.days_to_deadline:>3}d  {a.company} — {a.title}  [{a.status}]  ({a.slug})")
    return 0


# ----------------------------------------------------------------------
def _add_jd_args(p: argparse.ArgumentParser) -> None:
    src = p.add_argument_group("job description")
    src.add_argument("--file", "-f", help="path to a file holding the posting text (or .json)")
    src.add_argument("--text", "-t", help="the posting text inline")
    src.add_argument("--url", "-u", help="posting URL (best effort; many boards need --file)")
    src.add_argument("--company", "-c", help="company name")
    src.add_argument("--title", help="role title")
    src.add_argument("--location", "-l", help="role location")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="job_applier",
        description="Grounded job application tooling. Drafts and fills; you click submit.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="check setup and create .env")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("score", help="gap report only, no documents, no model needed")
    _add_jd_args(sp)
    sp.add_argument("--save", help="also write the report to this path")
    sp.set_defaults(func=cmd_score)

    sp = sub.add_parser("apply", help="produce a full application pack")
    _add_jd_args(sp)
    sp.add_argument("--from-queue", "-q", metavar="SLUG",
                    help="use a role already found by discover/ingest, no paste needed")
    sp.add_argument("--slug", help="override the folder/tracker slug")
    sp.add_argument("--deadline", help="application deadline, YYYY-MM-DD")
    sp.add_argument("--no-llm", action="store_true", help="skip the model entirely")
    sp.add_argument("--no-cover-letter", action="store_true")
    sp.add_argument("--no-pdf", action="store_true", help="skip PDF conversion")
    sp.add_argument("--pages", type=int, metavar="N",
                    help="page target; content is trimmed to fit (default from .env)")
    sp.add_argument("--no-fit", action="store_true",
                    help="render everything, however long it runs")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("status", help="list tracked applications")
    sp.add_argument("--status", choices=STATUSES)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("mark", help="update an application's status")
    sp.add_argument("slug")
    sp.add_argument("status", choices=STATUSES)
    sp.add_argument("--note", help="a line for the history log")
    sp.set_defaults(func=cmd_mark)

    sp = sub.add_parser("show", help="details and history for one application")
    sp.add_argument("slug")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("due", help="deadlines coming up")
    sp.add_argument("--days", type=int, default=7)
    sp.set_defaults(func=cmd_due)

    # ---- phase 2 ----
    sp = sub.add_parser("discover", help="search the public job APIs and queue what fits")
    sp.add_argument("--limit", type=int, help="max postings per source")
    sp.add_argument("--min-score", type=float, help="minimum must-have coverage to keep (%%)")
    sp.add_argument("--max-years", type=int, help="drop postings asking for more years than this")
    sp.add_argument("--keep-blocked", action="store_true",
                    help="keep postings with a hard blocker, to see them anyway")
    sp.add_argument("--dry-run", action="store_true", help="show results without touching the tracker")
    sp.add_argument("--show-rejected", action="store_true", help="list what was screened out and why")
    sp.set_defaults(func=cmd_discover)

    sp = sub.add_parser("urls", help="search URLs for the boards that need your browser")
    sp.add_argument("--board", choices=sorted(BROWSER_BOARDS), help="just one board")
    sp.add_argument("--keyword", "-k", action="append", help="override the configured search terms")
    sp.set_defaults(func=cmd_urls)

    sp = sub.add_parser("ingest", help="score postings captured from your browser and queue them")
    sp.add_argument("--source", "-s", required=True, help="which board they came from, e.g. linkedin")
    sp.add_argument("--file", "-f", required=True, help="JSON, JSON Lines, CSV or TSV capture file")
    sp.add_argument("--min-score", type=float)
    sp.add_argument("--max-years", type=int)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--show-rejected", action="store_true")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("sources", help="list sources, check they resolve, or add a company")
    sp.add_argument("action", nargs="?", choices=["list", "check", "add"], default="list")
    sp.add_argument("company", nargs="?", help="for `add`: the company name to look up")
    sp.add_argument("--ats", choices=sorted(boardlookup.PROBES),
                    help="for `add`: only probe this platform")
    sp.add_argument("--write", action="store_true",
                    help="for `add`: write the board into Context/sources.yaml")
    sp.set_defaults(func=cmd_sources)

    sp = sub.add_parser("fill", help="build a form fill plan for a tracked application")
    sp.add_argument("slug")
    sp.add_argument("--apply-url", help="the form URL, if it differs from the posting")
    sp.set_defaults(func=cmd_fill)

    sp = sub.add_parser("followup", help="what has gone quiet or is about to close")
    sp.add_argument("--days", type=int, default=7, help="deadline window")
    sp.set_defaults(func=cmd_followup)
    return p


def main(argv: list[str] | None = None) -> int:
    settings.ensure_dirs()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except FileNotFoundError as e:
        print(f"{BAD} {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


# ----------------------------------------------------------------------
# Phase 2: discovery, ingest, form fill, follow-up
# ----------------------------------------------------------------------
def _screening_args(args, cfg: SourceConfig) -> dict:
    return {
        "max_years": args.max_years if getattr(args, "max_years", None) else cfg.max_years,
        "min_required_score": (
            args.min_score if getattr(args, "min_score", None) is not None
            else cfg.min_required_score
        ),
    }


def _print_queue(result, show_rejected: bool) -> None:
    print()
    print(result.summary())

    if result.candidates:
        print()
        print(f"{'MUST':>5} {'DUE':>6}  {'SOURCE':<16} {'COMPANY':<26} TITLE")
        print("-" * 100)
        for c in result.candidates:
            p = c.posting
            d = ""
            if p.deadline:
                d = p.deadline[5:]
            src = p.source + (f"+{len(c.also_on)}" if c.also_on else "")
            print(f"{c.required_score:>4.0f}% {d:>6}  {src:<16} {(p.company or '?')[:26]:<26} {p.title[:44]}")
            gaps = [m.term for m in c.report.by_status(ats.MISSING) if m.required]
            if gaps:
                print(f"{'':>13}  missing: {', '.join(gaps[:6])}")

    if show_rejected and result.rejected:
        print()
        print("Screened out:")
        for p, why in result.rejected[:60]:
            print(f"  {(p.company or '?')[:24]:<24} {p.title[:40]:<40} {why}")
        if len(result.rejected) > 60:
            print(f"  ... and {len(result.rejected) - 60} more")


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        cfg = SourceConfig.load()
    except FileNotFoundError as e:
        print(f"{BAD} {e}")
        return 1

    bad = cfg.unsupported_ats()
    if bad:
        print(f"{WARN} No adapter for these configured boards, so they are skipped: {', '.join(bad)}")

    sources = cfg.api_sources()
    if not sources:
        print(f"{BAD} No automated sources are enabled in Context/sources.yaml.")
        return 1

    print(f"Searching {len(sources)} source(s): {', '.join(s.name for s in sources)}")
    print(f"Terms: {', '.join(cfg.search_terms[:4])}" + (" ..." if len(cfg.search_terms) > 4 else ""))

    result = discovery.discover(
        sources,
        Profile.load(),
        per_source_limit=args.limit or cfg.max_per_source,
        keep_blocked=args.keep_blocked,
        **_screening_args(args, cfg),
    )
    _print_queue(result, args.show_rejected)

    browser = cfg.browser_sources()
    if browser:
        print()
        print(f"{WARN} {len(browser)} board(s) need your browser: {', '.join(b.name for b in browser)}")
        print("    Run `ja urls` for the search links, then `ja ingest`.")

    if args.dry_run:
        print(f"\n{OK} Dry run — the tracker was not touched.")
        return 0

    try:
        written = discovery.record(result)
        print(f"\n{OK} {written} role(s) queued in the tracker. See: ja status --status discovered")
    except Exception as e:
        print(f"\n{WARN} Could not write to the tracker: {e}")
    return 0


def cmd_urls(args: argparse.Namespace) -> int:
    try:
        cfg = SourceConfig.load()
    except FileNotFoundError as e:
        print(f"{BAD} {e}")
        return 1

    keywords = args.keyword or cfg.search_terms or [""]
    boards = cfg.browser_boards or {}
    wanted = [args.board] if args.board else [b for b, o in boards.items() if (o or {}).get("enabled")]
    if not wanted:
        print(f"{WARN} No browser boards are enabled in Context/sources.yaml.")
        return 0

    print("These boards have no public API and their terms prohibit automated")
    print("scraping, so open them yourself, in your own signed-in browser.")
    print("Capture the results as JSON, then: ja ingest -s <board> -f capture.json")
    for board in wanted:
        opts = dict(boards.get(board) or {})
        opts.pop("enabled", None)
        print()
        print(f"--- {board} ---")
        for kw in keywords:
            try:
                print("  " + search_urls.build(board, kw, **opts))
            except ValueError as e:
                print(f"  {BAD} {e}")
                break
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    source = args.source.lower().replace("-", "_")
    try:
        postings = load_capture(args.file, source)
    except (OSError, ValueError) as e:
        print(f"{BAD} {e}")
        return 1
    if not postings:
        print(f"{WARN} No usable postings in {args.file}. Each record needs at least a title.")
        return 0

    print(f"{OK} Read {len(postings)} posting(s) from {args.file}")
    try:
        cfg = SourceConfig.load()
    except FileNotFoundError:
        cfg = SourceConfig()

    result = discovery.score_postings(
        postings, Profile.load(), **_screening_args(args, cfg)
    )
    _print_queue(result, args.show_rejected)

    if args.dry_run:
        print(f"\n{OK} Dry run — the tracker was not touched.")
        return 0
    try:
        written = discovery.record(result)
        print(f"\n{OK} {written} role(s) queued in the tracker.")
    except Exception as e:
        print(f"\n{WARN} Could not write to the tracker: {e}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    try:
        cfg = SourceConfig.load()
    except FileNotFoundError as e:
        print(f"{BAD} {e}")
        return 1

    api = cfg.api_sources()
    browser = cfg.browser_sources()

    if args.action == "list":
        print("Automated (public APIs):")
        for s in api:
            token = getattr(s, "token", "")
            print(f"  {s.name}{(' / ' + token) if token else ''}")
        print("\nNeeds your browser:")
        for b in browser:
            print(f"  {b.name}")
        bad = cfg.unsupported_ats()
        if bad:
            print("\nConfigured but unsupported:")
            for b in bad:
                print(f"  {b}")
        print(f"\nSearch terms: {len(cfg.search_terms)}")
        print(f"Screening: max {cfg.max_years} years experience, "
              f"minimum {cfg.min_required_score:g}% must-have coverage")
        print("\nTo verify every board resolves: ja sources check")
        return 0

    if args.action == "add":
        return _sources_add(args)

    # action == check
    print("Checking each automated source with one request...\n")
    failures = 0
    for s in api:
        token = getattr(s, "token", "")
        label = f"{s.name}{(' / ' + token) if token else ''}"
        try:
            got = list(s.fetch(limit=1))
            print(f"  {OK} {label:<34} {len(got)} posting(s) reachable")
        except NotFound:
            failures += 1
            print(f"  {BAD} {label:<34} no board at this token")
        except Exception as e:
            failures += 1
            msg = str(e).split("\n")[0][:80]
            print(f"  {BAD} {label:<34} {type(e).__name__}: {msg}")
    print()
    if failures:
        print(f"{WARN} {failures} source(s) failed. A failing company board usually means")
        print("    the token is wrong — check the slug in the board's own URL.")
    else:
        print(f"{OK} Every configured source responded.")
    return 0


def _sources_add(args: argparse.Namespace) -> int:
    if not args.company:
        print(f'{BAD} Give a company name: ja sources add "Shopee"')
        return 2

    tokens = boardlookup.candidate_tokens(args.company)
    print(f"Looking up {args.company!r}")
    print(f"  trying slugs: {', '.join(tokens)}")
    print(f"  on: {args.ats or ', '.join(sorted(boardlookup.PROBES))}\n")

    hits, notes = boardlookup.find_boards(args.company, only=args.ats)
    for note in notes:
        print(f"  {WARN} {note}")

    if not hits:
        print(f"{WARN} No public board found for {args.company!r}.")
        print("    That usually means one of three things:")
        print("      - they use Workday, SmartRecruiters, Taleo or their own portal")
        print("      - the slug differs from the company name")
        print("      - they post only to LinkedIn or MyCareersFuture")
        print("    Open their careers page, follow the redirect, and read the slug")
        print("    out of the URL. Then add it to Context/sources.yaml by hand.")
        return 1

    print(f"{OK} Found {len(hits)} board(s):\n")
    for h in hits:
        print(f"  {h.ats:<12} token: {h.token:<22} {h.jobs} open posting(s)")

    if not args.write:
        print("\n    Add the best one with: "
              f'ja sources add "{args.company}" --write')
        return 0

    best = hits[0]
    if boardlookup.add_to_config(best):
        print(f"\n{OK} Added {best.ats}/{best.token} to Context/sources.yaml")
        print("    It will be included in the next `ja discover`.")
    else:
        print(f"\n{OK} {best.ats}/{best.token} was already configured.")
    return 0


def cmd_fill(args: argparse.Namespace) -> int:
    tr = Tracker()
    app = tr.get(args.slug)
    if not app:
        print(f"{BAD} No application with slug {args.slug!r}. See: ja status")
        return 1

    folder = Path(app.folder) if app.folder else None
    if folder and not folder.is_absolute():
        folder = settings.root / folder
    if not folder or not folder.exists():
        print(f"{BAD} No document folder for {args.slug}. Run `ja apply` for this role first.")
        return 1

    jd_file = folder / "jd.txt"
    jd = (
        JobDescription.from_file(jd_file, title=app.title, company=app.company,
                                 location=app.location, url=app.url)
        if jd_file.exists()
        else JobDescription.from_text(app.title or "", title=app.title,
                                      company=app.company, location=app.location, url=app.url)
    )

    plan = fillplan.build_plan(
        Profile.load(), jd, folder, apply_url=args.apply_url or app.url
    )
    path = fillplan.write_plan(plan, folder)

    print(f"{OK} Fill plan for {app.company} — {app.title}")
    print(f"    platform: {plan['application']['ats']}")
    print(f"    fields:   {len(plan['fields'])}")
    print(f"    files:    {', '.join(plan['documents']) or 'none'}")
    print(f"    written:  {_rel(path)}")
    if not plan["application"]["apply_url"]:
        print(f"\n{WARN} No apply URL on record. Re-run with --apply-url <form link>.")
    print(f"\n{OK} Nothing will be submitted. The plan stops before the submit button.")
    print("    Hand this file to the browser agent, or use it as your own checklist.")
    try:
        tr.log(args.slug, "fill-plan", f"{len(plan['fields'])} fields, ats={plan['application']['ats']}")
    except Exception:
        pass
    return 0


def cmd_followup(args: argparse.Namespace) -> int:
    print(followup.report(Tracker(), deadline_window=args.days))
    return 0
