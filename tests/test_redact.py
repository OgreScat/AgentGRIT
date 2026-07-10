"""
Unit tests for secret redaction.

CRITICAL: If these tests fail, secrets may leak to logs/Telegram.
"""

import pytest
from src.security.redact import redact, redact_dict, SECRET_PATTERNS


class TestRedactPatterns:
    """Test that all secret patterns are correctly redacted."""

    def test_anthropic_api_key_full(self):
        """Real Anthropic key format: sk-ant-api03-..."""
        text = "Key: sk-ant-api03-abcdef123456789012345678901234567890"
        result = redact(text)
        assert "sk-ant-api03" not in result
        assert "[REDACTED" in result

    def test_anthropic_api_key_short(self):
        """Shorter Anthropic key still redacted."""
        text = "Key: sk-ant-api03-abcdef123456"
        result = redact(text)
        assert "sk-ant-api03" not in result
        assert "[REDACTED" in result

    def test_telegram_bot_token(self):
        """Telegram bot tokens: digits:alphanumeric."""
        text = "Bot token is 1234567890:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQr"
        result = redact(text)
        assert "1234567890:AABBCCDD" not in result
        assert "[REDACTED" in result

    def test_telegram_token_different_length(self):
        """Telegram tokens with different ID lengths."""
        text = "token=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = redact(text)
        assert "123456789:ABCDEFG" not in result
        assert "[REDACTED" in result

    def test_perplexity_api_key(self):
        """Perplexity API keys: pplx-..."""
        text = "PPLX key: pplx-abc123def456ghi789jkl012mno345pqr678"
        result = redact(text)
        assert "pplx-abc123" not in result
        assert "[REDACTED" in result

    def test_bearer_token(self):
        """Bearer tokens in Authorization headers."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
        result = redact(text)
        assert "eyJhbGciOiJI" not in result
        assert "[REDACTED" in result

    def test_uuid_format(self):
        """UUIDs."""
        text = "API key: 550e8400-e29b-41d4-a716-446655440000"
        result = redact(text)
        assert "550e8400-e29b" not in result
        assert "[REDACTED" in result

    def test_xai_grok_key(self):
        """xAI/Grok API keys."""
        text = "Grok key: xai-abcdefghijklmnopqrstuvwxyz"
        result = redact(text)
        assert "xai-abcdef" not in result
        assert "[REDACTED" in result

    def test_generic_token_assignment(self):
        """Generic token assignments like token=xyz."""
        text = 'config: token="abcdefghijklmnopqrstuvwxyz123456"'
        result = redact(text)
        assert "abcdefghijklmnopqrs" not in result
        assert "[REDACTED" in result


class TestRedactNoFalsePositives:
    """Ensure we don't redact normal text."""

    def test_normal_text_untouched(self):
        """Regular text should not be modified."""
        text = "Hello world, this is a normal message."
        result = redact(text)
        assert result == text

    def test_short_strings_untouched(self):
        """Short strings shouldn't trigger patterns."""
        text = "token: abc"
        result = redact(text)
        # Short values shouldn't be redacted
        assert "abc" in result

    def test_code_snippets_untouched(self):
        """Code that looks like keys but isn't."""
        text = "function sk-ant() { return true; }"
        result = redact(text)
        # Pattern requires more chars after sk-ant-
        assert "sk-ant()" in result


class TestRedactDict:
    """Test dictionary redaction for JSON logging."""

    def test_sensitive_key_names(self):
        """Keys with sensitive names are redacted."""
        d = {
            "api_key": "sk-ant-api03-secret123456789",
            "password": "supersecret",
            "token": "mytoken1234567890",
            "normal": "visible",
        }
        result = redact_dict(d)
        assert "[REDACTED" in result["api_key"]
        assert "[REDACTED" in result["password"]
        assert "[REDACTED" in result["token"]
        assert result["normal"] == "visible"

    def test_nested_dict(self):
        """Nested dictionaries are recursively redacted."""
        d = {
            "config": {
                "api_key": "sk-ant-api03-nested123456789",
                "debug": True,
            }
        }
        result = redact_dict(d)
        assert "[REDACTED" in result["config"]["api_key"]
        assert result["config"]["debug"] is True

    def test_pattern_in_values(self):
        """Values containing patterns are redacted even without sensitive key names."""
        d = {
            "message": "Use token 1234567890:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQr",
        }
        result = redact_dict(d)
        assert "1234567890:AABBCC" not in result["message"]
        assert "[REDACTED" in result["message"]


