"""Yale SOM course catalogue MCP — Lecture 9 starter.

In class you'll add real tools that read ../data/yale_som.db.
Right now there is a placeholder tool plus any tools you add.

Run from this folder (stdio):  python mcp_server.py
Run (HTTP):                    python mcp_server.py --http
HTTP URL:                      http://127.0.0.1:8001/mcp
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

from fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = ROOT / "data" / "yale_som.db"

mcp = FastMCP("yale-som-courses")


@mcp.tool
def yo() -> str:
    """Placeholder tool — replace with real catalogue tools in class."""
    return "yo"


@mcp.tool
def search_courses_by_professor(name: str) -> list[dict]:
    """Find courses taught by a professor.

    Matches any part of the name, case-insensitive, in either order
    ("Rudi", "Nils Rudi", or "Rudi, Nils" all work).
    """
    words = [w for w in name.replace(",", " ").split() if w]
    if not words:
        return []
    where = " AND ".join("faculty_1 LIKE ?" for _ in words)
    params = [f"%{w}%" for w in words]
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT course_number, course_title, faculty_1, faculty_1_email,
                   course_session, daytimes, room, section, units
            FROM courses
            WHERE {where}
            ORDER BY course_number, section
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


SUMMARY_COLUMNS = """
    course_number, section, course_title, course_category, faculty_1,
    faculty_1_email, course_session, daytimes AS day_time, room, units,
    course_description
