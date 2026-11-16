#!/usr/bin/env python3
"""model-rot: find AI model IDs and APIs in your code that providers have retired, or are about to.

Reads the providers' OWN deprecation pages live (Anthropic, OpenAI, Google
Gemini; cached 24 h), so the data is never a stale hand-made list, then scans
code, configs and docs for model IDs and retired API usage. Each hit gets one
of four states: retired (requests fail), retiring on DATE, silently aliased
(requests are routed to another model), or no date announced. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SOURCES = {
    "anthropic": "https://platform.claude.com/docs/en/about-claude/model-deprecations.md",
    "openai": "https://developers.openai.com/api/docs/deprecations",
    "gemini": "https://ai.google.dev/gemini-api/docs/deprecations.md.txt",
}
CACHE = Path(os.environ.get("MODEL_ROT_CACHE", Path.home() / ".cache" / "model-rot"))
TODAY = dt.date.today()
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
ID_RX = re.compile(r"(?<![\w./-])((?:claude|gpt|chatgpt|gemini|text-embedding|dall-e|whisper|imagen|veo|tts|davinci|babbage|"
                   r"computer-use|codex|omni-moderation|text-moderation|o[1-9])(?:-[\w.]+)*)(?![\w/-])")
API_PATTERNS = [  # (name as it appears on the provider page, code regex)
    ("Assistants API", re.compile(r"\bbeta\.(assistants|threads)\b|/v1/assistants\b|/v1/threads\b|OpenAIAssistant\b")),
]
SCAN_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs",
            ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".md", ".mdx", ".txt", ".sh"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".next", "vendor", "site-packages"}
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock"}


@dataclass
class Entry:
    id: str
    provider: str
    date: dt.date | None = None
    earliest: bool = False       # "not sooner than" / "earliest possible"
    replacement: str = ""
    aliased: bool = False
    alias_date: dt.date | None = None
    source: str = ""

    def status(self, today=None) -> str:
        today = today or TODAY
        if self.aliased and (self.alias_date is None or self.alias_date <= today):
            return "aliased"
        if self.date is None:
            return "aliasing" if self.aliased else "no date"
        if self.date <= today:
            return "retired"
        return "aliasing" if self.aliased else "retiring"


@dataclass
class Hit:
    file: str
    line: int
    match: str
    entry: Entry | None
    kind: str = "model"            # model / api
    note: str = ""


# ---------------------------------------------------------------- fetching

def fetch(provider: str, refresh=False, max_age=86400) -> tuple[str, float]:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{provider}.txt"
    if p.exists() and not refresh and time.time() - p.stat().st_mtime < max_age:
        return p.read_text(), p.stat().st_mtime
    req = urllib.request.Request(SOURCES[provider], headers={"User-Agent": "model-rot/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8", "replace")
    p.write_text(text)
    return text, time.time()


# ---------------------------------------------------------------- parsing

def parse_date(s: str) -> tuple[dt.date | None, bool]:
    s = s.strip()
    earliest = bool(re.search(r"not sooner than|earliest|no earlier than", s, re.I))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), earliest
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1).lower()[:3] in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()[:3]], int(m.group(2))), earliest
    return None, earliest


def ids_in(cell: str) -> list[str]:
    # drop prose parentheticals ("(… no longer available …; routes to …)"), keep ID lists like "GPT-4o (gpt-4o-…)"
    cell = re.sub(r"\([^)]*(?:no longer|route|effective|available|shutting)[^)]*\)", " ", cell, flags=re.I)
    return [m.group(1) for m in ID_RX.finditer(cell.replace("`", " "))]


def rows_to_entries(header: list[str], rows: list[list[str]], provider: str, src: str) -> list[Entry]:
    h = [c.lower() for c in header]
    id_col = next((i for i, c in enumerate(h) if "model" in c or "name" in c or "affected" in c), None)
    date_col = next((i for i, c in enumerate(h) if "retire" in c or "shutdown" in c), None)
    rep_col = next((i for i, c in enumerate(h) if "replacement" in c), None)
    state_col = next((i for i, c in enumerate(h) if c.strip() in ("current state", "state", "status")), None)
    out = []
    if id_col is None or date_col is None:
        return out
    for r in rows:
        if len(r) <= max(id_col, date_col):
            continue
        date, earliest = parse_date(r[date_col])
        if state_col is not None and state_col < len(r) and r[state_col].strip().lower() == "active":
            date = None   # an active model's "not sooner than" date is a promise, not an announced retirement
        rep = r[rep_col] if rep_col is not None and rep_col < len(r) else ""
        aliased = bool(re.search(r"\broutes?\b.*\bto\b|alias", rep, re.I))
        alias_date = None
        if aliased:
            m = re.search(r"effective\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", rep)
            alias_date = parse_date(m.group(1))[0] if m else None
        ids = ids_in(r[id_col])
        if not ids and r[id_col].strip():
            ids = [r[id_col].strip()]          # a feature/API row, e.g. "Assistants API"
        for i in ids:
            out.append(Entry(i, provider, date, earliest, re.sub(r"\s+", " ", rep)[:120], aliased, alias_date, src))
    return out


def parse_markdown_tables(text: str, provider: str, src: str) -> list[Entry]:
    out, block = [], []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2:
            cells = [[c.strip() for c in l.strip().strip("|").split("|")] for l in block]
            body = [c for c in cells[1:] if not all(re.fullmatch(r":?-+:?", x) for x in c if x)]
            out += rows_to_entries(cells[0], body, provider, src)
        block = []
    return out


def parse_markdoc_tables(text: str, provider: str, src: str) -> list[Entry]:
    out = []
    for blk in re.findall(r"\{%\s*table\s*%\}(.*?)\{%\s*/table\s*%\}", text, re.S):
        rows = []
        for part in re.split(r"^\s*---\s*$", blk, flags=re.M):
            cells, cur = [], None
            for line in part.splitlines():
                m = re.match(r"^\s*\*\s?(.*)$", line)
                if m:
                    if cur is not None:
                        cells.append(cur.strip())
                    cur = m.group(1)
                elif cur is not None and line.strip():
                    cur += " " + line.strip()
            if cur is not None:
                cells.append(cur.strip())
            if cells:
                rows.append(cells)
        if len(rows) >= 2:
            out += rows_to_entries(rows[0], rows[1:], provider, src)
    return out


def parse_html_tables(text: str, provider: str, src: str) -> list[Entry]:
    out = []
    for tbl in re.findall(r"<table[^>]*>(.*?)</table>", text, re.S):
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
            cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                     for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            if cells:
                rows.append(cells)
        if len(rows) >= 2:
            out += rows_to_entries(rows[0], rows[1:], provider, src)
    return out


PARSERS = {"anthropic": parse_markdown_tables, "openai": parse_html_tables, "gemini": parse_markdoc_tables}


def load_db(refresh=False) -> tuple[dict[str, Entry], dict[str, str]]:
    db: dict[str, Entry] = {}
    meta: dict[str, str] = {}
    for prov, url in SOURCES.items():
        try:
            text, ts = fetch(prov, refresh)
        except Exception as e:  # noqa: BLE001 - report and continue with other providers
            meta[prov] = f"unavailable ({e.__class__.__name__})"
            continue
        entries = PARSERS[prov](text, prov, url)
        for e in entries:
            key = e.id.lower()
            old = db.get(key)
            # keep the most informative row: one with a date beats one without
            if old is None or (old.date is None and e.date is not None):
                db[key] = e
        meta[prov] = f"{len(entries)} rows, fetched {dt.datetime.fromtimestamp(ts):%Y-%m-%d %H:%M}"
    return db, meta


# ---------------------------------------------------------------- scanning

def normalize(model: str) -> list[str]:
    """Candidate DB keys for an ID found in code (provider prefixes, Bedrock/Vertex forms)."""
    m = model.lower()
    cands = [m]
    m2 = re.sub(r"^(?:(?:us|eu|apac|global)\.)?anthropic\.", "", m)       # Bedrock
    m2 = re.sub(r"-v\d+(?::\d+)?$", "", m2)
    m2 = re.sub(r"@(\d{8})$", r"-\1", m2)                                 # Vertex claude-x@20250514
    if m2 != m:
        cands.append(m2)
    return cands


def scan(root: Path, db: dict[str, Entry], include_docs=True) -> list[Hit]:
    hits = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or set(rel.parts[:-1]) & SKIP_DIRS or p.name in LOCKFILES:
            continue
        if p.suffix not in SCAN_EXT and p.name not in (".env", ".env.example"):
            continue
        if not include_docs and p.suffix in (".md", ".mdx", ".txt"):
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            for m in re.finditer(r"[\w.@:-]*(?:claude|gpt|gemini|o[1-9]|text-embedding|dall-e|whisper|imagen|chatgpt|"
                                 r"davinci|babbage|codex|tts)[\w.@:-]*", line, re.I):
                token = m.group(0).strip(".:-")
                if token != token.lower():
                    continue   # API model IDs are lowercase; "GPT-4" / "Claude 3" are display labels
                ent = next((db[c] for c in normalize(token) if c in db), None)
                if ent:
                    note = "Bedrock/Vertex ID: those platforms keep their own schedules" if normalize(token)[-1] != token.lower() else ""
                    hits.append(Hit(str(rel), n, token, ent, "model", note))
            for name, rx in API_PATTERNS:
                if rx.search(line):
                    ent = db.get(name.lower())
                    hits.append(Hit(str(rel), n, name, ent, "api"))
    return hits


# ---------------------------------------------------------------- CLI

ORDER = {"retired": 0, "aliased": 1, "retiring": 2, "aliasing": 3, "no date": 4, "unknown": 5}


def describe(e: Entry | None, today=None) -> str:
    if e is None:
        return "unknown"
    s = e.status(today)
    d = (f"not sooner than {e.date}" if e.earliest else str(e.date)) if e.date else ""
    rep = f" → {e.replacement}" if e.replacement and not e.aliased else ""
    if s == "retired":
        return f"retired {d}: requests fail{rep}"
    if s == "retiring":
        days = (e.date - (today or TODAY)).days
        return f"retiring {d} (in {days} days){rep}"
    if s in ("aliased", "aliasing"):
        when = f" from {e.alias_date}" if e.alias_date else ""
        return f"silently aliased{when}: {e.replacement}"
    return "no retirement date announced"


def render(hits: list[Hit], meta: dict[str, str], root: Path, days: int) -> str:
    groups: dict[str, list[Hit]] = {}
    for h in hits:
        groups.setdefault(h.entry.status() if h.entry else "unknown", []).append(h)
    L = [f"# model-rot report: {root.name}", "", "Sources (official pages, parsed live): " +
         "; ".join(f"[{p}]({SOURCES[p]}) {m}" for p, m in meta.items()), ""]
    soon = [h for h in groups.get("retiring", []) if h.entry and h.entry.date and (h.entry.date - TODAY).days <= days]
    L.append(f"**{len(groups.get('retired', []))} retired** · **{len(groups.get('aliased', []))} silently aliased** · "
             f"**{len(soon)} retiring within {days} days** · {len(groups.get('retiring', [])) - len(soon)} later · "
             f"{len(groups.get('no date', []))} with no date")
    for st in sorted(groups, key=lambda s: ORDER.get(s, 9)):
        if st == "no date":
            continue
        L += ["", f"## {st}", ""]
        seen = set()
        for h in sorted(groups[st], key=lambda h: (h.match, h.file, h.line)):
            key = (h.file, h.line, h.match)
            if key in seen:
                continue
            seen.add(key)
            extra = f" ({h.note})" if h.note else ""
            L.append(f"- `{h.file}:{h.line}` **{h.match}**: {describe(h.entry)}{extra}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="modelrot", description=__doc__.split("\n\n")[0])
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--days", type=int, default=60, help="'retiring soon' window (default 60)")
    ap.add_argument("--no-docs", action="store_true", help="skip .md/.txt files")
    ap.add_argument("--refresh", action="store_true", help="re-download provider pages")
    ap.add_argument("--lookup", nargs="+", metavar="MODEL", help="just look up model IDs")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    db, meta = load_db(a.refresh)
    if a.lookup:
        for mid in a.lookup:
            e = next((db[c] for c in normalize(mid) if c in db), None)
            print(f"{mid}: {describe(e)}" + (f"  [{e.source}]" if e else ""))
        return
    root = Path(a.path).resolve()
    hits = scan(root, db, not a.no_docs)
    if a.json:
        print(json.dumps([{"file": h.file, "line": h.line, "match": h.match, "kind": h.kind,
                           "status": h.entry.status() if h.entry else "unknown", "detail": describe(h.entry)} for h in hits],
                         indent=1))
    else:
        print(render(hits, meta, root, a.days))
    bad = any(h.entry and (h.entry.status() in ("retired", "aliased") or
                           (h.entry.status() == "retiring" and h.entry.date and (h.entry.date - TODAY).days <= a.days))
              for h in hits)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
