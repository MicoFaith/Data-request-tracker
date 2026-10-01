from datetime import datetime, time, timedelta
from datetime import timezone as utc
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Count
from django.db.models.functions import TruncDate

from .models import DatasetRequest, Episode

KIGALI = ZoneInfo("Africa/Kigali")


def analytics(start, end):
    lower = datetime.combine(start, time.min, KIGALI).astimezone(utc.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, KIGALI).astimezone(
        utc.utc
    )
    episodes = Episode.objects.filter(recorded_at__gte=lower, recorded_at__lt=upper)
    cohort = DatasetRequest.objects.filter(created_at__gte=lower, created_at__lt=upper)
    per_day = list(
        episodes.annotate(day=TruncDate("recorded_at", tzinfo=KIGALI))
        .values("day", "robot_id")
        .annotate(count=Count("pk"))
        .order_by("day", "robot_id")
    )
    statuses = {s: 0 for s in DatasetRequest.Status.values}
    statuses.update(
        {
            x["status"]: x["count"]
            for x in cohort.values("status").annotate(count=Count("pk")).order_by()
        }
    )
    top = list(
        episodes.filter(quality="good")
        .values("task_name")
        .annotate(count=Count("pk"))
        .order_by("-count", "task_name")[:5]
    )
    # Window ranking + middle one/two rows computes median inside SQLite.
    # first_delivered_at avoids counting repeated delivery after rejection twice.
    sql = """WITH durations AS (
        SELECT (julianday(first_delivered_at)-julianday(created_at))*86400.0 AS seconds
        FROM desk_datasetrequest
        WHERE created_at >= %s AND created_at < %s AND first_delivered_at IS NOT NULL
    ), ranked AS (
        SELECT seconds, ROW_NUMBER() OVER (ORDER BY seconds) AS rn, COUNT(*) OVER () AS n FROM durations
    ) SELECT ROUND(AVG(seconds),3) FROM ranked WHERE rn IN ((n+1)/2,(n+2)/2)"""
    if connection.vendor == "postgresql":
        sql = """SELECT percentile_cont(0.5) WITHIN GROUP
            (ORDER BY EXTRACT(EPOCH FROM (first_delivered_at-created_at)))
            FROM desk_datasetrequest
            WHERE created_at >= %s AND created_at < %s AND first_delivered_at IS NOT NULL"""
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [
                connection.ops.adapt_datetimefield_value(lower),
                connection.ops.adapt_datetimefield_value(upper),
            ],
        )
        median = cursor.fetchone()[0]
        if median is not None:
            median = round(float(median), 3)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": "Africa/Kigali",
        "episodes_per_day_per_robot": per_day,
        "request_fulfilment": {
            "counts_by_status": statuses,
            "median_seconds_submitted_to_first_delivered": median,
        },
        "top_5_good_tasks": top,
    }
