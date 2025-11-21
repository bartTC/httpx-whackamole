# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Callback support**: Execute custom code on errors or successful requests
  - `ErrorContext` dataclass providing exception, request, response, and suppression status
  - `on_error` callback invoked for all HTTP errors (both suppressed and raised)
  - `on_success` callback invoked when no error occurs
  - Support for callbacks via subclassing (define `on_error`/`on_success` methods)
  - Support for callbacks via `__init__` parameters
  - Useful for integrating error tracking (Sentry), logging, and observability
- Added integration tests demonstrating realistic usage patterns with `raise_for_status()`
- Added version comparison links to CHANGELOG for easier navigation
- Added comprehensive callback tests (8 new test cases)

### Changed
- Improved README comparison example to show realistic vanilla httpx error handling
- Updated all documentation examples to include `response.raise_for_status()` calls
- Refactored test suite to use `pytest.mark.parametrize` for better maintainability
- Updated API documentation with callback usage patterns

## [1.0.0] - 2025-11-20

### Added

- Initial release of httpx-whackamole
- `HttpxWhackamole` context manager for policy-based error handling
- `ErrorPolicy` class with two modes:
  - Explicit mode: Raise only specific status codes
  - Inverted mode: Raise all except specific status codes (default behavior)
- Default policy: Safe by default (raises all errors)
- `ErrorPolicy.default()` for the default behavior
- `ErrorPolicy.raise_all_except()` for suppressing specific status codes
- Comprehensive test suite
- Full type hints for better IDE support
- Support for Python 3.9+

### Design Philosophy

- **Safe by default**: Raises all errors to prevent accidental suppression
- **Declarative**: Clear, upfront error handling policies
- **Simple API**: Single context manager with policy object
- **Production ready**: Battle-tested in production environments

[Unreleased]: https://github.com/bartTC/httpx-whackamole/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bartTC/httpx-whackamole/commits/v1.0.0
