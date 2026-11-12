"""Tests for the defects fixed after Phase 2.

Each class here corresponds to something that was actually broken:

  * discovery fetched the job description and threw it away
  * JA_MAX_PAGES was a request, not a constraint — a one-page setting produced two
  * ranking scored a Java address-book project above an AI security project on a
    security posting, because both merely said "Java"
  * a 404 from a board that does not exist was reported as an error
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from job_applier import ats, boardlookup, discover as discovery, pagefit, render  # noqa: E402
from job_applier.boardlookup import Hit, add_to_config, candidate_tokens, _count  # noqa: E402
from job_applier.jd import JobDescription                     # noqa: E402
from job_applier.net import Blocked, NotFound                 # noqa: E402
from job_applier.profile import Profile                       # noqa: E402
from job_applier.sources.base import Posting                  # noqa: E402
from job_applier.tailor import tailor_deterministic           # noqa: E402
from job_applier.tracker import Tracker                       # noqa: E402

SECURITY_JD = """Graduate Security Engineer

Responsibilities:
- Perform security reviews and secure code review across services
- Run vulnerability scanning and support penetration testing
- Improve security governance and security testing coverage

Requirements:
- Degree in Computer Science or Information Security, graduating 2027
- Proficiency in Python or Java
- Understanding of network security and cryptography
"""


def _profile():
    return Profile.load()


class TestPostingPersistence(unittest.TestCase):
    """Discovery already paid to fetch the description; losing it forced a
    manual copy-paste before `apply` could run."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tr = Tracker(Path(self.dir.name) / "t.db")
        self.posting = Posting(
            source="mycareersfuture", source_id="MCF-1",
            title="Graduate Security Engineer", company="Acme",
            location="Singapore", url="https://x",
            description="Requirements:\n- Python\n- Network security\n- SQL",
            deadline="2027-01-10",
        )

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        self.tr.save_posting("acme-grad", "mycareersfuture", self.posting.as_dict())
        got = self.tr.get_posting("acme-grad")
        self.assertEqual(got["description"], self.posting.description)
        self.assertEqual(got["deadline"], "2027-01-10")

    def test_missing_posting_returns_none(self):
        self.assertIsNone(self.tr.get_posting("nope"))

    def test_record_stores_the_description(self):
        r = discovery.score_postings([self.posting], _profile(), min_required_score=0)
        discovery.record(r, self.tr)
        stored = self.tr.get_posting(self.posting.slug())
        self.assertIsNotNone(stored)
        self.assertIn("Network security", stored["description"])

    def test_resave_overwrites_rather_than_duplicating(self):
        self.tr.save_posting("s", "a", {"description": "first"})
        self.tr.save_posting("s", "b", {"description": "second"})
        self.assertEqual(self.tr.get_posting("s")["description"], "second")

    def test_table_appears_on_a_pre_existing_database(self):
        # Users already have a tracker.db from Phase 1; it must gain the table
        # without a manual migration step.
        path = Path(self.dir.name) / "old.db"
        Tracker(path)
        again = Tracker(path)
        again.save_posting("x", "src", {"description": "d"})
        self.assertIsNotNone(again.get_posting("x"))


class TestDomainAffinity(unittest.TestCase):
    """A posting that says 'security testing' is a security posting, even
    though the phrase proves nothing about the candidate."""

    @classmethod
    def setUpClass(cls):
        cls.profile = _profile()
        cls.report = ats.match(JobDescription.from_text(SECURITY_JD), cls.profile)

    def test_security_domain_detected_from_boilerplate(self):
        self.assertIn("security", self.report.domain_tags)

    def test_blockchain_posting_reads_as_blockchain(self):
        jd = JobDescription.from_text(
            "Requirements:\n- Strong understanding of blockchain and smart contracts\n"
            "- Experience auditing DeFi protocols\n"
        )
        self.assertIn("blockchain", ats.match(jd, self.profile).domain_tags)

    def test_ml_posting_reads_as_ml(self):
        jd = JobDescription.from_text(
            "Requirements:\n- Experience with machine learning and PyTorch\n"
        )
        self.assertIn("ml", ats.match(jd, self.profile).domain_tags)

    def test_security_work_outranks_generic_java_work(self):
        order = self.report.evidence_bullets
        security_bullets = [b for b in order if self.profile.bullet(b)
                            and {"security", "cryptography", "offensive-security"}
                            & set(self.profile.bullet(b).tags)]
        self.assertTrue(security_bullets, "expected some security bullets to rank")
        # CollabSync is an address book that happens to be written in Java.
        if "collabsync.b1" in order:
            self.assertLess(
                order.index(security_bullets[0]), order.index("collabsync.b1"),
                "security work must outrank a generic Java project on a security posting",
            )

    def test_ranking_stays_deterministic(self):
        again = ats.match(JobDescription.from_text(SECURITY_JD), self.profile)
        self.assertEqual(self.report.evidence_bullets, again.evidence_bullets)

    def test_soft_terms_do_not_invent_a_domain(self):
        jd = JobDescription.from_text(
            "Requirements:\n- Strong communication and presentation skills\n"
            "- A self-starter who thrives in a fast-paced environment\n"
        )
        self.assertEqual(ats.match(jd, self.profile).domain_tags, set())


