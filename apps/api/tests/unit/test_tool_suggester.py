"""Tests for tool_suggester module."""

import pytest
from app.core.tool_suggester import (
    SuggestToolRequest,
    SuggestToolResponse,
    ToolSuggestion,
    suggest_tool,
    format_suggestions_as_text,
    _extract_keywords,
    _calculate_match_score,
)


class TestExtractKeywords:
    """Test _extract_keywords function."""

    def test_basic_extraction(self):
        """Test basic keyword extraction."""
        keywords = _extract_keywords("Create an invoice with Stripe")
        assert "create" in keywords
        assert "invoice" in keywords
        assert "stripe" in keywords

    def test_stopword_removal(self):
        """Test that stopwords are removed."""
        keywords = _extract_keywords("I want to create a new file")
        assert "want" not in keywords
        assert "the" not in keywords
        assert "create" in keywords
        assert "file" in keywords

    def test_short_word_removal(self):
        """Test that short words are removed."""
        keywords = _extract_keywords("Go to the URL and do it")
        assert "go" not in keywords
        assert "to" not in keywords
        assert "it" not in keywords

    def test_synonym_expansion(self):
        """Test that synonyms are expanded."""
        keywords = _extract_keywords("make a new document")
        # "make" should expand to include "create"
        assert "create" in keywords or "make" in keywords

    def test_empty_input(self):
        """Test empty input returns empty list."""
        keywords = _extract_keywords("")
        assert keywords == []


class TestCalculateMatchScore:
    """Test _calculate_match_score function."""

    def test_perfect_match(self):
        """Test perfect match returns high score."""
        score, matched = _calculate_match_score(
            ["stripe", "invoice", "create"],
            ["stripe", "invoice", "create"],
        )
        assert score == 1.0
        assert len(matched) == 3

    def test_partial_match(self):
        """Test partial match returns proportional score."""
        score, matched = _calculate_match_score(
            ["stripe", "invoice"],
            ["stripe", "invoice", "create", "billing"],
        )
        assert 0 < score < 1.0
        assert "stripe" in matched
        assert "invoice" in matched

    def test_no_match(self):
        """Test no match returns zero score."""
        score, matched = _calculate_match_score(
            ["database", "query"],
            ["browser", "navigate", "click"],
        )
        assert score == 0.0
        assert len(matched) == 0

    def test_empty_inputs(self):
        """Test empty inputs return zero score."""
        score, matched = _calculate_match_score([], ["stripe"])
        assert score == 0.0

        score, matched = _calculate_match_score(["stripe"], [])
        assert score == 0.0


class TestToolSuggestion:
    """Test ToolSuggestion dataclass."""

    def test_to_dict(self):
        """Test dictionary conversion."""
        suggestion = ToolSuggestion(
            server="stripe",
            tool="create_invoice",
            score=0.85,
            reason="Matched: stripe, invoice",
        )
        d = suggestion.to_dict()
        assert d["server"] == "stripe"
        assert d["tool"] == "create_invoice"
        assert d["score"] == 0.85
        assert d["reason"] == "Matched: stripe, invoice"


class TestSuggestToolResponse:
    """Test SuggestToolResponse dataclass."""

    def test_to_dict(self):
        """Test dictionary conversion."""
        response = SuggestToolResponse(
            suggestions=[
                ToolSuggestion(
                    server="stripe",
                    tool="create_invoice",
                    score=0.85,
                    reason="Test",
                )
            ],
            query_keywords=["stripe", "invoice"],
        )
        d = response.to_dict()
        assert len(d["suggestions"]) == 1
        assert d["query_keywords"] == ["stripe", "invoice"]


