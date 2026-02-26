"""Tests for confidence_engine module."""

import pytest
from app.core.confidence_engine import (
    ConfidenceChecker,
    ConfidenceInput,
    ConfidenceResult,
    Verdict,
    check_confidence,
    get_confidence_checker,
)


class TestConfidenceChecker:
    """Test ConfidenceChecker class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.checker = ConfidenceChecker()

    def test_baseline_score(self):
        """Test that empty input returns baseline score."""
        result = self.checker.assess(ConfidenceInput())
        assert result.score == 0.5
        assert result.verdict == Verdict.ASK_USER

    def test_high_confidence_all_positive(self):
        """Test high confidence with all positive indicators."""
        result = self.checker.assess(
            ConfidenceInput(
                has_official_docs=True,
                has_existing_patterns=True,
                has_clear_path=True,
            )
        )
        # 0.5 + 0.2 + 0.2 + 0.2 = 1.1 -> clamped to 1.0
        assert result.score == 1.0
        assert result.verdict == Verdict.PROCEED
        assert result.should_proceed is True
        assert result.level == "high"

    def test_medium_confidence(self):
        """Test medium confidence with mixed signals."""
        result = self.checker.assess(
            ConfidenceInput(
                has_official_docs=True,
                has_existing_patterns=True,
                multiple_approaches=True,
            )
        )
        # 0.5 + 0.2 + 0.2 - 0.1 = 0.8
        assert result.score == 0.8
        assert result.verdict == Verdict.PRESENT_ALTERNATIVES
        assert result.should_proceed is False
        assert result.level == "medium"

    def test_low_confidence_with_blockers(self):
        """Test low confidence with serious blockers."""
        result = self.checker.assess(
            ConfidenceInput(
                unclear_requirements=True,
                no_precedent=True,
            )
        )
        # 0.5 - 0.2 - 0.2 = 0.1
        assert result.score == 0.1
        assert result.verdict == Verdict.STOP
        assert result.should_proceed is False
        assert result.level == "low"
        assert result.questions is not None
        assert len(result.questions) >= 2

    def test_questions_generated_for_low_confidence(self):
        """Test that clarifying questions are generated for low confidence."""
        result = self.checker.assess(
            ConfidenceInput(
                unclear_requirements=True,
                missing_domain_knowledge=True,
            )
        )
        assert result.questions is not None
        assert any("requirements" in q.lower() for q in result.questions)
        assert any("domain" in q.lower() for q in result.questions)

    def test_no_questions_for_high_confidence(self):
        """Test that no questions are generated for high confidence."""
        result = self.checker.assess(
            ConfidenceInput(
                has_official_docs=True,
                has_existing_patterns=True,
                has_clear_path=True,
            )
        )
        assert result.questions is None

    def test_score_clamping(self):
        """Test that scores are clamped to [0.0, 1.0]."""
        # All positive
        result = self.checker.assess(
            ConfidenceInput(
                has_official_docs=True,
                has_existing_patterns=True,
                has_clear_path=True,
            )
        )
        assert result.score <= 1.0

        # All negative
        result = self.checker.assess(
            ConfidenceInput(
                unclear_requirements=True,
                no_precedent=True,
                missing_domain_knowledge=True,
                multiple_approaches=True,
                has_trade_offs=True,
            )
        )
        assert result.score >= 0.0

    def test_signals_tracking(self):
        """Test that signals are properly tracked."""
        result = self.checker.assess(
            ConfidenceInput(
                has_official_docs=True,
                unclear_requirements=True,
            )
        )
        assert result.signals["has_official_docs"] is True
        assert result.signals["unclear_requirements"] is True
        assert result.signals["has_existing_patterns"] is False

    def test_reasons_populated(self):
        """Test that reasons are populated correctly."""
        result = self.checker.assess(
            ConfidenceInput(
                has_official_docs=True,
                multiple_approaches=True,
            )
        )
        assert len(result.reasons) == 2
        assert any("documentation" in r.lower() for r in result.reasons)
        assert any("approaches" in r.lower() for r in result.reasons)


class TestConfidenceResult:
    """Test ConfidenceResult class."""

    def test_to_dict(self):
        """Test dictionary conversion."""
        result = ConfidenceResult(
            score=0.9,
            verdict=Verdict.PROCEED,
            reasons=["Test reason"],
            questions=None,
            signals={"test": True},
        )
        d = result.to_dict()
        assert d["score"] == 0.9
        assert d["verdict"] == "proceed"
        assert d["level"] == "high"
        assert d["should_proceed"] is True
        assert d["reasons"] == ["Test reason"]

    def test_level_property(self):
        """Test level property calculation."""
        # High
        result = ConfidenceResult(score=0.95, verdict=Verdict.PROCEED, reasons=[])
        assert result.level == "high"

        # Medium
        result = ConfidenceResult(score=0.75, verdict=Verdict.PRESENT_ALTERNATIVES, reasons=[])
        assert result.level == "medium"

        # Low
        result = ConfidenceResult(score=0.6, verdict=Verdict.ASK_USER, reasons=[])
        assert result.level == "low"


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_check_confidence_function(self):
        """Test check_confidence convenience function."""
        result = check_confidence(
            has_official_docs=True,
            has_existing_patterns=True,
            has_clear_path=True,
        )
        assert isinstance(result, ConfidenceResult)
        assert result.score == 1.0
        assert result.should_proceed is True

    def test_get_confidence_checker_singleton(self):
        """Test that get_confidence_checker returns singleton."""
        checker1 = get_confidence_checker()
        checker2 = get_confidence_checker()
        assert checker1 is checker2


class TestGetRecommendation:
    """Test get_recommendation method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.checker = ConfidenceChecker()

    def test_high_recommendation(self):
        """Test high confidence recommendation."""
        rec = self.checker.get_recommendation(0.95)
        assert "High confidence" in rec
        assert "Proceed" in rec

    def test_medium_recommendation(self):
        """Test medium confidence recommendation."""
        rec = self.checker.get_recommendation(0.75)
        assert "Medium confidence" in rec
        assert "alternatives" in rec

    def test_low_recommendation(self):
        """Test low confidence recommendation."""
        rec = self.checker.get_recommendation(0.55)
        assert "Low confidence" in rec
        assert "clarifying" in rec

    def test_very_low_recommendation(self):
        """Test very low confidence recommendation."""
        rec = self.checker.get_recommendation(0.3)
        assert "Very low" in rec
        assert "STOP" in rec
