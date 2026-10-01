from django.db import connection


def serialize_mutation(key):
    """Serialize cross-row invariants on Postgres, as IMMEDIATE does on SQLite.

    Call only inside transaction.atomic(). Locks expire with the transaction;
    no session lock is retained in a pooled connection.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
