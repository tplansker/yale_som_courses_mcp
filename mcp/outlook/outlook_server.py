"""Outlook MCP server — read-only access to a Yale Microsoft 365 mailbox.

Uses Microsoft Graph with delegated, read-only scopes (Mail.Read,
Calendars.Read, User.Read). Nothing here can send, move, or delete mail.

Settings come from the project .env (see .env.example):
    OUTLOOK_CLIENT_ID   Application (client) ID of your Entra app registration
    OUTLOOK_TENANT_ID   Tenant ID or domain (default: "organizations")
    OUTLOOK_TIMEZONE    Windows time zone name for calendar times
                        (default: "Eastern Standard Time")

Sign in once from a terminal (device-code flow, token cached locally):
    python outlook_server.py --login
Run (stdio, what Claude Code uses):
    python outlook_server.py
Sign out (delete the cached token):
    python outlook_server.py --logout
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import msal
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for env_file in (ROOT / ".env", ROOT.parent / ".env"):
    if env_file.exists():
        load_dotenv(env_file, override=False)

CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID", "").strip()
TENANT_ID = os.getenv("OUTLOOK_TENANT_ID", "organizations").strip() or "organizations"
TIMEZONE = os.getenv("OUTLOOK_TIMEZONE", "Eastern Standard Time").strip()
TOKEN_CACHE_PATH = HERE / ".token_cache.json"
SCOPES = ["User.Read", "Mail.Read", "Calendars.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"
MAX_LIMIT = 50
MAX_BODY_CHARS = 8000

mcp = FastMCP("outlook")


# --- Auth --------------------------------------------------------------------


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize())
        TOKEN_CACHE_PATH.chmod(0o600)


def _app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    if not CLIENT_ID:
        raise ToolError(
            "OUTLOOK_CLIENT_ID is not set. Add it to the project .env "
            "(see .env.example and the README)."
        )
    return msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )


def _access_token() -> str:
    cache = _load_cache()
    app = _app(cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    _save_cache(cache)
    if not result or "access_token" not in result:
        raise ToolError(
            "Not signed in to Outlook. In a terminal, run: "
            "mcp/outlook/.venv/bin/python mcp/outlook/outlook_server.py --login"
        )
    return result["access_token"]


def login() -> None:
    cache = _load_cache()
    app = _app(cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        sys.exit(f"Could not start sign-in: {flow.get('error_description', flow)}")
    print(flow["message"], flush=True)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        sys.exit(f"Sign-in failed: {result.get('error_description', result.get('error'))}")
    _save_cache(cache)
    name = result.get("id_token_claims", {}).get("preferred_username", "your account")
    print(f"Signed in as {name}. Token cached in {TOKEN_CACHE_PATH.name}.")


def logout() -> None:
    TOKEN_CACHE_PATH.unlink(missing_ok=True)
    print("Signed out; cached token removed.")


# --- Graph helpers -----------------------------------------------------------


def _get(path: str, params: dict | None = None, prefer: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_access_token()}"}
    if prefer:
        headers["Prefer"] = prefer
    resp = requests.get(f"{GRAPH}{path}", params=params, headers=headers, timeout=30)
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {})
            detail = f"{err.get('code', '')}: {err.get('message', '')}"
        except ValueError:
            detail = resp.reason
        raise ToolError(f"Microsoft Graph returned {resp.status_code} ({detail})")
    return resp.json()


def _clamp(limit: int, default: int) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _address(recipient: dict | None) -> str:
    email = (recipient or {}).get("emailAddress", {})
    name, addr = email.get("name", ""), email.get("address", "")
    return f"{name} <{addr}>" if name and addr and name != addr else addr or name


def _summary(msg: dict) -> dict:
    return {
        "id": msg.get("id"),
        "subject": msg.get("subject") or "(no subject)",
        "from": _address(msg.get("from")),
        "received": msg.get("receivedDateTime"),
        "is_read": msg.get("isRead"),
        "has_attachments": msg.get("hasAttachments"),
        "preview": " ".join((msg.get("bodyPreview") or "").split()),
    }


SUMMARY_FIELDS = "id,subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview"


# --- Tools -------------------------------------------------------------------


@mcp.tool
def whoami() -> dict:
    """Show which Microsoft 365 account the Outlook server is signed in as."""
    me = _get("/me", {"$select": "displayName,mail,userPrincipalName"})
    return {"name": me.get("displayName"), "email": me.get("mail") or me.get("userPrincipalName")}


@mcp.tool
def list_recent_emails(limit: int = 10, unread_only: bool = False) -> dict:
    """List the most recent emails in the Inbox, newest first.

    Returns subject, sender, received time, read status, and a short preview.
    Use get_email with an id for the full message.
    """
    limit = _clamp(limit, 10)
    params = {"$top": limit, "$select": SUMMARY_FIELDS, "$orderby": "receivedDateTime desc"}
    if unread_only:
        params["$filter"] = "isRead eq false"
    data = _get("/me/mailFolders/inbox/messages", params)
    messages = [_summary(m) for m in data.get("value", [])]
    return {"count": len(messages), "messages": messages}


@mcp.tool
def search_emails(query: str, limit: int = 10) -> dict:
    """Search all mail folders by keyword (subject, body, sender, etc.).

    Accepts plain keywords ("capstone deadline") or Outlook search syntax
    such as from:someone@yale.edu or subject:exam. Results are ranked by
    relevance, not date.
    """
    query = query.strip()
    if not query:
        raise ToolError("Give at least one search keyword.")
    limit = _clamp(limit, 10)
    escaped = query.replace('"', '\\"')
    data = _get("/me/messages", {"$search": f'"{escaped}"', "$top": limit, "$select": SUMMARY_FIELDS})
    messages = [_summary(m) for m in data.get("value", [])]
    result = {"query": query, "count": len(messages), "messages": messages}
    if not messages:
        result["message"] = f"No emails matched {query!r}."
    return result


@mcp.tool
def get_email(message_id: str) -> dict:
    """Read one email in full (plain text body), by the id from a list/search result."""
    msg = _get(
        f"/me/messages/{requests.utils.quote(message_id, safe='')}",
        {"$select": "subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,webLink,body"},
        prefer='outlook.body-content-type="text"',
    )
    body = (msg.get("body") or {}).get("content", "").strip()
    truncated = len(body) > MAX_BODY_CHARS
    return {
        "subject": msg.get("subject") or "(no subject)",
        "from": _address(msg.get("from")),
        "to": [_address(r) for r in msg.get("toRecipients", [])],
        "cc": [_address(r) for r in msg.get("ccRecipients", [])],
        "received": msg.get("receivedDateTime"),
        "has_attachments": msg.get("hasAttachments"),
        "web_link": msg.get("webLink"),
        "body": body[:MAX_BODY_CHARS] + ("\n…[truncated]" if truncated else ""),
    }


@mcp.tool
def list_calendar_events(days: int = 7, limit: int = 25) -> dict:
    """List calendar events from now through the next `days` days, soonest first.

    Times are in the OUTLOOK_TIMEZONE setting (default Eastern Standard Time).
    """
    days = max(1, min(int(days), 90))
    limit = _clamp(limit, 25)
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    data = _get(
        "/me/calendarView",
        {
            "startDateTime": start.isoformat(timespec="seconds"),
            "endDateTime": end.isoformat(timespec="seconds"),
            "$orderby": "start/dateTime",
            "$top": limit,
            "$select": "subject,start,end,location,organizer,isAllDay,isOnlineMeeting,onlineMeeting",
        },
        prefer=f'outlook.timezone="{TIMEZONE}"',
    )
    events = [
        {
            "subject": e.get("subject") or "(no title)",
            "start": e.get("start", {}).get("dateTime"),
            "end": e.get("end", {}).get("dateTime"),
            "all_day": e.get("isAllDay"),
            "location": (e.get("location") or {}).get("displayName", ""),
            "organizer": _address(e.get("organizer")),
            "join_url": (e.get("onlineMeeting") or {}).get("joinUrl") if e.get("isOnlineMeeting") else None,
        }
        for e in data.get("value", [])
    ]
    return {"timezone": TIMEZONE, "days": days, "count": len(events), "events": events}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Outlook (Microsoft 365) MCP server, read-only")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--login", action="store_true", help="Sign in with a device code")
    group.add_argument("--logout", action="store_true", help="Delete the cached token")
    args = parser.parse_args()
    if args.login:
        login()
    elif args.logout:
        logout()
    else:
        mcp.run()