class TestSuggestTool:
    """Test suggest_tool function."""

    def test_stripe_intent(self):
        """Test Stripe-related intent."""
        request = SuggestToolRequest(intent="Create an invoice with Stripe")
        response = suggest_tool(request)

        assert isinstance(response, SuggestToolResponse)
        assert len(response.suggestions) > 0
        # Should suggest Stripe tools
        stripe_tools = [s for s in response.suggestions if s.server == "stripe"]
        assert len(stripe_tools) > 0

    def test_memory_intent(self):
        """Test memory-related intent."""
        request = SuggestToolRequest(intent="Store this knowledge in memory")
        response = suggest_tool(request)

        assert len(response.suggestions) > 0
        memory_tools = [s for s in response.suggestions if s.server == "memory"]
        assert len(memory_tools) > 0

    def test_file_intent(self):
        """Test file-related intent."""
        request = SuggestToolRequest(intent="Read the contents of a file")
        response = suggest_tool(request)

        assert len(response.suggestions) > 0
        file_tools = [s for s in response.suggestions if s.server == "filesystem"]
        assert len(file_tools) > 0

    def test_browser_intent(self):
        """Test browser-related intent."""
        request = SuggestToolRequest(intent="Navigate to a webpage and take a screenshot")
        response = suggest_tool(request)

        assert len(response.suggestions) > 0
        # Should suggest browser or playwright tools
        browser_tools = [
            s for s in response.suggestions
            if s.server in ("browser", "playwright")
        ]
        assert len(browser_tools) > 0

    def test_max_results(self):
        """Test max_results limit."""
        request = SuggestToolRequest(intent="search for files", max_results=2)
        response = suggest_tool(request)

        assert len(response.suggestions) <= 2

    def test_empty_intent(self):
        """Test empty intent returns empty suggestions."""
        request = SuggestToolRequest(intent="")
        response = suggest_tool(request)

        assert len(response.suggestions) == 0
        assert len(response.query_keywords) == 0

    def test_sorted_by_score(self):
        """Test suggestions are sorted by score descending."""
        request = SuggestToolRequest(intent="search files browser git")
        response = suggest_tool(request)

        if len(response.suggestions) >= 2:
            scores = [s.score for s in response.suggestions]
            assert scores == sorted(scores, reverse=True)


class TestFormatSuggestionsAsText:
    """Test format_suggestions_as_text function."""

    def test_format_with_suggestions(self):
        """Test formatting with suggestions."""
        response = SuggestToolResponse(
            suggestions=[
                ToolSuggestion(
                    server="stripe",
                    tool="create_invoice",
                    score=0.85,
                    reason="Matched: stripe, invoice",
                ),
                ToolSuggestion(
                    server="stripe",
                    tool="list_customers",
                    score=0.65,
                    reason="Matched: stripe",
                ),
            ],
            query_keywords=["stripe", "invoice"],
        )
        text = format_suggestions_as_text(response)

        assert "Tool Suggestions" in text
        assert "stripe:create_invoice" in text
        assert "stripe:list_customers" in text
        assert "85%" in text
        assert "65%" in text
        assert "airis-schema" in text
        assert "airis-exec" in text

    def test_format_no_suggestions(self):
        """Test formatting with no suggestions."""
        response = SuggestToolResponse(
            suggestions=[],
            query_keywords=["unknown", "tool"],
        )
        text = format_suggestions_as_text(response)

        assert "No tool suggestions found" in text
        assert "unknown" in text
        assert "airis-find" in text


class TestIntegrationWithDynamicMCP:
    """Test integration with DynamicMCP (mocked)."""

    def test_suggest_with_dynamic_mcp(self):
        """Test suggest_tool with a mock DynamicMCP."""
        from unittest.mock import MagicMock
        from app.core.dynamic_mcp import ToolInfo

        # Create mock DynamicMCP
        mock_mcp = MagicMock()
        mock_mcp._tools = {
            "custom_tool": ToolInfo(
                name="custom_tool",
                server="custom",
                description="A custom tool for testing purposes",
                input_schema={},
                source="process",
            )
        }

        request = SuggestToolRequest(intent="use the custom testing tool")
        response = suggest_tool(request, dynamic_mcp=mock_mcp)

        # Should include the custom tool from DynamicMCP
        custom_tools = [s for s in response.suggestions if s.server == "custom"]
        assert len(custom_tools) > 0
