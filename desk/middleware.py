import json
import logging
import time

from django.db import DatabaseError

logger = logging.getLogger("desk.requests")


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        user = getattr(request, "user", None)
        try:
            user_id = user.pk if user and user.is_authenticated else None
        except DatabaseError:
            user_id = None
        logger.info(
            json.dumps(
                {
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "user_id": user_id,
                }
            )
        )
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response
