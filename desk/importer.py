import csv
import re
from collections import Counter
from datetime import datetime
from datetime import timezone as utc
from zoneinfo import ZoneInfo

from django.db import transaction

from .forms import normalize_task
from .models import ROBOTS, Episode
from .services import DomainError, require_role
from .locking import serialize_mutation

COLUMNS = [
    "episode_id",
    "robot_id",
    "task_name",
    "recorded_at",
    "duration_seconds",
    "operator_name",
    "quality",
]


def parse_row(row):
    if len(row) != len(COLUMNS):
        raise ValueError("wrong_column_count")
    eid, robot, task, recorded, duration, operator, quality = [v.strip() for v in row]
    eid = eid.upper()
    robot = robot.lower()
    task = normalize_task(task)
    quality = quality.lower()
    operator = " ".join(operator.split())
    if not re.fullmatch(r"EP-\d{1,30}", eid):
        raise ValueError("invalid_episode_id")
    if robot not in ROBOTS:
        raise ValueError("unknown_or_missing_robot")
    if not task or len(task) > 160:
        raise ValueError("invalid_task")
    if not operator or len(operator) > 120:
        raise ValueError("missing_or_long_operator")
    if quality not in ["good", "usable", "bad"]:
        raise ValueError("invalid_quality")
    duration = duration.lstrip("0") or "0"
    if not re.fullmatch(r"[0-9]{1,4}", duration) or not 1 <= int(duration) <= 3600:
        raise ValueError("duration_outside_1_to_3600")
    try:
        at = datetime.fromisoformat(recorded)
    except ValueError:
        try:
            at = datetime.strptime(recorded, "%d/%m/%Y %H:%M")
        except ValueError:
            raise ValueError("invalid_recorded_at")
    if at.tzinfo is None:
        at = at.replace(tzinfo=ZoneInfo("Africa/Kigali"))
    try:
        at = at.astimezone(utc.utc)
    except (OverflowError, ValueError):
        raise ValueError("invalid_recorded_at")
    return Episode(
        episode_id=eid,
        robot_id=robot,
        task_name=task,
        recorded_at=at,
        duration_seconds=int(duration),
        operator_name=operator,
        quality=quality,
    )


@transaction.atomic
def import_episodes(actor, stream):
    serialize_mutation(102)
    require_role(actor, "operator", "admin")
    reader = csv.reader(stream, strict=True)
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        raise DomainError("The CSV must contain the seven-column header.")
    except UnicodeError:
        raise DomainError("Invalid UTF-8; this file was rolled back.")
    if [h.strip().lower().lstrip("\ufeff") for h in header] != COLUMNS:
        raise DomainError("CSV columns must match the supplied episodes.csv header.")
    report = {
        "total_rows": 0,
        "imported": 0,
        "skipped": 0,
        "reasons": {},
        "rows": [],
        "unlisted_skips": 0,
    }
    reasons = Counter()
    batch = {}

    def skip(line, eid, reason):
        report["skipped"] += 1
        reasons[reason] += 1
        if len(report["rows"]) < 200:
            report["rows"].append({"line": line, "episode_id": eid, "reason": reason})
        else:
            report["unlisted_skips"] += 1

    def flush():
        if not batch:
            return
        existing = set(
            Episode.objects.filter(pk__in=batch).values_list("pk", flat=True)
        )
        new = []
        for eid, (line, ep) in batch.items():
            if eid in existing:
                skip(line, eid, "duplicate_episode_id")
            else:
                new.append(ep)
        Episode.objects.bulk_create(new, batch_size=100)
        report["imported"] += len(new)
        batch.clear()

    try:
        for row in reader:
            report["total_rows"] += 1
            line = reader.line_num
            if not row or not any(v.strip() for v in row):
                skip(line, "", "blank_row")
                continue
            try:
                ep = parse_row(row)
            except ValueError as exc:
                skip(line, row[0].strip()[:40], str(exc))
                continue
            if ep.pk in batch:
                skip(line, ep.pk, "duplicate_episode_id")
            else:
                batch[ep.pk] = (line, ep)
            if len(batch) >= 500:
                flush()
        flush()
    except (csv.Error, UnicodeError):
        raise DomainError(
            "Malformed CSV syntax or invalid UTF-8; this file was rolled back."
        )
    report["reasons"] = dict(sorted(reasons.items()))
    from .notifications import notify

    notify(
        "Episode import completed",
        f"Imported {report['imported']} episodes; skipped {report['skipped']} rows.",
    )
    return report
