"""API errors: every 4xx/5xx response is built from one of these."""


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def malformed_request(message):
    return ApiError(400, "malformed_request", message)


def missing_idempotency_key():
    return ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")


def unauthenticated(message="missing, malformed or unknown bearer token"):
    return ApiError(401, "unauthenticated", message)


def not_found(message="no such resource"):
    return ApiError(404, "not_found", message)


def validation_failed(message):
    return ApiError(422, "validation_failed", message)


def conflict(code, message):
    return ApiError(409, code, message)


def unprocessable(code, message):
    return ApiError(422, code, message)
