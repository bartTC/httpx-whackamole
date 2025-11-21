"""Tests for ErrorPolicy and HttpxErrorHandler."""

from http import HTTPStatus
from unittest.mock import Mock

import httpx
import pytest
from pytest_httpx import HTTPXMock

from whackamole import ErrorContext, ErrorPolicy, HttpxWhackamole


def test_error_policy_default() -> None:
    """Test that ErrorPolicy.default() creates the expected default policy."""
    policy = ErrorPolicy.default()

    # Should raise all errors by default (safe mode)
    assert policy.raise_for_status == "all"
    assert policy.suppress_for_status == ()


def test_httpx_whackamole_no_error_default_policy() -> None:
    """Test that handler works when no error occurs (default policy)."""
    with HttpxWhackamole() as handler:
        # No error
        pass

    assert not handler.error_occurred


@pytest.mark.parametrize(
    ("status_code", "error_message"),
    [
        (HTTPStatus.UNAUTHORIZED, "Unauthorized"),
        (HTTPStatus.TOO_MANY_REQUESTS, "Rate limited"),
        (HTTPStatus.FORBIDDEN, "Forbidden"),
        (HTTPStatus.NOT_FOUND, "Not found"),
        (HTTPStatus.INTERNAL_SERVER_ERROR, "Server error"),
    ],
)
def test_httpx_whackamole_all_errors_propagate_default_policy(
    status_code: HTTPStatus, error_message: str
) -> None:
    """Test that all errors propagate with default policy (safe by default)."""
    response = httpx.Response(
        status_code, request=httpx.Request("GET", "http://test.com")
    )

    with (
        pytest.raises(httpx.HTTPStatusError),
        HttpxWhackamole() as handler,
    ):
        raise httpx.HTTPStatusError(
            error_message, request=response.request, response=response
        )

    # Handler should not have marked it as skippable since it propagated
    assert not handler.error_occurred


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ReadTimeout("Timeout"),
        httpx.ConnectTimeout("Connect timeout"),
        httpx.WriteTimeout("Write timeout"),
    ],
)
def test_httpx_whackamole_network_errors_propagate_default_policy(
    exception: httpx.TransportError,
) -> None:
    """Test that network errors propagate with default policy (safe by default)."""
    with (
        pytest.raises(type(exception)),
        HttpxWhackamole() as handler,
    ):
        raise exception

    # Handler should not have marked it as skippable since it propagated
    assert not handler.error_occurred


def test_httpx_whackamole_non_http_error() -> None:
    """Test that non-HTTP errors propagate (not suppressed)."""
    with pytest.raises(ValueError), HttpxWhackamole() as handler:  # noqa: PT011
        msg = "Not an HTTP error"
        raise ValueError(msg)

    # Handler should not have marked it as skippable since it propagated
    assert not handler.error_occurred


# ═══════════════════════════════════════════════════════════════════════════
# CUSTOM EXPLICIT POLICY TESTS
# ═══════════════════════════════════════════════════════════════════════════


def test_custom_policy_explicit_raise_list() -> None:
    """Test custom policy with explicit list of status codes to raise."""
    policy = ErrorPolicy(raise_for_status=(HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN))

    assert HTTPStatus.NOT_FOUND in policy.raise_for_status
    assert HTTPStatus.FORBIDDEN in policy.raise_for_status


@pytest.mark.parametrize(
    "status_code",
    [HTTPStatus.NOT_FOUND, HTTPStatus.INTERNAL_SERVER_ERROR],
)
def test_custom_policy_raises_specified_codes(status_code: HTTPStatus) -> None:
    """Test that custom policy raises only specified status codes."""
    policy = ErrorPolicy(
        raise_for_status=(HTTPStatus.NOT_FOUND, HTTPStatus.INTERNAL_SERVER_ERROR)
    )

    response = httpx.Response(
        status_code, request=httpx.Request("GET", "http://test.com")
    )
    with (
        pytest.raises(httpx.HTTPStatusError),
        HttpxWhackamole(policy=policy) as handler,
    ):
        msg = "Error"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)
    assert not handler.error_occurred


