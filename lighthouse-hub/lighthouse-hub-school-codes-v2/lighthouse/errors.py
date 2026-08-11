class ApiError(Exception):
    def __init__(self, status, message, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra or {}


def bad_request(msg):
    return ApiError(400, msg)


def unauthorized(msg="Not authenticated"):
    return ApiError(401, msg)


def forbidden(msg="Not permitted"):
    return ApiError(403, msg)


def not_found(msg="Not found"):
    return ApiError(404, msg)


def conflict(msg, extra=None):
    return ApiError(409, msg, extra)
