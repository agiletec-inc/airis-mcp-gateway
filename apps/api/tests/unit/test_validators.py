"""
Unit tests for API Key Validators.

Tests cover:
- Empty/null validation
- Length validation
- Pattern-based validation for various services
- Generic validation fallback
"""

import pytest

from app.core.validators import APIKeyValidator, validate_api_key


class TestAPIKeyValidatorBasic:
    """Test basic validation rules."""

    def test_empty_key_invalid(self):
        """Test empty key is invalid."""
        is_valid, error = APIKeyValidator.validate("TEST_KEY", "")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_whitespace_only_invalid(self):
        """Test whitespace-only key is invalid."""
        is_valid, error = APIKeyValidator.validate("TEST_KEY", "   ")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_too_short_invalid(self):
        """Test key shorter than 10 chars is invalid."""
        is_valid, error = APIKeyValidator.validate("TEST_KEY", "abc")
        assert is_valid is False
        assert "short" in error.lower()

    def test_too_long_invalid(self):
        """Test key longer than 500 chars is invalid."""
        long_key = "a" * 501
        is_valid, error = APIKeyValidator.validate("TEST_KEY", long_key)
        assert is_valid is False
        assert "long" in error.lower()

    def test_newline_invalid(self):
        """Test key with newline is invalid."""
        is_valid, error = APIKeyValidator.validate("TEST_KEY", "valid_key_here\nmore")
        assert is_valid is False
        assert "newline" in error.lower()

    def test_carriage_return_invalid(self):
        """Test key with carriage return is invalid."""
        is_valid, error = APIKeyValidator.validate("TEST_KEY", "valid_key_here\rmore")
        assert is_valid is False
        assert "newline" in error.lower()


class TestTavilyAPIKey:
    """Test Tavily API key validation."""

    def test_valid_tavily_key(self):
        """Test valid Tavily key format."""
        is_valid, error = APIKeyValidator.validate(
            "TAVILY_API_KEY", "tvly-ABC123xyz456789012"
        )
        assert is_valid is True
        assert error is None

    def test_valid_tavily_key_underscore(self):
        """Test valid Tavily key with underscore separator."""
        is_valid, error = APIKeyValidator.validate(
            "TAVILY_API_KEY", "tvly_ABC123xyz456789012"
        )
        assert is_valid is True

    def test_invalid_tavily_key(self):
        """Test invalid Tavily key format."""
        is_valid, error = APIKeyValidator.validate(
            "TAVILY_API_KEY", "invalid_key_format_12345"
        )
        assert is_valid is False
        assert "Invalid format" in error


class TestStripeSecretKey:
    """Test Stripe secret key validation."""

    def test_valid_stripe_test_key(self):
        """Test valid Stripe test key."""
        is_valid, error = APIKeyValidator.validate(
            "STRIPE_SECRET_KEY", "sk_test_" + "a" * 24
        )
        assert is_valid is True

    def test_valid_stripe_live_key(self):
        """Test valid Stripe live key."""
        is_valid, error = APIKeyValidator.validate(
            "STRIPE_SECRET_KEY", "sk_live_" + "a" * 24
        )
        assert is_valid is True

    def test_invalid_stripe_key(self):
        """Test invalid Stripe key format."""
        is_valid, error = APIKeyValidator.validate(
            "STRIPE_SECRET_KEY", "not_a_stripe_key_123456"
        )
        assert is_valid is False


class TestGitHubToken:
    """Test GitHub personal access token validation."""

    def test_valid_github_classic_token(self):
        """Test valid GitHub classic token (ghp_)."""
        is_valid, error = APIKeyValidator.validate(
            "GITHUB_PERSONAL_ACCESS_TOKEN", "ghp_" + "a" * 36
        )
        assert is_valid is True

    def test_valid_github_fine_grained_token(self):
        """Test valid GitHub fine-grained token (ghs_)."""
        is_valid, error = APIKeyValidator.validate(
            "GITHUB_PERSONAL_ACCESS_TOKEN", "ghs_" + "a" * 36
        )
        assert is_valid is True

    def test_invalid_github_token(self):
        """Test invalid GitHub token."""
        is_valid, error = APIKeyValidator.validate(
            "GITHUB_PERSONAL_ACCESS_TOKEN", "github_pat_invalid_format"
        )
        assert is_valid is False


class TestOpenAIAPIKey:
    """Test OpenAI API key validation."""

    def test_valid_openai_key(self):
        """Test valid OpenAI key."""
        is_valid, error = APIKeyValidator.validate("OPENAI_API_KEY", "sk-" + "a" * 48)
        assert is_valid is True

    def test_invalid_openai_key(self):
        """Test invalid OpenAI key."""
        is_valid, error = APIKeyValidator.validate(
            "OPENAI_API_KEY", "openai_key_invalid"
        )
        assert is_valid is False