def test_custom_policy_suppresses_unspecified_codes() -> None:
    """Test that custom policy suppresses codes not in raise list."""
    policy = ErrorPolicy(raise_for_status=(HTTPStatus.NOT_FOUND,))

    # Should suppress 403 (not in raise list)
    response = httpx.Response(
        HTTPStatus.FORBIDDEN, request=httpx.Request("GET", "http://test.com")
    )
    with HttpxWhackamole(policy=policy) as handler:
        msg = "Forbidden"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    assert handler.error_occurred


def test_error_policy_raise_all_except() -> None:
    """Test ErrorPolicy.raise_all_except() classmethod."""
    policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN)

    assert policy.raise_for_status == "all"
    assert HTTPStatus.NOT_FOUND in policy.suppress_for_status
    assert HTTPStatus.FORBIDDEN in policy.suppress_for_status


def test_inverted_mode_suppresses_specified_codes() -> None:
    """Test that inverted mode suppresses only the specified codes."""
    policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

    # Should suppress 404
    response = httpx.Response(
        HTTPStatus.NOT_FOUND, request=httpx.Request("GET", "http://test.com")
    )
    with HttpxWhackamole(policy=policy) as handler:
        msg = "Not found"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    assert handler.error_occurred


def test_inverted_mode_raises_unspecified_codes() -> None:
    """Test that inverted mode raises all codes not in suppress list."""
    policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

    # Should raise 500 (not in suppress list)
    response = httpx.Response(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        request=httpx.Request("GET", "http://test.com"),
    )
    with (
        pytest.raises(httpx.HTTPStatusError),
        HttpxWhackamole(policy=policy) as handler,
    ):
        msg = "Server error"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    assert not handler.error_occurred


def test_inverted_mode_raises_network_errors() -> None:
    """Test that inverted mode raises network errors by default."""
    policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

    # Should raise network errors in inverted mode
    with (
        pytest.raises(httpx.ConnectTimeout),
        HttpxWhackamole(policy=policy) as handler,
    ):
        msg = "Connect timeout"
        raise httpx.ConnectTimeout(msg)

    assert not handler.error_occurred


@pytest.mark.parametrize(
    ("status_code", "should_suppress"),
    [
        (HTTPStatus.NOT_FOUND, True),  # Should suppress
        (HTTPStatus.FORBIDDEN, True),  # Should suppress
        (HTTPStatus.SERVICE_UNAVAILABLE, True),  # Should suppress
        (HTTPStatus.INTERNAL_SERVER_ERROR, False),  # Should raise
    ],
)
def test_inverted_mode_multiple_suppress_codes(
    status_code: HTTPStatus, should_suppress: bool
) -> None:
    """Test inverted mode with multiple suppressed codes."""
    policy = ErrorPolicy.raise_all_except(
        HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN, HTTPStatus.SERVICE_UNAVAILABLE
    )

    response = httpx.Response(
        status_code, request=httpx.Request("GET", "http://test.com")
    )
    msg = "Error"

    if should_suppress:
        with HttpxWhackamole(policy=policy) as handler:
            raise httpx.HTTPStatusError(
                msg, request=response.request, response=response
            )
        assert handler.error_occurred
    else:
        with (
            pytest.raises(httpx.HTTPStatusError),
            HttpxWhackamole(policy=policy) as handler,
        ):
            raise httpx.HTTPStatusError(
                msg, request=response.request, response=response
            )
        assert not handler.error_occurred


