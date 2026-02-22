import asyncio
import json
import re
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.change_detector import hash_content
from app.settings import config


# ---------------------------
# polite rate limiter
# ---------------------------
class RateLimiter:
    def __init__(self, delay: float):
        self.delay = delay
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            gap = now - self._last
            if gap < self.delay:
                await asyncio.sleep(self.delay - gap)
            self._last = asyncio.get_event_loop().time()


rate_limiter = RateLimiter(config.REQUEST_DELAY_SEC)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def fetch(url: str) -> str:
    await rate_limiter.wait()
    headers = {"User-Agent": config.USER_AGENT}

    async with httpx.AsyncClient(
        timeout=config.REQUEST_TIMEOUT,
        headers=headers,
        follow_redirects=True,
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


def _clean_text(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return t


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ---------------------------
# FEES extraction
# ---------------------------
_MONEY = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\b")


def _extract_tables(soup: BeautifulSoup, max_tables: int = 3, max_rows: int = 25) -> List[List[List[str]]]:
    """
    Return list of tables, each table is list of rows, row is list of cell texts.
    """
    tables_out = []
    tables = soup.select("table")[:max_tables]
    for table in tables:
        rows_out = []
        for tr in table.select("tr")[:max_rows]:
            cells = tr.find_all(["th", "td"])
            row = [_clean_text(c.get_text(" ")) for c in cells]
            row = [c for c in row if c]
            if row:
                rows_out.append(row)
        if rows_out:
            tables_out.append(rows_out)
    return tables_out


def extract_fees(html: str) -> Dict:
    soup = _soup(html)
    text = _clean_text(soup.get_text(" "))

    # Try tables first (more accurate)
    tables = _extract_tables(soup)
    key_values = {}

    # Heuristic: search label -> money in full text
    def find_money(label: str) -> Optional[str]:
        m = re.search(rf"{label}[^$]*\$\s*([0-9,]+)", text, re.IGNORECASE)
        return f"${m.group(1)}" if m else None

    key_values["tuition"] = find_money("Tuition")
    key_values["fees"] = find_money("Fees")
    key_values["housing"] = find_money("Housing|Room")
    key_values["food"] = find_money("Food|Board|Meal")
    key_values["books"] = find_money("Books")
    key_values["travel"] = find_money("Travel|Transportation")
    key_values["personal"] = find_money("Personal")

    # compute rough “total” if many values exist
    total = None
    nums = []
    for v in key_values.values():
        if isinstance(v, str) and v.startswith("$"):
            nums.append(int(v[1:].replace(",", "")))
    if len(nums) >= 3:
        total = f"${sum(nums):,}"

    return {
        "summary": key_values,
        "estimated_total_maybe": total,
        "tables": tables,  # helpful for UI or debugging
        "note": "Fees extracted from official page text/tables; values can vary by year/program. Verify on the official page."
    }


# ---------------------------
# ADMISSIONS extraction
# ---------------------------
def extract_admissions(html: str) -> Dict:
    soup = _soup(html)

    # bullets + headings
    headings = [_clean_text(h.get_text(" ")) for h in soup.select("h1, h2, h3")][:30]
    bullets = [_clean_text(li.get_text(" ")) for li in soup.select("li")]

    # likely requirement bullets
    reqs = []
    for b in bullets:
        low = b.lower()
        if any(k in low for k in ["recommend", "required", "requirement", "years", "transcript", "essay", "teacher", "recommendation", "testing", "sat", "act"]):
            if 20 <= len(b) <= 220:
                reqs.append(b)

    # de-dup
    uniq = []
    seen = set()
    for r in reqs:
        if r not in seen:
            uniq.append(r)
            seen.add(r)

    return {
        "headings": headings,
        "requirements": uniq[:40],
        "note": "Admissions requirements are extracted from headings/bullets. Always verify on the official admissions page."
    }


# ---------------------------
# DEADLINES extraction
# ---------------------------
_MONTHS = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_LINE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}})\b", re.IGNORECASE)


