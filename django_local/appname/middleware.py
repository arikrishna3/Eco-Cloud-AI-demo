from time import perf_counter

from .models import ApiRequestLog


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = perf_counter()
        response = self.get_response(request)
        latency_ms = int((perf_counter() - start) * 1000)

        if not request.path.startswith("/static/"):
            ApiRequestLog.objects.create(
                path=request.path,
                method=request.method,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )

        return response