@pytest.mark.parametrize(
    "error_type",
    [
        "404",  # 404 should be suppressed (file truly missing)
        "network",  # Network errors should raise (transient)
        "500",  # 500 errors should raise (transient)
    ],
)
def test_verification_policy(error_type: str) -> None:
    """Test verification use case: only 404 is suppressed, others raise."""
    policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

    if error_type == "404":
        response = httpx.Response(
            HTTPStatus.NOT_FOUND, request=httpx.Request("GET", "http://test.com")
        )
        with HttpxWhackamole(policy=policy) as handler:
            msg = "Not found"
            raise httpx.HTTPStatusError(
                msg, request=response.request, response=response
            )
        assert handler.error_occurred

    elif error_type == "network":
        with (
            pytest.raises(httpx.ConnectTimeout),
            HttpxWhackamole(policy=policy) as handler,
        ):
            msg = "Network timeout"
            raise httpx.ConnectTimeout(msg)
        assert not handler.error_occurred

    elif error_type == "500":
        response = httpx.Response(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            request=httpx.Request("GET", "http://test.com"),
        )
        with (
            pytest.raises(httpx.HTTPStatusError),
            HttpxWhackamole(policy=policy) as handler,
        ):
            msg = "Server error"
            raise httpx.HTTPStatusError(
                msg, request=response.request, response=response
            )
        assert not handler.error_occurred


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS WITH raise_for_status()
# ═══════════════════════════════════════════════════════════════════════════


def test_realistic_usage_with_raise_for_status(httpx_mock: HTTPXMock) -> None:
    """Test realistic usage pattern with raise_for_status()."""
    # Mock successful response
    httpx_mock.add_response(status_code=200, json={"data": "success"})

    # Only raise auth and rate-limit errors
    policy = ErrorPolicy(
        raise_for_status=(HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS)
    )

    with HttpxWhackamole(policy=policy) as handler:
        response = httpx.get("https://api.example.com/data")
        response.raise_for_status()
        if not handler.error_occurred:
            result = response.json()

    assert not handler.error_occurred
    assert result == {"data": "success"}


def test_realistic_usage_suppresses_transient_errors(httpx_mock: HTTPXMock) -> None:
    """Test that transient errors (404, 500) are suppressed."""
    # Mock 404 response
    httpx_mock.add_response(status_code=404)

    policy = ErrorPolicy(
        raise_for_status=(HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS)
    )

    result = None
    with HttpxWhackamole(policy=policy) as handler:
        response = httpx.get("https://api.example.com/missing")
        response.raise_for_status()
        if not handler.error_occurred:  # pragma: no cover
            result = response.json()

    assert handler.error_occurred
    assert result is None


def test_realistic_usage_raises_critical_errors(httpx_mock: HTTPXMock) -> None:
    """Test that critical errors (401, 429) are raised."""
    # Mock 401 response
    httpx_mock.add_response(status_code=401)

    policy = ErrorPolicy(
        raise_for_status=(HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS)
    )

    with pytest.raises(httpx.HTTPStatusError), HttpxWhackamole(policy=policy):
        response = httpx.get("https://api.example.com/protected")
        response.raise_for_status()


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK TESTS
# ═══════════════════════════════════════════════════════════════════════════


def test_on_error_callback_called_when_error_suppressed() -> None:
    """Test that on_error callback is invoked when an error is suppressed."""
    callback = Mock()
    policy = ErrorPolicy(raise_for_status=())  # Suppress all errors

    response = httpx.Response(
        HTTPStatus.NOT_FOUND, request=httpx.Request("GET", "http://test.com")
    )

    with HttpxWhackamole(policy=policy, on_error=callback) as handler:
        msg = "Not found"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    # Callback should have been called
    callback.assert_called_once()

    # Check the ErrorContext passed to callback
    ctx: ErrorContext = callback.call_args[0][0]
    assert isinstance(ctx.exception, httpx.HTTPStatusError)
    assert ctx.was_suppressed is True
    assert ctx.status_code == HTTPStatus.NOT_FOUND
    assert ctx.request is not None
    assert ctx.response is not None
    assert handler.error_occurred


def test_on_error_callback_called_when_error_raised() -> None:
    """Test that on_error callback is invoked even when error will be raised."""
    callback = Mock()
    policy = ErrorPolicy.default()  # Raise all errors

    response = httpx.Response(
        HTTPStatus.NOT_FOUND, request=httpx.Request("GET", "http://test.com")
    )

    with (
        pytest.raises(httpx.HTTPStatusError),
        HttpxWhackamole(policy=policy, on_error=callback) as handler,
    ):
        msg = "Not found"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    # Callback should have been called even though error was raised
    callback.assert_called_once()

    # Check the ErrorContext
    ctx: ErrorContext = callback.call_args[0][0]
    assert ctx.was_suppressed is False  # Error was not suppressed
    assert ctx.status_code == HTTPStatus.NOT_FOUND
    assert not handler.error_occurred


