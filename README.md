# httpx-whackamole

A policy-based error handling pattern for httpx HTTP operations. The "whackamole" pattern lets you selectively suppress or raise HTTP errors based on configurable policies - like the whack-a-mole game where you decide which errors to "whack" (suppress) and which to let through.

## Background

This module was built for a common use case: processing tens of thousands of API requests where some failures are inevitable and acceptable. When you're making 50,000 HTTP calls, network timeouts, temporary 503s, and rate limits aren't bugs—they're statistical certainties.

The key insight is distinguishing between errors that need immediate attention (authentication failures, invalid API keys) and transient issues that will resolve themselves (network hiccups, temporary server overload). The whackamole pattern lets you explicitly declare this distinction, turning 40 lines of error handling into 6 lines of clear intent.

Best of all, it's safe by default - all errors are raised unless you explicitly choose to suppress them. No accidental error swallowing.

### When to Use This Pattern

✅ **Good for:**

- API clients with varying error tolerance
- Batch processing where some failures are acceptable
- Verification operations (checking if resources exist)
- Services that need resilience to transient failures
- Retry logic implementation
- Multi-service orchestration where partial failures are OK

❌ **Not ideal for:**

- Critical operations where all errors must be handled explicitly
- Debugging scenarios where you need full error details
- Simple scripts with straightforward error handling
- When you need different handling for the same error in different contexts

## Installation

```bash
# Using uv
uv add httpx-whackamole

# Or with pip
pip install httpx-whackamole
```

## Quick Start

```python
from http import HTTPStatus
import httpx
from whackamole import HttpxWhackamole, ErrorPolicy

# Default policy: Raise all errors (safe by default)
with HttpxWhackamole() as handler:
    response = httpx.get("https://api.example.com/data")
    response.raise_for_status()
    # All errors will be raised unless you specify a policy

# To suppress specific errors, use a custom policy
policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)
with HttpxWhackamole(policy=policy) as handler:
    response = httpx.get("https://api.example.com/data")
    response.raise_for_status()
    # Only 404 errors will be suppressed

if handler.error_occurred:
    print("Request failed with a 404")
```

## Usage Patterns

### Example: Batch Processing

```python
# Processing 50,000 files from an API
def sync_remote_files(file_ids: list[str]) -> dict[str, bool]:
    """Sync thousands of files, gracefully handling transient failures."""
    # Only fail on auth issues - everything else can be retried next run
    policy = ErrorPolicy(raise_for_status=(HTTPStatus.UNAUTHORIZED,))
    results = {}

    for file_id in file_ids:  # e.g., 50,000 files
        with HttpxWhackamole(policy=policy) as handler:
            response = httpx.get(f"https://api.example.com/files/{file_id}")
            response.raise_for_status()
            
            if not handler.error_occurred:
                process_file(response.json())
                results[file_id] = True
            else:
                # Will retry in next run (could be network, 500, 429, etc.)
                results[file_id] = False

    # Typically 49,950 succeed, 50 fail and get retried next run
    success_rate = sum(results.values()) / len(results) * 100
    print(f"Processed {success_rate:.1f}% successfully, will retry failures")
    return results
```

### Comparison: Vanilla httpx vs HttpxWhackamole

#### Vanilla httpx

```python
import httpx
from http import HTTPStatus

def fetch_data(url: str):
    """Fetch data, raising only auth and rate-limit errors."""
    try:
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        # Only raise critical errors, suppress everything else
        if e.response.status_code == HTTPStatus.UNAUTHORIZED:
            raise  # Auth failure - must be fixed immediately
        elif e.response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise  # Rate limit - needs backoff logic
        else:
            # All other status codes (404, 500, etc.) - suppress
            return None
    except httpx.RequestError:
        # Network errors, timeouts, protocol errors - all transient, suppress
        return None
    except ...:
        raise
```

#### With HttpxWhackamole

```python
import httpx
from http import HTTPStatus
from whackamole import HttpxWhackamole, ErrorPolicy

# Central policy. Raise only critical errors.
policy = ErrorPolicy(
    raise_for_status=(HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS)
)
    
def fetch_data(url: str):
    """Fetch data, raising only auth and rate-limit errors."""
    with HttpxWhackamole(policy=policy) as handler:
        response = httpx.get(url)
        response.raise_for_status()
        return None if handler.error_occurred else response.json()
```

### API Overview

