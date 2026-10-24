"""Yale SOM course catalogue MCP — Lecture 9 starter.

In class you'll add real tools that read ../data/yale_som.db.
Right now there is a placeholder tool plus any tools you add.

Run from this folder (stdio):  python mcp_server.py
Run (HTTP):                    python mcp_server.py --http
HTTP URL:                      http://127.0.0.1:8001/mcp
"""

from __future__ import annotations

import argparse
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
SEARCH_COLUMNS = (
    "course_number",
    "course_title",
    "faculty_1",
    "course_category",
    "course_description",
)
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


@mcp.tool
def search_courses(query: str, limit: int = 10) -> dict:
    """Keyword search over the Yale SOM course catalogue.

    Every word in the query must appear in at least one of: course number,
    title, faculty, category, or description (case-insensitive). Returns one
    row per section with number, title, faculty, day/time, room, and a short
    description. Use get_course for the full description of one course.
    """
    limit = _clamp(limit, 10)
    words = [w for w in query.replace(",", " ").split() if w]
    if not words:
        return {"query": query, "count": 0, "results": [], "message": "Empty query."}

    clauses, params = [], []
    for word in words:
        ors = [f"{col} LIKE ?" for col in SEARCH_COLUMNS]
        ors.append("REPLACE(course_number, ' ', '') LIKE ?")
        clauses.append("(" + " OR ".join(ors) + ")")
        params += [f"%{word}%"] * len(SEARCH_COLUMNS) + [f"%{_no_spaces(word)}%"]

    where = " AND ".join(clauses)
    total = _query(f"SELECT COUNT(*) AS n FROM courses WHERE {where}", params)[0]["n"]
    rows = _query(
        f"SELECT {SUMMARY_COLUMNS} FROM courses WHERE {where} "
        "ORDER BY course_number, section LIMIT ?",
        params + [limit],
    )
    result = {
        "query": query,
        "count": len(rows),
        "total_matches": total,
        "results": [_shorten(r) for r in rows],
    }
    if not rows:
        result["message"] = f"No courses in yale_som.db match {query!r}."
    elif total > len(rows):
        result["message"] = f"Showing {len(rows)} of {total} matches; refine the query."
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
