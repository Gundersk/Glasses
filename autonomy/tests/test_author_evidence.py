"""Offline synthetic tests; no actual research artifacts are opened."""
import hashlib
import json
import unittest
from unittest.mock import patch

from autonomy import intake
from autonomy.author_evidence import AuthorEvidenceError, author_bundle, _excerpts
from autonomy.tests import test_intake


class AuthorEvidenceTests(unittest.TestCase):
    def test_v2_query_and_selected_cap_checked_even_when_unavailable(self):
        from autonomy.tests.test_source_outcomes import document
        a, b, c = ('https://example.org/' + key for key in ('a', 'b', 'c'))
        variants = [document(selected=[a], errors=['bot_blocked'], query='wrong query'),
                    document(selected=[a, b, c], errors=['bot_blocked'] * 3, query=self.spec['research_queries'][0]),
                    document(selected=[a, b, c], pages=[{'url': a, 'content': 'actual page'}],
                             errors=['bot_blocked'] * 2, query=self.spec['research_queries'][0])]
        for doc in variants:
            (self.base / 'sources-0.md.json').write_text(json.dumps(doc), encoding='utf-8')
            with self.assertRaises(AuthorEvidenceError):
                author_bundle(self.card, [self.name])

    def test_preferred_quote_crossing_prefix_stays_contiguous(self):
        for budget, start, size in ((3000, 990, 200), (3000, 900, 2500)):
            quote = 'Q' * size
            text = 'x' * start + quote + 'y' * 10000
            spans = _excerpts(text, budget, set(), [quote], set())
            self.assertTrue(any(quote in text[a:b] for a, b in spans))
            self.assertLessEqual(sum(b - a for a, b in spans), budget)
            self.assertTrue(all(b <= c for (a, b), (c, d) in zip(spans, spans[1:])))

    def setUp(self):
        test_intake.IntakeTests.setUp(self)
        self.card = {"spec": self.spec, "sha256": "fixture"}
        self.base = intake.root(self.spec["id"])
        self.base.mkdir(parents=True)
        self.name = intake.rel(self.base / "sources-0.md.json")

    def save(self, pages, index=0):
        fp = self.base / f"sources-{index}.md.json"
        fp.write_text(json.dumps({"sources": pages}, ensure_ascii=False), encoding="utf-8")
        return intake.rel(fp)

    def bundle(self, pages, **kwargs):
        self.save(pages)
        return json.loads(author_bundle(self.card, ["docs/context.json", self.name], **kwargs))

    def page(self, text, suffix="1"):
        return {"url": "https://example.org/" + suffix, "content": text}

    def test_late_second_page_query(self):
        text = "unrelated " * 9000 + " CPU relevant unique quotation " + "tail " * 1000
        packet = self.bundle([self.page("short"), self.page(text, "2")])
        self.assertEqual(len(packet["sources"]), 2)
        self.assertIn("CPU relevant unique quotation", str(packet["sources"][1]["excerpts"]))

    def test_urls_and_limit_and_balance(self):
        self.spec["research_policy"] = {"max_queries": 6, "pages_per_query": 3, "topics": ["CPU"]}
        pages = [self.page("noise " * 30000, str(i)) for i in range(3)]
        self.save(pages)
        raw = author_bundle(self.card, [self.name])
        self.assertLessEqual(len(raw), 60000)
        result = json.loads(raw)["sources"]
        self.assertEqual([p["url"] for p in result], [p["url"] for p in pages])
        self.assertLessEqual(max(p["visible_characters"] for p in result) - min(p["visible_characters"] for p in result), 1)

    def test_malformed_each_file(self):
        self.spec["research_queries"].append("second")
        self.save([self.page("ok")])
        self.save([self.page("ok")], 1)
        other = intake.rel(self.base / "sources-1.md.json")
        for raw in ('{}', '{', '{"sources": [1]}', '{"sources": []}', '{"sources":[{"url":1,"content":"x"}]}'):
            (self.base / "sources-1.md.json").write_text(raw, encoding="utf-8")
            with self.subTest(raw=raw), self.assertRaises(AuthorEvidenceError):
                author_bundle(self.card, [self.name, other])

    def test_metadata_overflow(self):
        self.spec["research_policy"] = {"max_queries": 6, "pages_per_query": 3, "topics": ["CPU"]}
        self.save([{"url": "x" * 1999 + str(i), "content": "word " * 500} for i in range(3)])
        with self.assertRaises(AuthorEvidenceError):
            author_bundle(self.card, [self.name], max_chars=8000)

    def test_omission_and_offsets(self):
        text = "begin \n " + "filler " * 15000 + " CPU end"
        packet = self.bundle([self.page(text)])
        page = packet["sources"][0]
        normalized = " ".join(text.split())
        self.assertFalse(page["full_source"])
        self.assertEqual(page["source_characters"], len(normalized))
        self.assertEqual(page["visible_characters"] + page["omitted_characters"], len(normalized))
        self.assertEqual(packet["omitted_characters"], page["omitted_characters"])
        self.assertEqual(page["visible_characters"], sum(len(x["text"]) for x in page["excerpts"]))
        for excerpt in page["excerpts"]:
            self.assertEqual(excerpt["text"], normalized[excerpt["start"]:excerpt["end"]])

    def test_existing_quote_retained(self):
        quote = "unique repair quotation at end"
        text = "boring " * 20000 + quote
        claim = {"evidence_file": self.name, "source_url": self.page("")["url"], "quote": quote}
        result = self.bundle([self.page(text)], claims=[claim])
        self.assertTrue(any(quote in e["text"] for e in result["sources"][0]["excerpts"]))

    def test_missing_quote_not_invented(self):
        claim = {"evidence_file": self.name, "source_url": self.page("")["url"], "quote": "invented quote"}
        self.assertNotIn("invented quote", json.dumps(self.bundle([self.page("real text")], claims=[claim])))

    def test_hash_reproducible(self):
        self.save([self.page("hello")])
        a = author_bundle(self.card, [self.name])
        self.assertEqual(a, author_bundle(self.card, [self.name]))
        self.assertEqual(json.loads(a)["sources"][0]["source_sha256"], hashlib.sha256((self.base / "sources-0.md.json").read_bytes()).hexdigest())

    def test_unknown_source_rejected_before_read(self):
        self.save([self.page("ok")])
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("must not read")):
            with self.assertRaises(AuthorEvidenceError):
                author_bundle(self.card, [self.name, "../sources-99.md.json"])

    def test_missing_selected_fails_unused_does_not(self):
        self.spec["research_queries"].append("second")
        self.save([self.page("ok")])
        self.assertTrue(author_bundle(self.card, [self.name]))
        with self.assertRaises(AuthorEvidenceError):
            author_bundle(self.card, [intake.rel(self.base / "sources-1.md.json")])

    def test_default_policy_and_legacy(self):
        self.save([self.page("hello")])
        self.assertTrue(author_bundle(self.card, [self.name]))
        self.spec["research_policy"] = {"max_queries": 6, "pages_per_query": 3, "topics": ["CPU"]}
        self.assertTrue(author_bundle(self.card, [self.name]))

    def test_bad_budget(self):
        for budget in (True, 7999, 60001, float("nan")):
            with self.subTest(budget=budget), self.assertRaises(AuthorEvidenceError):
                author_bundle(self.card, [], max_chars=budget)

    def test_empty_or_bad_content(self):
        for content in (None, "   ", 3):
            with self.subTest(content=content), self.assertRaises(AuthorEvidenceError):
                self.bundle([self.page(content)])


if __name__ == "__main__":
    unittest.main()