```python
from whackamole import HttpxWhackamole, ErrorPolicy
from http import HTTPStatus

# The handler is a context manager with one attribute
with HttpxWhackamole(policy=ErrorPolicy(...)) as handler:
    # Make your HTTP calls here
    response = httpx.get(...)

    # Check if an error was suppressed
    if handler.error_occurred:  # bool: True if error was suppressed
        # Handle the suppressed error case
        pass

# ErrorPolicy has two class methods for common patterns
ErrorPolicy.default()                    # Returns policy that raises all errors
ErrorPolicy.raise_all_except(404, 503)  # Returns policy that suppresses only these codes

# Or create custom policies
ErrorPolicy(raise_for_status=(401, 429))  # Explicit mode: raise only these
ErrorPolicy(raise_for_status="all", suppress_for_status=(404,))  # Same as raise_all_except
```

### 1. Default Policy (Safe by Default)

By default, all errors are raised to ensure no errors are accidentally suppressed:

```python
with HttpxWhackamole() as handler:
    response = httpx.get(url)
    response.raise_for_status()
    # All HTTP and network errors will be raised
```

To suppress non-critical errors and only raise critical ones:

```python
# Only raise critical errors (401, 429)
policy = ErrorPolicy(raise_for_status=(HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS))
with HttpxWhackamole(policy=policy) as handler:
    response = httpx.get(url)
    response.raise_for_status()
    # 500, 503, network errors, etc. are suppressed
```

### 2. Verification Pattern

Distinguish between permanent failures (404) and transient issues:

```python
# Raise everything EXCEPT 404
policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

with HttpxWhackamole(policy=policy) as handler:
    response = httpx.get(url)
    response.raise_for_status()

if handler.error_occurred:
    # File doesn't exist (404) - expected case
    return None
# Any other error (500, network) propagates up
```

### 3. Custom Policy

Define exactly which errors to raise:

```python
# Only raise specific critical errors
policy = ErrorPolicy(
    raise_for_status=(
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.SERVICE_UNAVAILABLE
    )
)

with HttpxWhackamole(policy=policy) as handler:
    response = httpx.post(url, json=data)
    response.raise_for_status()
```

### 4. Inverted Mode (Multiple Suppressions)

Suppress multiple expected errors:

```python
# Suppress 404, 403, and 503
policy = ErrorPolicy.raise_all_except(
    HTTPStatus.NOT_FOUND,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.SERVICE_UNAVAILABLE
)

with HttpxWhackamole(policy=policy) as handler:
    response = httpx.get(url)
    response.raise_for_status()
```

## Real-World Examples

### API Client with Retry Logic

```python
async def fetch_with_retry(url: str, max_retries: int = 3):
    """Fetch data with automatic retry for transient errors."""
    # Only raise critical errors, suppress transient ones for retry
    policy = ErrorPolicy(
        raise_for_status=(HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS)
    )

    for attempt in range(max_retries):
        with HttpxWhackamole(policy=policy) as handler:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                if not handler.error_occurred:
                    return response.json()

        # Transient error occurred, wait before retry
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)

    return None  # All retries exhausted
```

### File Verification

```python
def verify_remote_file_exists(url: str) -> bool:
    """Check if a remote file exists without failing on 404."""
    policy = ErrorPolicy.raise_all_except(HTTPStatus.NOT_FOUND)

    with HttpxWhackamole(policy=policy) as handler:
        response = httpx.head(url)
        response.raise_for_status()
        return not handler.error_occurred
```

### Batch Processing

```python
def process_urls(urls: list[str]) -> dict[str, Any]:
    """Process multiple URLs, continuing on non-critical errors."""
    # Suppress all errors except authentication issues
    policy = ErrorPolicy(raise_for_status=(HTTPStatus.UNAUTHORIZED,))
    results = {}

    for url in urls:
        with HttpxWhackamole(policy=policy) as handler:
            response = httpx.get(url)
            response.raise_for_status()
            if not handler.error_occurred:
                results[url] = response.json()
            else:
                results[url] = None  # Mark as failed but continue

    return results
```

### Error Types Handled

- **HTTPStatusError**: HTTP response errors (4xx, 5xx)
- **Network errors**: Timeouts, connection failures
- **Non-HTTP errors**: Propagated unchanged (e.g., ValueError)

See the [Changelog](CHANGELOG.md) for a full list of changes.