class TestRedactShowsLastN:
    """Test that we show last N chars for identification."""

    def test_shows_suffix(self):
        """Redacted output shows last 4 chars by default."""
        text = "sk-ant-api03-abcdefghij1234"
        result = redact(text, show_last_n=4)
        assert "1234]" in result or "1234" in result  # Last 4 visible

    def test_custom_suffix_length(self):
        """Custom suffix length works."""
        text = "sk-ant-api03-abcdefghij123456"
        result = redact(text, show_last_n=6)
        assert "123456" in result  # Last 6 visible


class TestPatternCoverage:
    """Ensure our patterns match what we claim."""

    def test_all_patterns_compile(self):
        """All patterns should be valid compiled regex."""
        for pattern in SECRET_PATTERNS:
            assert hasattr(pattern, 'search'), f"Pattern not compiled: {pattern}"

    def test_pattern_count(self):
        """We should have patterns for all known secret types."""
        # Anthropic, Telegram, Perplexity, UUID, xAI, Bearer, generic token
        assert len(SECRET_PATTERNS) >= 7


class TestBoundaryLengths:
    """Test exact boundary lengths for each pattern."""

    def test_anthropic_at_boundary(self):
        """sk-ant- needs 10+ chars after prefix."""
        # At boundary (10 chars) - should redact
        at_boundary = "sk-ant-api03-1234"  # 10 chars after sk-ant-
        result = redact(at_boundary)
        assert "[REDACTED" in result

        # Below boundary (9 chars) - should NOT redact
        below = "sk-ant-api03-123"  # 9 chars after sk-ant-
        result = redact(below)
        assert result == below

    def test_telegram_at_boundary(self):
        """Telegram needs 9+ digit ID and 30+ char token."""
        # At boundary - should redact
        at_boundary = "123456789:" + "A" * 30
        result = redact(at_boundary)
        assert "[REDACTED" in result

        # Below boundary (29 char token) - should NOT redact
        below = "123456789:" + "A" * 29
        result = redact(below)
        assert result == below

    def test_perplexity_at_boundary(self):
        """pplx- needs 20+ chars after prefix."""
        # At boundary - should redact
        at_boundary = "pplx-" + "a" * 20
        result = redact(at_boundary)
        assert "[REDACTED" in result

        # Below boundary - should NOT redact
        below = "pplx-" + "a" * 19
        result = redact(below)
        assert result == below


class TestFalsePositives:
    """Negative control corpus - things that look like secrets but aren't."""

    def test_function_names_not_redacted(self):
        """Code patterns shouldn't trigger."""
        text = "def sk_ant_helper(): pass"
        result = redact(text)
        assert result == text

    def test_short_uuids_not_redacted(self):
        """Partial UUIDs shouldn't match."""
        text = "id: a1b2c3d4-e5f6"
        result = redact(text)
        assert result == text

    def test_numeric_ids_not_redacted(self):
        """Plain numeric IDs without token part."""
        text = "user_id: 1234567890"
        result = redact(text)
        assert result == text

    def test_bearer_with_short_token(self):
        """Bearer with short value shouldn't match."""
        text = "Authorization: Bearer short"
        result = redact(text)
        assert result == text


class TestEmbeddedSecrets:
    """Test secrets embedded in larger structures."""

    def test_secret_in_json(self):
        """Secrets in JSON strings should be redacted."""
        text = '{"api_key": "sk-ant-api03-realkey12345"}'
        result = redact(text)
        assert "sk-ant-api03" not in result
        assert "[REDACTED" in result

    def test_secret_in_log_line(self):
        """Secrets in log lines should be redacted."""
        text = "2024-01-01 INFO: Using token 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"
        result = redact(text)
        assert "123456789:ABCDEF" not in result

    def test_multiple_secrets_same_line(self):
        """Multiple secrets on one line all redacted."""
        text = "Keys: sk-ant-api03-key1234567 and pplx-abcdefghijklmnopqrst"
        result = redact(text)
        assert "sk-ant-api03" not in result
        assert "pplx-abcdef" not in result
        assert result.count("[REDACTED") == 2

    def test_secret_in_url(self):
        """Secrets in URLs should be redacted."""
        text = "https://api.example.com?token=sk-ant-api03-urlkey1234"
        result = redact(text)
        assert "sk-ant-api03" not in result


# Run the same self-test that runs on module import
class TestSelfTest:
    """Replicate the module self-test as a proper unit test."""

    def test_self_test_cases(self):
        """All self-test cases pass."""
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
                match = pattern.search(result)
                assert match is None, f"Secret still present in result: {result}"