"""
# Text fields the keyword search looks through, with a ranking weight each.
SEARCH_FIELDS = {
    "course_number": 3,
    "course_title": 3,
    "faculty_1": 3,
    "course_description": 2,
    "faculty_bio": 1,
    "course_category": 1,
    "course_type": 1,
    "course_session": 1,
    "room": 1,
}
SHORT_DESCRIPTION_CHARS = 280
MAX_LIMIT = 50


def _query(sql: str, params: list) -> list[dict]:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Course database not found at {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _shorten(row: dict) -> dict:
    """Swap the full description for a short one so result lists stay small."""
    text = " ".join((row.pop("course_description") or "").split())
    if len(text) > SHORT_DESCRIPTION_CHARS:
        text = text[: SHORT_DESCRIPTION_CHARS - 1].rstrip() + "…"
    row["short_description"] = text
    return row


def _clamp(limit: int, default: int) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _no_spaces(text: str) -> str:
    return "".join(text.split()).upper()


def _keyword_pattern(word: str) -> re.Pattern:
    """Match a keyword at the start of a word, ignoring case.

    Keywords of 3 letters or fewer must be a whole word (plural "s" allowed),
    so "AI" finds "AI" and "AIs" but not "maintain" or "said". Longer
    keywords also match longer words: "competitor" finds "competitors".
    """
    tail = r"s?\b" if len(word) <= 3 else ""
    return re.compile(r"\b" + re.escape(word) + tail, re.IGNORECASE)


@mcp.tool
def search_courses(query: str, limit: int = 10) -> dict:
    """Keyword search over the Yale SOM course catalogue.

    Give one or more keywords (e.g. "AI", "competitor", "statistics").
    Checks the course number, title, professor name, course description,
    professor bio, category, type, session, and room. With several keywords,
    a course must match all of them. Returns one result per course, best
    matches first, with its sections, a short description, and which fields
    matched. Use get_course for the full description of one course.
    """
    limit = _clamp(limit, 10)
    words = [w for w in query.replace(",", " ").split() if w]
    if not words:
        return {"query": query, "count": 0, "results": [], "message": "Empty query."}
    patterns = [_keyword_pattern(w) for w in words]

    rows = _query(
        f"SELECT {SUMMARY_COLUMNS}, faculty_bio, course_type FROM courses "
        "ORDER BY course_number, section",
        [],
    )
    courses: dict[str, dict] = {}
    for row in rows:
        texts = {f: row.get(f) or "" for f in SEARCH_FIELDS}
        compact_number = _no_spaces(texts["course_number"])
        matched: set[str] = set()
        for word, pattern in zip(words, patterns):
            hits = {f for f, text in texts.items() if pattern.search(text)}
            if _no_spaces(word) in compact_number and len(_no_spaces(word)) > 3:
                hits.add("course_number")  # "MGT409" with no space
            if not hits:
                break
            matched |= hits
        else:
            course = courses.setdefault(row["course_number"], {
                "course_number": row["course_number"],
                "course_title": row["course_title"],
                "course_category": row["course_category"],
                "units": row["units"],
                "course_description": "",
                "matched_fields": set(),
                "sections": [],
            })
            if not course["course_description"]:
                course["course_description"] = row["course_description"]
            course["matched_fields"] |= matched
            course["sections"].append({
                "section": row["section"],
                "faculty_1": row["faculty_1"],
                "faculty_1_email": row["faculty_1_email"],
                "course_session": row["course_session"],
                "day_time": row["day_time"],
                "room": row["room"],
            })

    for course in courses.values():
        fields = course["matched_fields"]
        course["score"] = sum(SEARCH_FIELDS[f] for f in fields)
        course["matched_fields"] = sorted(fields, key=lambda f: -SEARCH_FIELDS[f])
    ranked = sorted(courses.values(), key=lambda c: (-c.pop("score"), c["course_number"]))
    results = [_shorten(c) for c in ranked[:limit]]

    result = {
        "query": query,
        "count": len(results),
        "total_matches": len(ranked),
        "results": results,
    }
    if not results:
        result["message"] = f"No courses in yale_som.db match {query!r}."
    elif len(ranked) > len(results):
        result["message"] = (
            f"Showing {len(results)} of {len(ranked)} matching courses; "
            "raise limit or add a keyword to narrow it."
        )
    return result


@mcp.tool
def get_course(course_number: str, section: str = "") -> dict:
    """Look up one course by number (e.g. "MGT 409" or "MGT409").

    Returns every section with full description, faculty, day/time, room,
    session, and units. Pass section (e.g. "01") to get just that section.
    """
    sql = (
        f"SELECT {SUMMARY_COLUMNS}, faculty_bio FROM courses "
        "WHERE REPLACE(UPPER(course_number), ' ', '') = ?"
    )
    params: list = [_no_spaces(course_number)]
    if section.strip():
        sql += " AND UPPER(section) = ?"
        params.append(section.strip().upper())
    rows = _query(sql + " ORDER BY section", params)

    if not rows:
        what = course_number + (f" section {section}" if section.strip() else "")
        return {
            "course_number": course_number,
            "found": False,
            "sections": [],
            "message": f"No course {what!r} in yale_som.db.",
        }
    return {
        "course_number": rows[0]["course_number"],
        "course_title": rows[0]["course_title"],
        "found": True,
        "section_count": len(rows),
        "sections": rows,
    }


@mcp.tool
def list_courses_by_faculty(name: str, limit: int = 15) -> dict:
    """List courses whose instructor (faculty_1) matches a name.

    Case-insensitive; each word must appear, in any order ("Zaman",
    "Tauhid Zaman", and "Zaman, Tauhid" all work).
    """
    limit = _clamp(limit, 15)
    words = [w for w in name.replace(",", " ").split() if w]
    if not words:
        return {"name": name, "count": 0, "results": [], "message": "Empty name."}

    where = " AND ".join("faculty_1 LIKE ?" for _ in words)
    params = [f"%{w}%" for w in words]
    rows = _query(
        f"SELECT {SUMMARY_COLUMNS} FROM courses WHERE {where} "
        "ORDER BY course_number, section LIMIT ?",
        params + [limit],
    )
    result = {"name": name, "count": len(rows), "results": [_shorten(r) for r in rows]}
    if not rows:
        result["message"] = f"No courses in yale_som.db taught by {name!r}."
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Yale SOM courses MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve Streamable HTTP on port 8001 (keeps FastAPI free on 8000)",
    )
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="http", host="127.0.0.1", port=8001)
    else:
        mcp.run()
