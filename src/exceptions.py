"""
Custom API exceptions for standardized error handling
"""


class APIException(Exception):
    """Base API exception"""
    def __init__(self, code: str, message: str, status_code: int = 400, field: str = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field
        super().__init__(message)


class NotFoundException(APIException):
    """Resource not found (404)"""
    def __init__(self, resource: str, identifier: str = None):
        msg = f"{resource} not found" if not identifier else f"{resource} '{identifier}' not found"
        super().__init__("NOT_FOUND", msg, 404)


class ValidationException(APIException):
    """Validation error (400)"""
    def __init__(self, message: str, field: str = None):
        super().__init__("VALIDATION_ERROR", message, 400, field)


class ConflictException(APIException):
    """Resource conflict (409)"""
    def __init__(self, message: str):
        super().__init__("CONFLICT", message, 409)


class UnauthorizedException(APIException):
    """Authentication required (401)"""
    def __init__(self, message: str = "Authentication required"):
        super().__init__("UNAUTHORIZED", message, 401)


class ForbiddenException(APIException):
    """Access forbidden (403)"""
    def __init__(self, message: str = "Access forbidden"):
        super().__init__("FORBIDDEN", message, 403)


class ServiceUnavailableException(APIException):
    """Service unavailable (503)"""
    def __init__(self, message: str = "Service unavailable"):
        super().__init__("SERVICE_UNAVAILABLE", message, 503)
