"""The ZKTeco ADMS ("push") protocol, as PayRole spoke it (zkk/zk_adms.py). Pure: no database.

The device calls the server, never the other way round:

    GET  /iclock/cdata?SN=…              handshake: the server answers with options
    POST /iclock/cdata?SN=…&table=ATTLOG punches, one per line: PIN \\t time \\t status \\t verify …
    POST /iclock/cdata?SN=…&table=OPERLOG|USERINFO   users: "USER PIN=…\\tName=…"
    GET  /iclock/getrequest?SN=…         "OK", or a command line "C:<id>:<command>"
    POST /iclock/devicecmd?SN=…          the results: "ID=<id>&Return=<n>&CMD=…" per line

Replies are plain text, lines joined by "\\n". The options are PayRole's, but the time zone is
the client's own (PayRole sent Cairo's to every device).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs

POLL_DELAY = 10  # seconds between the device's calls
ERROR_DELAY = 30
ONLINE_SECONDS = 120  # seen this recently: shown as online
PICKUP_SECONDS = 90  # a command not picked up by then has expired
REPLY_SECONDS = 180  # a command picked up but not answered by then has expired

PUNCH_STATUS = {0: "in", 1: "out", 2: "break_out", 3: "break_in", 4: "overtime_in",
                5: "overtime_out"}

INFO = "INFO"
PULL_USERS = "DATA QUERY USERINFO"
PULL_PUNCHES = "DATA QUERY ATTLOG"


def pull_punches(start, end) -> str:
    """Ask the device for its punches from one day to another (both whole days)."""
    return (f"{PULL_PUNCHES} StartTime={start:%Y-%m-%d} 00:00:00"
            f"\tEndTime={end:%Y-%m-%d} 23:59:59")


def options(serial: str, *, resend_all: bool, utc_offset_hours: int) -> str:
    """The handshake answer. `resend_all` asks for every punch the device holds again."""
    return "\n".join([
        f"GET OPTION FROM: {serial}",
        f"ATTLOGStamp={0 if resend_all else 'None'}",
        "OPERLOGStamp=9999",
        "ATTPHOTOStamp=None",
        f"ErrorDelay={ERROR_DELAY}",
        f"Delay={POLL_DELAY}",
        "TransTimes=00:00;14:05",
        "TransInterval=1",
        "TransFlag=TransData AttLog\tOpLog\tEnrollUser\tChgUser",
        f"TimeZone={utc_offset_hours}",
        "Realtime=1",
        "Encrypt=None",
    ]) + "\n"


def command_lines(commands) -> str:
    """`[(id, text)]` → the getrequest answer."""
    if not commands:
        return "OK\n"
    return "".join(f"C:{pk}:{text}\n" for pk, text in commands)


@dataclass(frozen=True)
class AttRecord:
    pin: str
    at: datetime  # the device's local time, naive
    status: int
    verify: int
    workcode: str


def _int(text: str, default: int | None = 0) -> int | None:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return default


def parse_attlog(body: str) -> list[AttRecord]:
    """Punch lines (PIN, "YYYY-MM-DD HH:MM:SS", status, verify, workcode, …); a line that
    can't be read is skipped."""
    records = []
    for line in body.splitlines():
        fields = line.split("\t")
        if len(fields) < 2 or not fields[0].strip():
            continue
        try:
            at = datetime.strptime(fields[1].strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        status, verify, workcode = (fields + ["", "", ""])[2:5]
        records.append(AttRecord(pin=fields[0].strip()[:24], at=at, status=_int(status),
                                 verify=_int(verify), workcode=workcode.strip()[:24]))
    return records


def parse_users(body: str) -> dict[str, str]:
    """{PIN: name} from user records ("USER PIN=…\\tName=…"; PayRole ignored lines without the
    "USER " prefix, which some firmware leaves out)."""
    users = {}
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("USER "):
            line = line[5:]
        pairs = dict(part.split("=", 1) for part in line.split("\t") if "=" in part)
        pin = pairs.get("PIN", "").strip()[:24]
        if pin:
            users[pin] = pairs.get("Name", "").strip()[:60]
    return users


@dataclass(frozen=True)
class CommandReply:
    id: int
    ok: bool
    result: int | None


def parse_replies(body: str) -> list[CommandReply]:
    """`ID=12&Return=0&CMD=DATA` per line. A reply without a Return is a failure (PayRole
    counted it as done)."""
    replies = []
    for line in body.splitlines():
        values = {key: items[0] for key, items in parse_qs(line.strip()).items()}
        pk = _int(values.get("ID", ""), None)
        if pk is None:
            continue
        result = _int(values.get("Return", ""), None)
        replies.append(CommandReply(pk, result is not None and result >= 0, result))
    return replies


def device_info(text: str) -> dict:
    """INFO: "firmware,users,fingerprints,punches,…"."""
    parts = text.split(",")
    keys = ("firmware", "users", "fingerprints", "punches")
    return {key: parts[i].strip() for i, key in enumerate(keys) if i < len(parts)}
