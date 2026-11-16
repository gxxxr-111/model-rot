"""Offline tests with fixture copies of the three page formats. Run: python3 -m unittest discover tests"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import modelrot as mr  # noqa: E402

FX = Path(__file__).parent / "fx"
TODAY = dt.date(2026, 11, 17)


def db():
    d = {}
    for e in (mr.parse_markdown_tables((FX / "anthropic.md").read_text(), "anthropic", "a")
              + mr.parse_html_tables((FX / "openai.html").read_text(), "openai", "o")
              + mr.parse_markdoc_tables((FX / "gemini.md").read_text(), "gemini", "g")):
        d.setdefault(e.id.lower(), e)
    return d


class ModelRot(unittest.TestCase):
    def setUp(self):
        mr.TODAY = TODAY
        self.db = db()

    def st(self, mid):
        e = next((self.db[c] for c in mr.normalize(mid) if c in self.db), None)
        return e.status(TODAY) if e else "unknown"

    def test_four_states_across_formats(self):
        self.assertEqual(self.st("claude-gone-20240620"), "retired")
        self.assertEqual(self.st("claude-old-1-20240101"), "retiring")
        self.assertEqual(self.st("claude-new-9"), "no date", "active + 'not sooner than' is not a retirement")
        self.assertEqual(self.st("gpt-x-2024-08-06"), "retiring", "IDs listed inside parentheses")
        self.assertEqual(self.st("gemini-old-flash"), "retired")
        self.assertEqual(self.st("gemini-pro-x"), "aliasing")
        self.assertEqual(self.db["gemini-pro-x"].alias_date, dt.date(2026, 12, 1))
        self.assertEqual(self.st("assistants api"), "retired")

    def test_bedrock_and_vertex_forms(self):
        self.assertEqual(self.st("us.anthropic.claude-old-1-20240101-v1:0"), "retiring")
        self.assertEqual(mr.normalize("claude-old-1@20240101")[-1], "claude-old-1-20240101")

    def test_scan_case_sensitive_and_api(self):
        hits = mr.scan(FX / "app", self.db)
        found = sorted((h.match, h.entry.status(TODAY)) for h in hits)
        self.assertEqual(found, [("Assistants API", "retired"), ("claude-gone-20240620", "retired"),
                                 ("claude-new-9", "no date"), ("gemini-pro-x", "aliasing"),
                                 ("gpt-x-2024-08-06", "retiring"), ("us.anthropic.claude-old-1-20240101-v1:0", "retiring")])

    def test_date_parsing(self):
        self.assertEqual(mr.parse_date("Not sooner than June 9, 2027"), (dt.date(2027, 6, 9), True))
        self.assertEqual(mr.parse_date("Jan 14, 2027")[0], dt.date(2027, 1, 14))
        self.assertEqual(mr.parse_date("To be announced"), (None, False))


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        mr.TODAY = TODAY
        self.db = db()
        for key, e in list(self.db.items()):
            m = __import__("re").match(r"^(.*)-(\d{8})$", key)
            if m:
                for alias in (m.group(1), m.group(1) + "-latest"):
                    self.db.setdefault(alias, e)

    def scan_text(self, text, name="a.py"):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / name).write_text(text)
            return sorted(h.match for h in mr.scan(Path(t), self.db))

    def test_forms_in_code(self):
        src = ('url = "models/gemini-old-flash:generateContent"\n'
               'm = "openai/gpt-x-2024-08-06"\n'
               'ft = "ft:gpt-x-2024-08-06:org::abc"\n'
               'alias = "claude-gone-latest"\n'
               'b = "au.anthropic.claude-gone-20240620-v1:0"\n'
               'v = "claude-gone-v2@20240620"\n')
        self.assertEqual(self.scan_text(src), ["au.anthropic.claude-gone-20240620-v1:0", "claude-gone-latest",
                                               "claude-gone-v2@20240620", "gemini-old-flash", "gpt-x-2024-08-06",
                                               "gpt-x-2024-08-06"])

    def test_bare_o_variables_and_assistants_variants(self):
        self.assertEqual(self.scan_text("o1 = 3\no3 = 4\n"), [])
        self.assertEqual(self.scan_text("from langchain.agents.openai_assistant import OpenAIAssistantRunnable\n"
                                        "requests.get('https://graph.threads.net/v1/threads')\n"), ["Assistants API"])

    def test_long_token_is_linear(self):
        import time
        t0 = time.time()
        self.scan_text("x = '" + "a" * 200_000 + "'\n", "big.json")
        self.assertLess(time.time() - t0, 2.0)

    def test_alias_routing_wording_and_agent_tables(self):
        rows = mr.rows_to_entries(["Agent", "Release", "Shutdown date", "Recommended replacement"],
                                  [["`deep-agent-1`", "May 1, 2025", "March 1, 2026", ""],
                                   ["`flash-omni`", "x", "December 3, 2026", "Effective December 3, 2026, automatically routing to `omni-2`"]],
                                  "gemini", "g")
        st = {e.id: e.status(TODAY) for e in rows}
        self.assertEqual(st, {"deep-agent-1": "retired", "flash-omni": "aliasing"})

    def test_bad_path_exits_nonzero(self):
        with self.assertRaises(SystemExit) as c:
            mr.main(["/nonexistent/path/xyz"])
        self.assertNotEqual(c.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