def test_on_success_callback_called_when_no_error() -> None:
    """Test that on_success callback is invoked when no error occurs."""
    callback = Mock()

    with HttpxWhackamole(on_success=callback) as handler:
        # No error
        pass

    callback.assert_called_once()
    assert not handler.error_occurred


def test_on_success_callback_not_called_on_error() -> None:
    """Test that on_success callback is NOT invoked when error occurs."""
    success_callback = Mock()
    error_callback = Mock()
    policy = ErrorPolicy(raise_for_status=())  # Suppress all

    response = httpx.Response(
        HTTPStatus.NOT_FOUND, request=httpx.Request("GET", "http://test.com")
    )

    with HttpxWhackamole(
        policy=policy, on_error=error_callback, on_success=success_callback
    ) as handler:
        msg = "Not found"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    error_callback.assert_called_once()
    success_callback.assert_not_called()
    assert handler.error_occurred


def test_callbacks_via_subclassing() -> None:
    """Test that callbacks work via subclassing pattern."""
    error_callback = Mock()
    success_callback = Mock()

    class CustomWhackamole(HttpxWhackamole):
        def on_error(self, ctx: ErrorContext) -> None:
            error_callback(ctx)

        def on_success(self) -> None:
            success_callback()

    # Test error case
    policy = ErrorPolicy(raise_for_status=())
    response = httpx.Response(
        HTTPStatus.NOT_FOUND, request=httpx.Request("GET", "http://test.com")
    )

    with CustomWhackamole(policy=policy):
        msg = "Not found"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    error_callback.assert_called_once()
    success_callback.assert_not_called()

    # Reset and test success case
    error_callback.reset_mock()
    success_callback.reset_mock()

    with CustomWhackamole():
        pass

    success_callback.assert_called_once()
    error_callback.assert_not_called()


def test_instance_callbacks_override_class_callbacks() -> None:
    """Test that instance callbacks override subclass callbacks."""
    class_error_callback = Mock()
    instance_error_callback = Mock()

    class CustomWhackamole(HttpxWhackamole):
        def on_error(self, ctx: ErrorContext) -> None:
            class_error_callback(ctx)  # pragma: no cover

    policy = ErrorPolicy(raise_for_status=())
    response = httpx.Response(
        HTTPStatus.NOT_FOUND, request=httpx.Request("GET", "http://test.com")
    )

    # Pass instance callback to override class callback
    with CustomWhackamole(policy=policy, on_error=instance_error_callback):
        msg = "Not found"
        raise httpx.HTTPStatusError(msg, request=response.request, response=response)

    # Only instance callback should be called
    instance_error_callback.assert_called_once()
    class_error_callback.assert_not_called()


def test_error_context_for_network_error() -> None:
    """Test that ErrorContext is populated correctly for network errors."""
    callback = Mock()
    policy = ErrorPolicy(raise_for_status=())  # Suppress all

    request = httpx.Request("GET", "http://test.com")

    with HttpxWhackamole(policy=policy, on_error=callback):
        msg = "Connection timeout"
        raise httpx.ConnectTimeout(msg, request=request)

    callback.assert_called_once()

    ctx: ErrorContext = callback.call_args[0][0]
    assert isinstance(ctx.exception, httpx.ConnectTimeout)
    assert ctx.was_suppressed is True
    assert ctx.request is not None
    assert ctx.response is None  # Network errors don't have responses
    assert ctx.status_code is None


def test_no_callback_invoked_for_non_http_error() -> None:
    """Test that callbacks are not invoked for non-HTTP errors."""
    error_callback = Mock()
    success_callback = Mock()

    with (
        pytest.raises(ValueError),  # noqa: PT011
        HttpxWhackamole(on_error=error_callback, on_success=success_callback),
    ):
        msg = "Not an HTTP error"
        raise ValueError(msg)

    # Neither callback should be called for non-HTTP errors
    error_callback.assert_not_called()
    success_callback.assert_not_called()