class TestAnthropicAPIKey:
    """Test Anthropic API key validation."""

    def test_valid_anthropic_key(self):
        """Test valid Anthropic key."""
        is_valid, error = APIKeyValidator.validate(
            "ANTHROPIC_API_KEY", "sk-ant-" + "a" * 95
        )
        assert is_valid is True

    def test_invalid_anthropic_key(self):
        """Test invalid Anthropic key."""
        is_valid, error = APIKeyValidator.validate(
            "ANTHROPIC_API_KEY", "anthropic_key_invalid"
        )
        assert is_valid is False


class TestSupabaseKeys:
    """Test Supabase URL and key validation."""

    def test_valid_supabase_url(self):
        """Test valid Supabase URL."""
        is_valid, error = APIKeyValidator.validate(
            "SUPABASE_URL", "https://abc123xyz.supabase.co"
        )
        assert is_valid is True

    def test_invalid_supabase_url(self):
        """Test invalid Supabase URL."""
        is_valid, error = APIKeyValidator.validate(
            "SUPABASE_URL", "https://example.com"
        )
        assert is_valid is False

    def test_valid_supabase_anon_key(self):
        """Test valid Supabase anon key (JWT format)."""
        # JWT format: header.payload.signature
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        is_valid, error = APIKeyValidator.validate("SUPABASE_ANON_KEY", jwt)
        assert is_valid is True


class TestPostgresKeys:
    """Test Postgres DSN and related validation."""

    def test_valid_postgres_dsn(self):
        """Test valid Postgres DSN."""
        is_valid, error = APIKeyValidator.validate(
            "PG_DSN", "postgres://user:pass@localhost:5432/db"
        )
        assert is_valid is True

    def test_valid_postgresql_dsn(self):
        """Test valid PostgreSQL DSN."""
        is_valid, error = APIKeyValidator.validate(
            "PG_DSN", "postgresql://user:pass@localhost:5432/db"
        )
        assert is_valid is True

    def test_valid_postgrest_url(self):
        """Test valid PostgREST URL."""
        is_valid, error = APIKeyValidator.validate(
            "POSTGREST_URL", "https://api.example.com/rest/v1"
        )
        assert is_valid is True


class TestShortValueKeys:
    """Test short value keys like READ_ONLY."""

    def test_valid_read_only_true(self):
        """Test READ_ONLY=true is valid."""
        is_valid, error = APIKeyValidator.validate("READ_ONLY", "true")
        assert is_valid is True

    def test_valid_read_only_false(self):
        """Test READ_ONLY=false is valid."""
        is_valid, error = APIKeyValidator.validate("READ_ONLY", "false")
        assert is_valid is True

    def test_invalid_read_only(self):
        """Test invalid READ_ONLY value."""
        is_valid, error = APIKeyValidator.validate("READ_ONLY", "yes")
        assert is_valid is False


class TestFeaturesKey:
    """Test FEATURES validation."""

    def test_valid_single_feature(self):
        """Test single feature (must be >= 10 chars due to min length check)."""
        is_valid, error = APIKeyValidator.validate("FEATURES", "authentication")
        assert is_valid is True

    def test_valid_multiple_features(self):
        """Test multiple features."""
        is_valid, error = APIKeyValidator.validate("FEATURES", "auth,storage,functions")
        assert is_valid is True

    def test_valid_hyphenated_feature(self):
        """Test hyphenated feature name (must be >= 10 chars)."""
        is_valid, error = APIKeyValidator.validate("FEATURES", "real-time-sync")
        assert is_valid is True


class TestUnknownKeys:
    """Test validation of unknown key types."""

    def test_unknown_key_generic_validation(self):
        """Test unknown key passes generic validation."""
        is_valid, error = APIKeyValidator.validate(
            "UNKNOWN_SERVICE_KEY", "some_valid_key_value_12345"
        )
        assert is_valid is True

    def test_unknown_key_strips_whitespace(self):
        """Test unknown key has whitespace stripped."""
        is_valid, error = APIKeyValidator.validate("UNKNOWN_KEY", "  valid_key_12345  ")
        assert is_valid is True


class TestValidateAPIKeyFunction:
    """Test validate_api_key helper function."""

    def test_valid_key_no_exception(self):
        """Test valid key doesn't raise."""
        # Should not raise
        validate_api_key("TEST_KEY", "some_valid_key_value_12345")

    def test_invalid_key_raises(self):
        """Test invalid key raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_api_key("TEST_KEY", "")
        assert "empty" in str(exc_info.value).lower()
