"""Phase 2 tests: sources, screening, discovery, ingest, fill plans, follow-up.

The source-parser tests use fixtures copied from the live API responses that
were inspected while writing the adapters, so a change in a provider's shape
shows up here rather than mid-run.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.robotparser
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from job_applier import discover as discovery           # noqa: E402
from job_applier import search_urls                     # noqa: E402
from job_applier.filters import required_years, screen  # noqa: E402
from job_applier.fillplan import build_plan, detect_ats  # noqa: E402
from job_applier.followup import nudges                 # noqa: E402
from job_applier.jd import JobDescription               # noqa: E402
from job_applier.net import PoliteFetcher               # noqa: E402
from job_applier.profile import Profile                 # noqa: E402
from job_applier.sources.ashby import AshbySource       # noqa: E402
from job_applier.sources.base import Posting, html_to_text  # noqa: E402
from job_applier.sources.browser import (               # noqa: E402
    BrowserAssistedSource, load_capture, parse_records)
from job_applier.sources.greenhouse import GreenhouseSource  # noqa: E402
from job_applier.sources.lever import LeverSource       # noqa: E402
from job_applier.sources.mycareersfuture import MyCareersFutureSource as MCF  # noqa: E402
from job_applier.sources.registry import SourceConfig   # noqa: E402
from job_applier.tracker import Tracker                 # noqa: E402


def P(title, company="Acme", **kw):
    kw.setdefault("source", "test")
    kw.setdefault("source_id", "1")
    return Posting(title=title, company=company, **kw)


class TestHtmlToText(unittest.TestCase):
    def test_keeps_list_structure(self):
        out = html_to_text("<p>Needs:</p><ul><li>Python</li><li>SQL</li></ul>")
        self.assertIn("- Python", out)
        self.assertIn("- SQL", out)

    def test_unescapes_entities(self):
        self.assertIn("R&D", html_to_text("<p>R&amp;D</p>"))

    def test_drops_scripts(self):
        self.assertNotIn("alert", html_to_text("<script>alert(1)</script><p>Hi</p>"))

    def test_plain_text_passes_through(self):
        self.assertEqual(html_to_text("just text"), "just text")


class TestGreenhouseParser(unittest.TestCase):
    FIXTURE = {
        "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/5456619008",
        "internal_job_id": 4563891008, "id": 5456619008, "title": "Security Engineer",
        "location": {"name": "San Francisco, CA | Seattle, WA"},
        "metadata": [{"id": 1, "name": "Location Type", "value": "Remote"}],
        "updated_at": "2026-10-19T11:17:24-04:00",
        "first_published": "2026-10-19T11:17:24-04:00",
        "requisition_id": "REQ-26-1145-01", "company_name": "Anthropic",
        "application_deadline": None,
        "content": "&lt;p&gt;Requirements:&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;",
    }

    def setUp(self):
        self.p = GreenhouseSource("anthropic", "Anthropic")._to_posting(self.FIXTURE)

    def test_core_fields(self):
        self.assertEqual(self.p.title, "Security Engineer")
        self.assertEqual(self.p.company, "Anthropic")
        self.assertEqual(self.p.posted_at, "2026-10-19")
        self.assertTrue(self.p.url.endswith("5456619008"))

    def test_double_escaped_html_is_decoded(self):
        # Greenhouse returns `content` HTML-escaped; raw entities must not survive.
        self.assertNotIn("&lt;", self.p.description)
        self.assertIn("- Python", self.p.description)

    def test_remote_detected_from_metadata(self):
        self.assertTrue(self.p.remote)

    def test_null_deadline_does_not_crash(self):
        self.assertEqual(self.p.deadline, "")


class TestLeverParser(unittest.TestCase):
    FIXTURE = {
        "id": "6ed76ce8", "text": "Security Engineer", "createdAt": 1786469891368,
        "categories": {"commitment": "Full-time", "location": "Singapore, Singapore",
                       "team": "Security", "allLocations": ["Singapore, Singapore"]},
        "country": "SG", "workplaceType": "hybrid",
        "descriptionPlain": "Defend the platform.",
        "lists": [{"text": "What We Require", "content": "<li>Python</li><li>SQL</li>"}],
        "hostedUrl": "https://jobs.lever.co/palantir/6ed76ce8",
        "applyUrl": "https://jobs.lever.co/palantir/6ed76ce8/apply",
        "additionalPlain": "EEO notice.",
    }

    def setUp(self):
        self.p = LeverSource("palantir", "Palantir")._to_posting(self.FIXTURE)

    def test_core_fields(self):
        self.assertEqual(self.p.title, "Security Engineer")
        self.assertEqual(self.p.location, "Singapore, Singapore")
        self.assertEqual(self.p.employment_type, "Full-time")

    def test_epoch_millis_become_a_date(self):
        self.assertRegex(self.p.posted_at, r"^\d{4}-\d{2}-\d{2}$")

    def test_list_sections_keep_their_headings(self):
        # The JD parser needs headings to weight requirements correctly.
        self.assertIn("What We Require:", self.p.description)
        self.assertIn("- Python", self.p.description)

    def test_apply_url_preferred_over_hosted(self):
        self.assertTrue(self.p.apply_url.endswith("/apply"))


class TestAshbyParser(unittest.TestCase):
    FIXTURE = {
        "id": "34413f8d", "title": "  Security Engineer, Cloud ",
        "department": "Engineering", "team": "Backend", "employmentType": "FullTime",
        "location": "New York, NY (HQ)",
        "secondaryLocations": [{"location": "Remote (US)"}, {"location": "Remote (US)"}],
        "publishedAt": "2026-04-07T17:12:35.753+00:00", "isListed": True,
        "isRemote": True, "workplaceType": "Hybrid",
        "jobUrl": "https://jobs.ashbyhq.com/ramp/34413f8d",
        "applyUrl": "https://jobs.ashbyhq.com/ramp/34413f8d/application",
        "descriptionPlain": "Build cloud security.",
    }

    def setUp(self):
        self.p = AshbySource("ramp", "Ramp")._to_posting(self.FIXTURE)

    def test_title_whitespace_stripped(self):
        self.assertEqual(self.p.title, "Security Engineer, Cloud")

    def test_locations_merged_without_duplicates(self):
        self.assertEqual(self.p.location.count("Remote (US)"), 1)

    def test_unlisted_jobs_are_dropped(self):
        self.assertIsNone(AshbySource("ramp")._to_posting({"id": "1", "isListed": False}))


class TestMyCareersFutureParser(unittest.TestCase):
    FIXTURE = {
        "uuid": "2fe8643739bd36433e601fb0042ce7a4", "title": "Security Engineer",
        "description": "<h2>Role</h2><p>Defend the platform.</p>",
        "minimumYearsExperience": 2,
        "skills": [{"skill": "Python", "isKeySkill": True}, {"skill": "Network Security"}],
        "categories": [{"id": 1, "category": "Information Technology"}],
        "employmentTypes": [{"id": 8, "employmentType": "Full Time"}],
        "positionLevels": [{"id": 2, "position": "Fresh/entry level"}],
        "status": {"id": 102, "jobStatus": "Open"},
        "postedCompany": {"uen": "202541156Z", "name": "ACME TECH PTE. LTD."},
        "hiringCompany": None,
        "address": {"isOverseas": False,
                    "districts": [{"id": 1, "location": "D01 Raffles Place", "region": "Central"}]},
        "metadata": {"jobPostId": "MCF-2026-2002217", "newPostingDate": "2026-11-12",
                     "expiryDate": "2026-12-12",
                     "jobDetailsUrl": "https://www.mycareersfuture.gov.sg/job/x",
                     "isHideSalary": False},
        "salary": {"minimum": 4500, "maximum": 6500, "type": {"id": 4, "salaryType": "Monthly"}},
        "numberOfVacancies": 2,
    }

    def setUp(self):
        self.p = MCF._to_posting(self.FIXTURE)

    def test_core_fields(self):
        self.assertEqual(self.p.company, "ACME TECH PTE. LTD.")
        self.assertEqual(self.p.source_id, "MCF-2026-2002217")
        self.assertEqual(self.p.deadline, "2026-12-12")
        self.assertEqual(self.p.min_years_experience, 2)

    def test_salary_band(self):
        self.assertEqual((self.p.salary_min, self.p.salary_max), (4500, 6500))
        self.assertEqual(self.p.salary_currency, "SGD")

    def test_hidden_salary_is_not_invented(self):
        hidden = json.loads(json.dumps(self.FIXTURE))
        hidden["metadata"]["isHideSalary"] = True
        p = MCF._to_posting(hidden)
        self.assertIsNone(p.salary_min)
        self.assertEqual(p.salary_currency, "")

    def test_structured_skills_reach_the_matcher(self):
        # MCF is the only source with a clean skills taxonomy; dropping it
        # would throw away the best signal available.
        self.assertIn("Python", self.p.description)
        self.assertIn("Network Security", self.p.description)

    def test_closed_jobs_are_dropped(self):
        closed = json.loads(json.dumps(self.FIXTURE))
        closed["status"] = {"jobStatus": "Closed"}
        self.assertIsNone(MCF._to_posting(closed))

    def test_overseas_location(self):
        overseas = json.loads(json.dumps(self.FIXTURE))
        overseas["address"] = {"isOverseas": True, "overseasCountry": "Malaysia"}
        self.assertEqual(MCF._to_posting(overseas).location, "Malaysia")


class TestScreening(unittest.TestCase):
    def test_senior_titles_rejected(self):
        for title in ("Senior Security Engineer", "Staff Engineer", "Head of Security",
                      "Principal Analyst", "Cybersecurity Manager", "Security Architect"):
            self.assertFalse(screen(P(title)).suitable, title)

    def test_level_markers_rejected(self):
        self.assertFalse(screen(P("Security Engineer III")).suitable)

    def test_graduate_titles_kept(self):
        for title in ("Graduate Cybersecurity Engineer", "Security Engineer, University Graduate",
                      "Junior Security Analyst", "Technical Graduate Programme 2027"):
            self.assertTrue(screen(P(title)).suitable, title)

    def test_experience_requirement_rejected(self):
        self.assertFalse(screen(P("Security Engineer", description="Minimum 8 years experience.")).suitable)

    def test_experience_ceiling_is_not_a_requirement(self):
        # "under 2 years" is a new-grad signal; reading it as a 2-year
        # requirement would discard exactly the right postings.
        self.assertIsNone(required_years("Fresh graduates with under 2 years of full-time work experience."))
        s = screen(P("Graduate Engineer", description="Fresh or recent graduates with under 2 years of full-time work experience."))
        self.assertTrue(s.suitable)
        self.assertEqual(s.seniority, "entry")

    def test_graduate_title_survives_boilerplate_years(self):
        s = screen(P("Graduate Analyst", description="Requires 5 years experience."))
        self.assertTrue(s.suitable)
        self.assertTrue(any("graduate role" in r for r in s.reasons))

    def test_every_rejection_has_a_reason(self):
        s = screen(P("Senior Director of Security"))
        self.assertTrue(s.reasons)


class TestMergeDuplicates(unittest.TestCase):
    def setUp(self):
        self.a = P("Graduate Security Engineer", "Acme Corp", source="linkedin", source_id="1",
                   location="Singapore", url="https://li/1",
                   description="Requirements:\n- Python\n- Network security\n- SQL")
        self.b = P("Graduate Security Engineer", "ACME CORP", source="greenhouse", source_id="2",
                   location="Singapore, Singapore", url="https://boards.greenhouse.io/acme/1",
                   description="Short.", deadline="2027-01-15")
        self.c = P("Graduate  Security Engineer", "Acme Corp", source="indeed", source_id="3",
                   location="Singapore")

    def test_collapses_to_one(self):
        self.assertEqual(len(discovery.merge_duplicates([self.a, self.b, self.c])), 1)

    def test_keeps_the_most_direct_source(self):
        best, _ = discovery.merge_duplicates([self.a, self.b, self.c])[0]
        self.assertEqual(best.source, "greenhouse")

    def test_carries_over_the_richest_description(self):
        best, _ = discovery.merge_duplicates([self.a, self.b, self.c])[0]
        self.assertIn("Network security", best.description)

    def test_fills_blanks_from_siblings(self):
        best, _ = discovery.merge_duplicates([self.a, self.c])[0]
        self.assertEqual(best.source, "linkedin")
        best2, _ = discovery.merge_duplicates([self.a, self.b])[0]
        self.assertEqual(best2.deadline, "2027-01-15")

    def test_records_the_other_boards(self):
        _, also = discovery.merge_duplicates([self.a, self.b, self.c])[0]
        self.assertEqual(set(also), {"indeed", "linkedin"})

    def test_distinct_roles_are_not_merged(self):
        other = P("Data Engineer", "Acme Corp", location="Singapore")
        self.assertEqual(len(discovery.merge_duplicates([self.a, other])), 2)


class TestDiscoveryScoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = Profile.load()

    def test_ranks_by_must_have_coverage(self):
        strong = P("Graduate Security Engineer", "Strong Co", location="Singapore",
                   description="Requirements:\n- Python\n- Network security\n- SQL\n- log analysis\n- threat detection")
        weak = P("Graduate Engineer", "Weak Co", location="Singapore",
                 description="Requirements:\n- Kubernetes\n- Terraform\n- Go\n- Istio")
        r = discovery.score_postings([strong, weak], self.profile, min_required_score=40)
        self.assertEqual(r.candidates[0].posting.company, "Strong Co")
        self.assertTrue(any(p.company == "Weak Co" for p, _ in r.rejected))

    def test_threshold_is_respected(self):
        weak = P("Graduate Engineer", "Weak Co",
                 description="Requirements:\n- Kubernetes\n- Terraform\n- Solidity")
        self.assertEqual(len(discovery.score_postings([weak], self.profile, min_required_score=90).candidates), 0)

    def test_blockers_are_dropped(self):
        blocked = P("Graduate Security Engineer", "Past Co",
                    description="Requirements:\n- Python\n- Must be graduating in 2024")
        r = discovery.score_postings([blocked], self.profile, min_required_score=0)
        self.assertEqual(len(r.candidates), 0)
        self.assertTrue(any("blocker" in why for _, why in r.rejected))

    def test_keep_blocked_overrides(self):
        blocked = P("Graduate Security Engineer", "Past Co",
                    description="Requirements:\n- Python\n- Must be graduating in 2024")
        r = discovery.score_postings([blocked], self.profile, min_required_score=0, keep_blocked=True)
        self.assertEqual(len(r.candidates), 1)

    def test_rejections_always_explain_themselves(self):
        r = discovery.score_postings(
            [P("Senior Engineer", "X"), P("Grad Engineer", "Y", description="- Terraform")],
            self.profile, min_required_score=99)
        for _, why in r.rejected:
            self.assertTrue(why.strip())

    def test_record_leaves_in_flight_applications_alone(self):
        with tempfile.TemporaryDirectory() as d:
            tr = Tracker(Path(d) / "t.db")
            strong = P("Graduate Security Engineer", "Strong Co", location="Singapore",
                       description="Requirements:\n- Python\n- Network security\n- SQL")
            r = discovery.score_postings([strong], self.profile, min_required_score=0)
            discovery.record(r, tr)
            slug = strong.slug()
            tr.set_status(slug, "applied")
            discovery.record(r, tr)       # a later run must not reset it
            self.assertEqual(tr.get(slug).status, "applied")


class TestBrowserIngest(unittest.TestCase):
    def test_records_without_a_title_are_skipped(self):
        self.assertEqual(len(parse_records([{"company": "X"}, {"title": "Grad SE"}], "linkedin")), 1)

    def test_html_descriptions_are_flattened(self):
        p = parse_records([{"title": "T", "description": "<ul><li>Python</li></ul>"}], "linkedin")[0]
        self.assertEqual(p.description, "- Python")

    def test_messy_salary_values_parsed(self):
        p = parse_records([{"title": "T", "salary_min": "8,000", "salary_max": "$12000"}], "linkedin")[0]
        self.assertEqual((p.salary_min, p.salary_max), (8000.0, 12000.0))

    def test_remote_inferred_from_location(self):
        self.assertTrue(parse_records([{"title": "T", "location": "Remote - APAC"}], "linkedin")[0].remote)

    def test_capture_formats(self):
        rows = [{"title": "Grad SE", "company": "Acme"}]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.json").write_text(json.dumps(rows), encoding="utf-8")
            (d / "b.json").write_text(json.dumps({"jobs": rows}), encoding="utf-8")
            (d / "c.jsonl").write_text(json.dumps(rows[0]), encoding="utf-8")
            (d / "e.csv").write_text("title,company\nGrad SE,Acme\n", encoding="utf-8")
            for name in ("a.json", "b.json", "c.jsonl", "e.csv"):
                self.assertEqual(len(load_capture(d / name, "linkedin")), 1, name)

    def test_browser_source_refuses_to_fetch(self):
        with self.assertRaises(RuntimeError):
            BrowserAssistedSource("linkedin", ["x"]).fetch()

    def test_browser_source_builds_one_url_per_keyword(self):
        s = BrowserAssistedSource("linkedin", ["a", "b"], location="Singapore")
        self.assertEqual(len(s.search_urls()), 2)

    def test_unknown_board_rejected(self):
        with self.assertRaises(ValueError):
            BrowserAssistedSource("monster", ["x"])


class TestSearchUrls(unittest.TestCase):
    def test_linkedin_filter_codes(self):
        u = search_urls.linkedin("security engineer", experience=["internship", "entry"],
                                 job_type=["full-time"], workplace=["remote"], posted_within="week")
        self.assertIn("f_E=1,2", u)      # 1=internship, 2=entry
        self.assertIn("f_JT=F", u)
        self.assertIn("f_WT=2", u)       # 2=remote
        self.assertIn("f_TPR=r604800", u)
        self.assertIn("sortBy=DD", u)

    def test_keywords_are_encoded(self):
        self.assertIn("security%20engineer", search_urls.linkedin("security engineer"))

    def test_every_board_builds(self):
        for board in ("linkedin", "jobstreet", "indeed", "glassdoor", "mycareersfuture_web"):
            self.assertTrue(search_urls.build(board, "security engineer").startswith("https://"))

    def test_unknown_board_rejected(self):
        with self.assertRaises(ValueError):
            search_urls.build("monster", "x")


class TestFillPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = Profile.load()
        cls.jd = JobDescription.from_text("Requirements:\n- Python\n", title="Graduate SE",
                                          company="Acme", location="Singapore")

    def test_ats_detection(self):
        self.assertEqual(detect_ats("https://boards.greenhouse.io/a/jobs/1"), "greenhouse")
        self.assertEqual(detect_ats("https://jobs.lever.co/a/b"), "lever")
        self.assertEqual(detect_ats("https://jobs.ashbyhq.com/a/b"), "ashby")
        self.assertEqual(detect_ats("https://x.wd3.myworkdayjobs.com/en-US/c/job/y"), "workday")
        self.assertEqual(detect_ats("https://example.com/apply"), "unknown")

    def test_never_submits(self):
        plan = build_plan(self.profile, self.jd, apply_url="https://boards.greenhouse.io/a/jobs/1")
        self.assertTrue(plan["stop_before_submit"])
        self.assertTrue(any("Submit" in n or "submit" in n for n in plan["never_do"]))

    def test_values_come_from_the_profile(self):
        plan = build_plan(self.profile, self.jd)
        values = {f["key"]: f["value"] for f in plan["fields"]}
        self.assertEqual(values["email"], self.profile.meta["email"])
        self.assertIn("Nicholas", values["full_name"])
        self.assertEqual(values["first_name"], "Nicholas")

    def test_singapore_role_needs_no_sponsorship(self):
        plan = build_plan(self.profile, self.jd)
        values = {f["key"]: f["value"] for f in plan["fields"]}
        self.assertEqual(values["needs_sponsorship"], "No")
        self.assertEqual(values["work_authorised"], "Yes")

    def test_overseas_role_flags_sponsorship(self):
        jd = JobDescription.from_text("x", title="SE", company="Acme", location="London, UK")
        values = {f["key"]: f["value"] for f in build_plan(self.profile, jd)["fields"]}
        self.assertEqual(values["needs_sponsorship"], "Yes")

    def test_demographics_left_blank(self):
        plan = build_plan(self.profile, self.jd)
        keys = {f["key"] for f in plan["fields"]}
        for banned in ("race", "gender", "disability", "veteran", "ethnicity"):
            self.assertNotIn(banned, keys)
        self.assertTrue(any("demographic" in x for x in plan["leave_blank"]))

    def test_no_empty_fields_emitted(self):
        for f in build_plan(self.profile, self.jd)["fields"]:
            self.assertTrue(f["value"])


class TestFollowup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tr = Tracker(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.dir.cleanup()

    def test_imminent_deadline_surfaces(self):
        soon = (date.today() + timedelta(days=3)).isoformat()
        self.tr.upsert("a", company="Acme", title="Grad SE", status="drafted", deadline=soon)
        kinds = [n.kind for n in nudges(self.tr)]
        self.assertIn("deadline", kinds)

    def test_passed_deadline_surfaces(self):
        past = (date.today() - timedelta(days=2)).isoformat()
        self.tr.upsert("b", company="B", title="T", status="discovered", deadline=past)
        self.assertIn("expired", [n.kind for n in nudges(self.tr)])

    def test_silence_after_applying_surfaces(self):
        self.tr.upsert("c", company="C", title="T", status="applied")
        old = (date.today() - timedelta(days=20)).isoformat()
        with self.tr._conn() as con:
            con.execute("UPDATE applications SET applied_at=?, updated_at=? WHERE slug='c'", (old, old))
        self.assertIn("stale_applied", [n.kind for n in nudges(self.tr)])

    def test_closed_outcomes_are_left_alone(self):
        past = (date.today() - timedelta(days=5)).isoformat()
        self.tr.upsert("d", company="D", title="T", status="rejected", deadline=past)
        self.tr.upsert("e", company="E", title="T", status="offer", deadline=past)
        self.assertEqual(nudges(self.tr), [])

    def test_fresh_applications_are_quiet(self):
        self.tr.upsert("f", company="F", title="T", status="applied")
        self.assertEqual(nudges(self.tr), [])


class TestPoliteFetcher(unittest.TestCase):
    def _fetcher_with_robots(self, body: str) -> PoliteFetcher:
        f = PoliteFetcher()
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.splitlines())
        f._robots["example.com"] = rp
        return f

    def test_disallowed_path_is_refused(self):
        f = self._fetcher_with_robots("User-agent: *\nDisallow: /private/")
        self.assertFalse(f.allowed("https://example.com/private/x"))
        self.assertTrue(f.allowed("https://example.com/public/x"))

    def test_blanket_disallow_is_respected(self):
        f = self._fetcher_with_robots("User-agent: *\nDisallow: /")
        self.assertFalse(f.allowed("https://example.com/anything"))

    def test_missing_robots_is_not_a_block(self):
        f = PoliteFetcher()
        f._robots["example.com"] = None
        self.assertTrue(f.allowed("https://example.com/x"))

    def test_crawl_delay_is_read(self):
        f = self._fetcher_with_robots("User-agent: *\nCrawl-delay: 5\nDisallow:")
        self.assertEqual(f.crawl_delay("https://example.com/x"), 5.0)

    def test_user_agent_identifies_the_tool(self):
        from job_applier.net import USER_AGENT
        self.assertIn("job_applier", USER_AGENT)


class TestSourceConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = SourceConfig.load()

    def test_loads_shipped_config(self):
        self.assertTrue(self.cfg.search_terms)
        self.assertTrue(self.cfg.api_sources())

    def test_browser_boards_are_not_automated(self):
        for s in self.cfg.browser_sources():
            self.assertFalse(s.automated)

    def test_discover_skips_browser_sources(self):
        # They must never be fetched over HTTP, even if handed to discover().
        r = discovery.discover(self.cfg.browser_sources(), Profile.load())
        self.assertEqual(r.fetched, 0)
        self.assertEqual(r.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