class TestPageFit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = _profile()
        cls.jd = JobDescription.from_text(SECURITY_JD, title="Graduate Security Engineer",
                                          company="Acme")
        cls.dir = tempfile.mkdtemp()
        probe = Path(cls.dir) / "probe.docx"
        t = tailor_deterministic(cls.jd, cls.profile)
        render.render_resume_docx(t, cls.profile, probe)
        pdf = render.to_pdf(probe)
        cls.can_measure = pdf is not None and pagefit.count_pages(pdf) is not None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _fresh(self):
        return tailor_deterministic(self.jd, self.profile)

    def test_trim_drops_the_summary_first(self):
        t = self._fresh()
        t.summary = "A summary."
        self.assertIn("summary", pagefit.trim_once(t))
        self.assertIsNone(t.summary)

    def test_trim_only_removes_never_rewrites(self):
        t = self._fresh()
        before = {b.source_id: b.text for s in t.all_sections for b in s.bullets}
        for _ in range(8):
            if pagefit.trim_once(t) is None:
                break
        for s in t.all_sections:
            for b in s.bullets:
                self.assertEqual(b.text, before[b.source_id],
                                 "trimming must not reword a surviving bullet")

    def test_whole_irrelevant_role_goes_before_a_strong_role_is_thinned(self):
        t = self._fresh()
        bullets_at_start = len(t.experience[0].bullets)
        dropped_role = False
        for _ in range(12):
            what = pagefit.trim_once(t)
            if what is None:
                break
            if what.startswith("role:"):
                dropped_role = True
                break
            if len(t.experience[0].bullets) < bullets_at_start:
                break
        self.assertTrue(dropped_role,
                        "a whole low-relevance role should go before the top role is thinned")

    def test_two_most_recent_roles_keep_at_least_two_bullets_while_slack_remains(self):
        t = self._fresh()
        for _ in range(6):
            if pagefit.trim_once(t) is None:
                break
        for sec in t.experience[:2]:
            if sec.bullets:
                self.assertGreaterEqual(len(sec.bullets), 2)

    def test_trim_eventually_reports_nothing_left(self):
        t = self._fresh()
        for _ in range(60):
            if pagefit.trim_once(t) is None:
                break
        else:
            self.fail("trim_once never reported exhaustion")

    def test_estimate_is_a_positive_number(self):
        self.assertGreater(pagefit.estimate_pages(self._fresh(), self.profile), 0)

    def test_count_pages_handles_a_missing_file(self):
        self.assertIsNone(pagefit.count_pages(Path(self.dir) / "nope.pdf"))

    def test_fitting_reaches_one_page(self):
        if not self.can_measure:
            self.skipTest("no PDF converter on this machine")
        t = self._fresh()
        res = pagefit.render_fitted(t, self.profile, Path(self.dir) / "fit.docx", max_pages=1)
        self.assertTrue(res.fitted, res.message())
        self.assertEqual(res.pages, 1)
        self.assertTrue(res.trimmed, "the full resume is longer than a page, so something must go")

    def test_generous_target_trims_nothing(self):
        if not self.can_measure:
            self.skipTest("no PDF converter on this machine")
        t = self._fresh()
        res = pagefit.render_fitted(t, self.profile, Path(self.dir) / "loose.docx", max_pages=4)
        self.assertEqual(res.trimmed, [])

    def test_message_admits_when_it_could_not_fit(self):
        r = pagefit.FitResult(docx=Path("x.docx"), pages=3, fitted=False, target=1)
        self.assertIn("still over", r.message())

    def test_message_flags_an_estimate_as_an_estimate(self):
        r = pagefit.FitResult(docx=Path("x.docx"), pages=1, estimated=True, target=1)
        self.assertIn("estimated", r.message())


class TestBoardLookup(unittest.TestCase):
    def test_legal_suffixes_are_stripped(self):
        self.assertEqual(candidate_tokens("Shopee Singapore Private Limited")[0], "shopee")
        self.assertEqual(candidate_tokens("BYTEDANCE PTE. LTD.")[0], "bytedance")
        self.assertEqual(candidate_tokens("Grab Holdings Inc")[0], "grab")

    def test_simple_names_pass_through(self):
        self.assertEqual(candidate_tokens("Stripe")[0], "stripe")

    def test_empty_name_yields_nothing(self):
        self.assertEqual(candidate_tokens(""), [])

    def test_counts_match_each_platform_shape(self):
        # Shapes verified against the live APIs.
        self.assertEqual(_count("greenhouse", {"jobs": [{"id": 1}, {"id": 2}]}), 2)
        self.assertEqual(_count("lever", [{"id": "a"}]), 1)
        self.assertEqual(_count("ashby", {"jobs": []}), 0)

    def test_a_non_board_response_is_not_a_hit(self):
        self.assertIsNone(_count("greenhouse", {"error": "not found"}))
        self.assertIsNone(_count("lever", {"jobs": []}))
        self.assertIsNone(_count("ashby", ["unexpected"]))

    def test_config_write_preserves_comments_and_dedupes(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "sources.yaml"
            shutil.copy(ROOT / "Context" / "sources.yaml", target)
            before = target.read_text(encoding="utf-8")
            self.assertTrue(add_to_config(Hit("greenhouse", "stripe", 159, "Stripe"), target))
            after = target.read_text(encoding="utf-8")
            self.assertEqual(before.count("#"), after.count("#"))
            self.assertFalse(add_to_config(Hit("greenhouse", "stripe", 159, "Stripe"), target))

    def test_config_stays_valid_yaml_after_writing(self):
        import yaml
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "sources.yaml"
            shutil.copy(ROOT / "Context" / "sources.yaml", target)
            add_to_config(Hit("lever", "csit", 12, "CSIT"), target)
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
            self.assertIn(("lever", "csit"),
                          [(b["ats"], b["token"]) for b in data["company_boards"]])

    def test_not_found_is_distinct_from_blocked(self):
        # A company that runs no board on a platform is a normal answer.
        self.assertFalse(issubclass(NotFound, Blocked))


if __name__ == "__main__":
    unittest.main(verbosity=2)
