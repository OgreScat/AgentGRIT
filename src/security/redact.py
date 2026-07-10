"""
Secret Redaction Utility

CRITICAL: All logs, Telegram output, and error messages MUST use this module.
Never print raw secrets to any output channel.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Optional

# Patterns that indicate secrets (compiled for performance)
SECRET_PATTERNS = [
    re.compile(r'pplx-[A-Za-z0-9]{20,}'),           # Perplexity API keys (min 20 chars after prefix)
    re.compile(r'\d{9,}:[A-Za-z0-9_-]{30,}'),       # Telegram bot tokens (9+ digit ID : 30+ char token)
    re.compile(r'sk-ant-[A-Za-z0-9-]{10,}'),        # Anthropic API keys (min 10 chars after sk-ant-)
    re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'),  # UUIDs
    re.compile(r'xai-[A-Za-z0-9]{20,}'),            # xAI/Grok keys
    re.compile(r'Bearer [A-Za-z0-9._-]{20,}'),      # Bearer tokens
    re.compile(r'token["\']?\s*[:=]\s*["\']?[A-Za-z0-9._-]{20,}', re.I),  # Generic tokens
]

# Environment variable names that contain secrets
SECRET_ENV_VARS = frozenset([
    'PPLX_API_KEY',
    'TELEGRAM_BOT_TOKEN',
    'ANTHROPIC_API_KEY',
    'GROK_API_KEY',
    'API_SECRET_KEY',
    'ENCRYPTION_KEY',
])


@lru_cache(maxsize=128)
def _get_env_secrets() -> frozenset:
    """Get current secret values from environment (cached)."""
    secrets = set()
    for var in SECRET_ENV_VARS:
        val = os.getenv(var, '')
        if val and len(val) > 8 and not val.startswith('ROTATE_ME'):
            secrets.add(val)
    return frozenset(secrets)


def redact(text: str, show_last_n: int = 4) -> str:
    """
    Redact all secrets from text.

    Args:
        text: Input text that may contain secrets
        show_last_n: Number of characters to show at end (for identification)

    Returns:
        Text with all secrets replaced by [REDACTED...xxxx]
    """
    if not text:
        return text

    result = str(text)

    # Redact known env var values
    for secret in _get_env_secrets():
        if secret in result:
            suffix = secret[-show_last_n:] if len(secret) > show_last_n else ''
            result = result.replace(secret, f'[REDACTED...{suffix}]')

    # Redact pattern matches
    for pattern in SECRET_PATTERNS:
        def replacer(m):
            val = m.group(0)
            suffix = val[-show_last_n:] if len(val) > show_last_n else ''
            return f'[REDACTED...{suffix}]'
        result = pattern.sub(replacer, result)

    return result


def redact_dict(d: dict, keys_to_redact: Optional[set] = None) -> dict:
    """
    Redact secrets from a dictionary (for JSON logging).

    Args:
        d: Dictionary to redact
        keys_to_redact: Additional key names to fully redact

    Returns:
        New dictionary with redacted values
    """
    keys_to_redact = keys_to_redact or set()
    sensitive_keys = {'token', 'key', 'secret', 'password', 'credential', 'auth'}

    result = {}
    for k, v in d.items():
        k_lower = k.lower()

        # Fully redact known sensitive keys
        if k in keys_to_redact or any(s in k_lower for s in sensitive_keys):
            if isinstance(v, str) and len(v) > 4:
                result[k] = f'[REDACTED...{v[-4:]}]'
            else:
                result[k] = '[REDACTED]'
        elif isinstance(v, dict):
            result[k] = redact_dict(v, keys_to_redact)
        elif isinstance(v, str):
            result[k] = redact(v)
        else:
            result[k] = v

    return result


def safe_log(message: str) -> str:
    """Shorthand for redacting a log message."""
    return redact(message)


def clear_cache():
    """Clear the cached secrets (call after .env reload)."""
    _get_env_secrets.cache_clear()


# Self-test on import
def _self_test():
    """Verify redaction is working."""
    test_cases = [
        ('Token is pplx-abc123def456ghi789jkl012mno345pqr678', '[REDACTED'),
        ('Bot 1234567890:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQr', '[REDACTED'),
        ('Key: sk-ant-api03-abcdef123456', '[REDACTED'),
    ]

    for text, expected_substr in test_cases:
        result = redact(text)
        assert expected_substr in result, f"Redaction failed for: {text}"
        # Verify original secret is NOT in output
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(result), f"Secret still present in: {result}"


# Run self-test on module load (fail fast if broken)
try:
    _self_test()
except AssertionError as e:
    import warnings
    warnings.warn(f"Redaction self-test failed: {e}")