def extract_deadlines(html: str) -> Dict:
    soup = _soup(html)
    text = soup.get_text("\n")
    lines = [_clean_text(l) for l in text.splitlines()]
    lines = [l for l in lines if l]

    # Pick lines that contain common deadline phrases
    candidates = []
    for l in lines:
        low = l.lower()
        if any(k in low for k in ["deadline", "early", "regular", "decision", "single-choice", "financial aid", "questbridge", "due"]):
            if 10 <= len(l) <= 240:
                # prefer lines with dates
                if _DATE_LINE.search(l) or any(m in low for m in ["nov", "jan", "feb", "mar", "apr", "may", "dec", "oct", "sep", "aug", "jul", "jun"]):
                    candidates.append(l)

    # Also look for “Nov 1”, “January 2” style lines in the whole page
    date_snips = []
    for l in lines:
        if _DATE_LINE.search(l):
            if 10 <= len(l) <= 200:
                date_snips.append(l)

    # De-dup
    def dedup(items: List[str], limit: int) -> List[str]:
        seen = set()
        out = []
        for it in items:
            if it not in seen:
                out.append(it)
                seen.add(it)
            if len(out) >= limit:
                break
        return out

    candidates = dedup(candidates, 25)
    date_snips = dedup(date_snips, 25)

    # Attempt to infer common buckets (very basic)
    buckets = {"early": None, "regular": None}
    joined = " | ".join(lines).lower()
    if "nov" in joined and "early" in joined:
        buckets["early"] = "Likely around Nov (check official page)"
    if "jan" in joined and "regular" in joined:
        buckets["regular"] = "Likely around Jan (check official page)"

    return {
        "highlights": candidates,
        "date_lines": date_snips,
        "inferred": buckets,
        "note": "Deadlines extracted from lines containing date/deadline keywords. Confirm on official page."
    }


# ---------------------------
# PROGRAMS/MAJORS extraction
# ---------------------------
def extract_programs(html: str) -> Dict:
    soup = _soup(html)

    # Usually majors are links or list items; gather link texts
    link_texts = []
    for a in soup.select("a"):
        t = _clean_text(a.get_text(" "))
        if 3 <= len(t) <= 60:
            # filter obvious nav junk
            low = t.lower()
            if any(x in low for x in ["apply", "admission", "financial", "contact", "login", "search", "privacy", "cookie", "menu"]):
                continue
            link_texts.append(t)

    # Also list item texts
    li_texts = [_clean_text(li.get_text(" ")) for li in soup.select("li")]
    li_texts = [t for t in li_texts if 3 <= len(t) <= 80]

    # Merge + filter to “program-like”
    combined = link_texts + li_texts
    programs = []
    for t in combined:
        low = t.lower()
        if any(k in low for k in ["studies", "engineering", "science", "mathematics", "history", "economics", "biology", "computer", "physics", "chemistry", "philosophy", "political", "sociology", "psychology", "language", "literature", "art", "music", "anthropology"]):
            programs.append(t)

    # de-dup, keep top
    seen = set()
    uniq = []
    for p in programs:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
        if len(uniq) >= 120:
            break

    return {
        "programs": uniq,
        "count_estimate": len(uniq),
        "note": "Programs extracted from link/list texts and filtered heuristically. Official catalogs are the source of truth."
    }


# ---------------------------
# AID + ABOUT extraction
# ---------------------------
def extract_summary_paragraphs(html: str, max_paras: int = 3) -> List[str]:
    soup = _soup(html)
    paras = []
    for p in soup.select("p"):
        t = _clean_text(p.get_text(" "))
        if 60 <= len(t) <= 350:
            paras.append(t)
        if len(paras) >= max_paras:
            break
    return paras


def extract_aid(html: str) -> Dict:
    paras = extract_summary_paragraphs(html, max_paras=4)
    return {
        "summary": paras,
        "note": "Financial aid summary extracted from top paragraphs. Use official page for details."
    }


def extract_about(html: str) -> Dict:
    paras = extract_summary_paragraphs(html, max_paras=4)
    return {
        "overview": paras,
        "note": "About/overview extracted from top paragraphs. Use official page for details."
    }


# ---------------------------
# Entry point per source
# ---------------------------
def extract_by_type(page_type: str, html: str) -> Dict:
    if page_type == "fees":
        return extract_fees(html)
    if page_type == "admissions":
        return extract_admissions(html)
    if page_type == "deadlines":
        return extract_deadlines(html)
    if page_type == "programs":
        return extract_programs(html)
    if page_type == "aid":
        return extract_aid(html)
    if page_type == "about":
        return extract_about(html)

    # fallback
    soup = _soup(html)
    return {"text_preview": _clean_text(soup.get_text(" "))[:2000]}


async def scrape_one(source: Dict) -> Dict:
    url = source["url"]
    html = await fetch(url)
    h = hash_content(html)
    data = extract_by_type(source["page_type"], html)
    return {
        "university": source["university"],
        "page_type": source["page_type"],
        "url": url,
        "hash": h,
        "data_json": json.dumps(data, ensure_ascii=False),
    }