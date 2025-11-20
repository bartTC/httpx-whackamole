"""Tests for ErrorPolicy and HttpxErrorHandler."""

from http import HTTPStatus

import httpx
import pytest

from whackamole import ErrorPolicy, HttpxWhackamole


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
