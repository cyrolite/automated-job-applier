"""Core behaviour tests. Run with:  python -m unittest discover -s tests

The grounding tests matter most: they are what stop a fabricated claim from
reaching a document.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from job_applier import ats, render                      # noqa: E402
from job_applier.jd import JobDescription                # noqa: E402
from job_applier.llm import extract_json                 # noqa: E402
from job_applier.profile import Profile                  # noqa: E402
from job_applier.tailor import tailor_deterministic      # noqa: E402
from job_applier.tracker import Tracker                  # noqa: E402
from job_applier.verify import verify_bullet, verify_free_text  # noqa: E402

JD_TEXT = """Security Engineer, University Graduate (2027)

Responsibilities:
- Build detection pipelines for bot detection and scraping traffic
- Analyse HTTP traffic at scale, prepare technical documentation

Minimum Qualifications:
- Bachelor's degree in Information Security, graduating in 2027
- Proficiency in Python and SQL
- Understanding of network security and TCP/IP
- Strong communication and presentation skills

Preferred Qualifications:
- Exposure to machine learning and anomaly detection
- Familiarity with Kubernetes and Terraform
"""


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.p = Profile.load()

    def test_loads_bullets_and_skills(self):
        self.assertGreater(len(self.p.bullets), 20)
        self.assertGreater(len(self.p.skills), 20)

    def test_bullet_ids_unique_and_linked_to_parents(self):
        for bid, b in self.p.bullets.items():
            self.assertEqual(bid, b.id)
            self.assertTrue(b.parent_id, f"{bid} has no parent")
            self.assertTrue(b.parent_label, f"{bid} has no label")

    def test_skill_evidence_points_at_real_bullets(self):
        for s in self.p.skills:
            for bid in s.evidence:
                self.assertIn(bid, self.p.bullets, f"{s.name} cites missing bullet {bid}")

    def test_skill_lookup_by_alias(self):
        self.assertIsNotNone(self.p.skill("llm"))
        self.assertEqual(self.p.skill("llm").name, "Large Language Models")


class TestJD(unittest.TestCase):
    def setUp(self):
        self.jd = JobDescription.from_text(JD_TEXT, company="Acme", location="Singapore")

    def test_sections_split_correctly(self):
        self.assertIn("Proficiency in Python", self.jd.text_of("requirement"))
        self.assertIn("Kubernetes", self.jd.text_of("preferred"))
        self.assertIn("detection pipelines", self.jd.text_of("responsibility"))

    def test_preferred_not_counted_as_requirement(self):
        self.assertNotIn("Kubernetes", self.jd.text_of("requirement"))

    def test_slug_is_filesystem_safe(self):
        self.assertRegex(self.jd.slug(), r"^[a-z0-9-]+$")


class TestMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Profile.load()
        cls.jd = JobDescription.from_text(JD_TEXT, company="Acme", location="Singapore")
        cls.r = ats.match(cls.jd, cls.p)

    def test_covered_skills_have_evidence(self):
        terms = {m.term for m in self.r.by_status(ats.COVERED)}
        self.assertIn("Python", terms)
        self.assertIn("Network Security", terms)

    def test_real_gaps_are_flagged(self):
        gaps = {m.term for m in self.r.by_status(ats.MISSING)}
        self.assertIn("kubernetes", gaps)
        self.assertIn("terraform", gaps)

    def test_generic_phrasing_is_never_a_gap(self):
        gaps = {m.term for m in self.r.by_status(ats.MISSING)}
        for term in ("presentation", "technical documentation", "communication"):
            self.assertNotIn(term, gaps, f"{term} is boilerplate, not a real gap")

    def test_generic_weights_do_not_compound(self):
        # A bug once multiplied the per-line weight repeatedly, driving later
        # terms on the same line towards zero.
        for m in self.r.matches:
            if m.soft:
                self.assertGreaterEqual(m.weight, 0.1, f"{m.term} weight collapsed")

    def test_singular_and_plural_merge(self):
        jd = JobDescription.from_text(
            "Requirements:\n- smart contract and smart contracts experience\n"
        )
        r = ats.match(jd, self.p)
        terms = [m.term for m in r.matches]
        self.assertEqual(len(terms), len(set(terms)))
        self.assertEqual(sum(1 for t in terms if "smart contract" in t), 1)

    def test_graduation_year_mismatch_is_a_blocker(self):
        jd = JobDescription.from_text(
            "Requirements:\n- Must be graduating in 2024\n"
        )
        r = ats.match(jd, self.p)
        self.assertTrue(any(h.kind == "grad_year" and h.verdict == "blocker"
                            for h in r.hard_requirements))

    def test_senior_experience_is_a_blocker(self):
        jd = JobDescription.from_text("Requirements:\n- 8+ years of experience required\n")
        r = ats.match(jd, self.p)
        self.assertTrue(any(h.kind == "years" and h.verdict == "blocker"
                            for h in r.hard_requirements))

    def test_unreadable_requirements_are_surfaced(self):
        jd = JobDescription.from_text(
            "Requirements:\n- Willingness to travel to regional offices each quarter\n"
        )
        r = ats.match(jd, self.p)
        self.assertTrue(r.unmatched, "a requirement matching nothing must be surfaced")

    def test_evidence_ranking_is_deterministic(self):
        self.assertEqual(self.r.evidence_bullets, ats.match(self.jd, self.p).evidence_bullets)


class TestGrounding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Profile.load()
        cls.corpus = cls.p.corpus()
        cls.src = cls.p.bullet("packet_sniffer.b1")

    def _check(self, text):
        return verify_bullet(text, self.src.text, self.src.tags, self.corpus)

    def test_faithful_rewrite_passes(self):
        r = self._check(
            "Built a packet capture tool parsing over 10,000 Ethernet, IP, TCP "
            "and UDP packets in real time."
        )
        self.assertTrue(r.ok, [str(f) for f in r.findings])

    def test_inflated_number_is_blocked(self):
        r = self._check("Built a packet sniffer handling over 100,000 packets in real time.")
        self.assertFalse(r.ok)
        self.assertTrue(any("100000" in f.detail for f in r.errors))

    def test_invented_technology_is_blocked(self):
        r = self._check("Built a packet sniffer deployed on Kubernetes with Terraform.")
        self.assertFalse(r.ok)

    def test_real_skill_in_wrong_place_only_warns(self):
        r = self._check("Built a packet sniffer and modelled the traffic with XGBoost.")
        self.assertTrue(r.ok)
        self.assertTrue(r.warnings)

    def test_number_equivalence_is_understood(self):
        # 10,000 and 10000 are the same claim.
        r = self._check("Captured 10000 packets across Ethernet, IP, TCP and UDP.")
        self.assertTrue(r.ok, [str(f) for f in r.findings])

    def test_free_text_allows_company_name(self):
        r = verify_free_text(
            "I am applying to Acme Corp for the Security Engineer role.",
            self.corpus,
            allowed_terms=["Acme Corp", "Security Engineer"],
            where="letter",
        )
        self.assertTrue(r.ok, [str(f) for f in r.findings])

    def test_free_text_blocks_invented_tech(self):
        r = verify_free_text("I have deep Kubernetes and Terraform experience.",
                             self.corpus, allowed_terms=[], where="letter")
        self.assertFalse(r.ok)


class TestDeterministicTailoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Profile.load()
        cls.jd = JobDescription.from_text(JD_TEXT, company="Acme", location="Singapore")
        cls.t = tailor_deterministic(cls.jd, cls.p)

    def test_produces_content(self):
        self.assertGreater(self.t.bullet_count, 5)
        self.assertTrue(self.t.experience)

    def test_every_bullet_traces_to_a_real_source(self):
        for s in self.t.all_sections:
            for b in s.bullets:
                self.assertIn(b.source_id, self.p.bullets)

    def test_wording_is_untouched(self):
        for s in self.t.all_sections:
            for b in s.bullets:
                self.assertEqual(b.text, self.p.bullet(b.source_id).text)

    def test_only_real_skills_are_listed(self):
        for line in self.t.skills_lines.values():
            for name in line.split(","):
                self.assertIsNotNone(self.p.skill(name.strip()))

    def test_bullets_sit_under_their_own_role(self):
        for s in self.t.all_sections:
            for b in s.bullets:
                self.assertEqual(self.p.bullet(b.source_id).parent_id, s.parent_id)


class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Profile.load()
        jd = JobDescription.from_text(JD_TEXT, company="Acme")
        cls.t = tailor_deterministic(jd, cls.p)

    def test_docx_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            out = render.render_resume_docx(self.t, self.p, Path(d) / "r.docx")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 10_000)

    def test_plain_text_has_the_essentials(self):
        txt = render.render_resume_text(self.t, self.p)
        self.assertIn("NICHOLAS", txt.upper())
        self.assertIn("EDUCATION", txt)
        self.assertIn("EXPERIENCE", txt)
        self.assertIn(str(self.p.meta["email"]), txt)


class TestTracker(unittest.TestCase):
    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            tr = Tracker(Path(d) / "t.db")
            tr.upsert("acme-sec", company="Acme", title="Security Engineer",
                      required_score=87.5, deadline="2027-01-01")
            tr.set_status("acme-sec", "drafted", "docs built")
            tr.set_status("acme-sec", "applied")
            a = tr.get("acme-sec")
            self.assertEqual(a.status, "applied")
            self.assertIsNotNone(a.applied_at)
            self.assertEqual(len(tr.events("acme-sec")), 2)
            self.assertEqual(tr.counts(), {"applied": 1})

    def test_unknown_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            tr = Tracker(Path(d) / "t.db")
            tr.upsert("x")
            with self.assertRaises(ValueError):
                tr.set_status("x", "hired")

    def test_upsert_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            tr = Tracker(Path(d) / "t.db")
            first = tr.upsert("x", company="A")
            second = tr.upsert("x", company="A Corp")
            self.assertEqual(first, second)
            self.assertEqual(tr.get("x").company, "A Corp")


class TestJSONExtraction(unittest.TestCase):
    def test_handles_fences_and_prose(self):
        self.assertEqual(extract_json('ok\n```json\n{"a":1}\n```'), {"a": 1})
        self.assertEqual(extract_json('{"a":1}'), {"a": 1})
        self.assertEqual(extract_json('prose then {"a":[1,2]} after'), {"a": [1, 2]})

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            extract_json("no json here")


if __name__ == "__main__":
    unittest.main(verbosity=2)
