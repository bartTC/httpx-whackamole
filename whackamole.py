"""
Policy-based error handling for httpx HTTP operations.

This module provides a clean way to handle HTTP errors in batch processing scenarios
where some failures are acceptable and should be retried later, while others require
immediate attention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

import httpx

if TYPE_CHECKING:
    from http import HTTPStatus

__version__ = "1.1.0"
__all__ = ["ErrorContext", "ErrorPolicy", "HttpxWhackamole"]


@dataclass(frozen=True)
class ErrorPolicy:
    """
    Error handling policy for httpx HTTP operations.

    Defines which HTTP errors should be raised vs suppressed during HTTP operations.

    Attributes:
        raise_for_status: Either "all" (raise everything) or tuple of specific status codes to raise
        suppress_for_status: Status codes to suppress when raise_for_status="all" (inverted mode)

    Modes:
        1. Inverted mode (default): raise_for_status="all", suppress specific codes via suppress_for_status
        2. Explicit mode: raise_for_status=tuple of codes, suppress everything else

    Examples:
        >>> # Default: Raise all errors (safe by default)
        >>> policy = ErrorPolicy.default()

        >>> # Suppress only 404, raise everything else
        >>> policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

        >>> # Raise only auth/rate-limit, suppress everything else
        >>> policy = ErrorPolicy(raise_for_status=(HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS))

    """

    raise_for_status: tuple[HTTPStatus, ...] | Literal["all"] = field(default="all")
    suppress_for_status: tuple[HTTPStatus, ...] = field(default=())

    @classmethod
    def default(cls) -> ErrorPolicy:
        """
        Return the default error handling policy that raises all errors.

        This is the safest default behavior - all HTTP and network errors will be
        raised unless explicitly suppressed. This ensures no errors are accidentally
        swallowed, making debugging easier and preventing silent failures.

        To suppress specific errors, use:
        - ErrorPolicy.raise_all_except(...) to suppress specific status codes
        - ErrorPolicy(raise_for_status=[...]) to raise only specific codes

        Rationale: Explicit error suppression is safer than implicit. By raising all
        errors by default, developers must consciously decide which errors to handle
        gracefully, reducing the risk of masking important failures.
        """
        return cls(raise_for_status="all")

    @classmethod
    def raise_all_except(cls, *codes: HTTPStatus) -> ErrorPolicy:
        """
        Inverted mode: Raise all errors EXCEPT the specified status codes.

        Use this for verification scenarios where you want to distinguish between
        permanent failures (e.g., 404) and transient failures (network, 500, etc.).

        Args:
            *codes: HTTP status codes to suppress (return None instead of raising)

        Returns:
            ErrorPolicy configured in inverted mode

        Example:
            # For verification: only suppress 404, raise everything else
            policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

        """
        return cls(raise_for_status="all", suppress_for_status=codes)


@dataclass(frozen=True)
class ErrorContext:
    """
    Context information passed to error callbacks.

    Provides details about the error that occurred and how it was handled.

    Attributes:
        exception: The exception that was caught
        was_suppressed: True if error was suppressed, False if it will be raised
        request: The HTTP request object (available for HTTP errors)
        response: The HTTP response object (only available for HTTPStatusError)

    """

    exception: BaseException
    was_suppressed: bool
    request: httpx.Request | None = None
    response: httpx.Response | None = None

    @property
    def status_code(self) -> int | None:
        """
        Get the HTTP status code if available.

        Returns:
            The HTTP status code, or None if not an HTTP status error

        """
        return self.response.status_code if self.response else None


class HttpxWhackamole:
    """
    Context manager for policy-based httpx error handling.

    Selectively suppresses or raises HTTP errors based on the provided policy.
    Safe by default - raises all errors unless explicitly configured otherwise.

    Supports custom callbacks via subclassing or instance parameters to execute
    custom code on error/success (e.g., sending errors to Sentry).

    Attributes:
        error_occurred: Set to True if an error was suppressed, False otherwise
        policy: The ErrorPolicy defining which errors to raise/suppress
        on_error: Optional callback invoked when an error occurs
        on_success: Optional callback invoked when no error occurs

    Examples:
        >>> # Default: Raise all errors (safe by default)
        >>> with HttpxWhackamole() as handler:
        ...     response = httpx.get(url)
        ...     if handler.error_occurred:
        ...         print("Won't get here - all errors raise")

        >>> # Suppress only 404 errors
        >>> policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)
        >>> with HttpxWhackamole(policy=policy) as handler:
        ...     response = httpx.get(url)  # 404 won't raise
        ...     if handler.error_occurred:
        ...         print("Resource not found, continuing...")

        >>> # With error callback (e.g., for Sentry)
        >>> def send_to_sentry(ctx: ErrorContext):
        ...     sentry_sdk.capture_exception(ctx.exception)
        >>> with HttpxWhackamole(on_error=send_to_sentry) as handler:
        ...     response = httpx.get(url)

        >>> # Via subclassing (recommended for reusable configurations)
        >>> class SentryWhackamole(HttpxWhackamole):
        ...     def on_error(self, ctx: ErrorContext):
        ...         sentry_sdk.capture_exception(ctx.exception)
        >>> with SentryWhackamole(policy=policy) as handler:
        ...     response = httpx.get(url)

    """

    error_occurred: bool
    policy: ErrorPolicy

    def __init__(
        self,
        policy: ErrorPolicy | None = None,
        on_error: Callable[[ErrorContext], None] | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        """
        Initialize the error handler with an error policy and optional callbacks.

        Args:
            policy: Error handling policy (default: ErrorPolicy.default())
            on_error: Optional callback invoked when an error occurs. Receives ErrorContext.
                      Overrides class-level on_error if provided.
            on_success: Optional callback invoked when no error occurs.
                        Overrides class-level on_success if provided.

        Note:
            This class is designed to be subclassed for custom default policies and callbacks.
            Define on_error/on_success as methods in your subclass, or pass them to __init__.
            Instance parameters take precedence over class-level definitions.

        """
        self.error_occurred = False
        self.policy = policy or ErrorPolicy.default()

        # Instance callbacks override class-level callbacks
        # getattr will find subclass methods automatically
        self._on_error = on_error or getattr(self, "on_error", None)
        self._on_success = on_success or getattr(self, "on_success", None)

    def __enter__(self) -> HttpxWhackamole:
        """Enter the context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        """Exit the context manager, handling exceptions based on policy."""
        if exc_type is None or exc_val is None:
            # No error occurred - call success callback
            self._invoke_success_callback()
            return False

        if not issubclass(exc_type, httpx.HTTPError):
            return False  # Not an HTTP error, let it propagate

        # Determine if we should raise or suppress this error
        should_raise = self._should_raise_error(exc_val)

        # Call error callback with context
        self._invoke_error_callback(exc_val, was_suppressed=not should_raise)

        if should_raise:
            return False  # Don't suppress, let it propagate

        # Mark that error is skippable and suppress it
        self.error_occurred = True
        return True  # Suppress the exception

    def _should_raise_error(self, exc_val: BaseException) -> bool:
        """
        Determine if an error should be raised or suppressed based on the policy.

        Args:
            exc_val: The exception that was caught

        Returns:
            True if error should be raised, False if it should be suppressed

        """
        # Handle network errors (timeouts, connection errors, etc.)
        if not isinstance(exc_val, httpx.HTTPStatusError):
            # In inverted mode ("all"), network errors raise by default
            # In explicit mode, network errors are suppressed
            return self.policy.raise_for_status == "all"

        status_code = exc_val.response.status_code

        # Inverted mode: Raise all EXCEPT those in suppress_for_status
        if self.policy.raise_for_status == "all":
            return status_code not in self.policy.suppress_for_status

        # Explicit mode: Raise only those in raise_for_status
        return status_code in self.policy.raise_for_status

    def _invoke_error_callback(
        self, exc_val: BaseException, was_suppressed: bool
    ) -> None:
        """
        Invoke the error callback if one is configured.

        Args:
            exc_val: The exception that occurred
            was_suppressed: Whether the error was suppressed by policy

        """
        if self._on_error is None:
            return

        # Extract request and response from the exception if available
        request = None
        response = None

        if isinstance(exc_val, httpx.HTTPStatusError):
            request = exc_val.request
            response = exc_val.response
        elif isinstance(exc_val, httpx.RequestError):
            request = exc_val.request

        # Create error context and invoke callback
        context = ErrorContext(
            exception=exc_val,
            was_suppressed=was_suppressed,
            request=request,
            response=response,
        )

        # Invoke callback (Python handles bound methods automatically)
        self._on_error(context)

    def _invoke_success_callback(self) -> None:
        """Invoke the success callback if one is configured."""
        if self._on_success is None:
            return

        # Invoke callback (Python handles bound methods automatically)
        self._on_success()
