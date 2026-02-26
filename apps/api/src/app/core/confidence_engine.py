"""
Pre-implementation Confidence Check

Prevents wrong-direction execution by assessing confidence BEFORE starting.

Token Budget: 100-200 tokens
ROI: 25-250x token savings when stopping wrong direction

Confidence Levels:
    - High (>=90%): Proceed with implementation
    - Medium (70-89%): Present alternatives, recommend best
    - Low (<70%): STOP -> Ask user specific questions

Scoring System (base 0.5):
    - Positive indicators: +0.2 each (docs, patterns, clear path)
    - Minor blockers: -0.1 each (multiple approaches, trade-offs)
    - Serious blockers: -0.2 each (unclear requirements, no precedent, missing domain knowledge)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Verdict(str, Enum):
    """Action to take based on confidence level."""

    PROCEED = "proceed"  # High confidence (>=90%) - implement immediately
    PRESENT_ALTERNATIVES = "present_alternatives"  # Medium (70-89%) - show options
    ASK_USER = "ask_user"  # Low (<70%) - ask clarifying questions
    STOP = "stop"  # Very low (<50%) - stop and investigate


@dataclass
class ConfidenceInput:
    """Input for confidence assessment.

    Positive indicators (each adds +0.2):
        - has_official_docs: Official documentation has been reviewed
        - has_existing_patterns: Existing codebase patterns identified
        - has_clear_path: Clear implementation path exists

    Minor blockers (each subtracts -0.1):
        - multiple_approaches: Multiple viable approaches exist
        - has_trade_offs: Trade-offs require consideration

    Serious blockers (each subtracts -0.2):
        - unclear_requirements: Requirements are vague or incomplete
        - no_precedent: No similar implementations to reference
        - missing_domain_knowledge: Domain expertise is lacking
    """

    # Positive indicators (+0.2 each)
    has_official_docs: bool = False
    has_existing_patterns: bool = False
    has_clear_path: bool = False

    # Minor blockers (-0.1 each)
    multiple_approaches: bool = False
    has_trade_offs: bool = False

    # Serious blockers (-0.2 each)
    unclear_requirements: bool = False
    no_precedent: bool = False
    missing_domain_knowledge: bool = False

    # Optional context
    task: str = ""


@dataclass
class ConfidenceResult:
    """Result of confidence assessment.

    Attributes:
        score: Confidence score (0.0 - 1.0)
        verdict: Recommended action (proceed/present_alternatives/ask_user/stop)
        reasons: List of evidence strings explaining the score
        questions: Clarifying questions (only for low confidence)
        signals: Raw signal values for debugging
    """

    score: float
    verdict: Verdict
    reasons: List[str]
    questions: Optional[List[str]] = None
    signals: Dict[str, Any] = field(default_factory=dict)

    @property
    def should_proceed(self) -> bool:
        """Returns True if confidence is high enough to proceed."""
        return self.verdict == Verdict.PROCEED

    @property
    def level(self) -> str:
        """Returns confidence level as string (high/medium/low)."""
        if self.score >= 0.9:
            return "high"
        elif self.score >= 0.7:
            return "medium"
        else:
            return "low"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "score": self.score,
            "verdict": self.verdict.value,
            "level": self.level,
            "should_proceed": self.should_proceed,
            "reasons": self.reasons,
            "questions": self.questions,
            "signals": self.signals,
        }


class ConfidenceChecker:
    """
    Pre-implementation confidence assessment.

    Usage:
        checker = ConfidenceChecker()
        result = checker.assess(ConfidenceInput(
            has_official_docs=True,
            has_existing_patterns=True,
            has_clear_path=True,
        ))

        if result.should_proceed:
            # High confidence - implement immediately
        elif result.verdict == Verdict.PRESENT_ALTERNATIVES:
            # Medium confidence - present options to user
        else:
            # Low confidence - ask clarifying questions
            for q in result.questions:
                print(q)
    """

    # Scoring weights
    POSITIVE_WEIGHT = 0.2  # Per positive indicator
    MINOR_BLOCKER_WEIGHT = 0.1  # Per minor blocker
    SERIOUS_BLOCKER_WEIGHT = 0.2  # Per serious blocker
    BASELINE_SCORE = 0.5  # Starting point

    # Thresholds
    HIGH_THRESHOLD = 0.9
    MEDIUM_THRESHOLD = 0.7
    LOW_THRESHOLD = 0.5

    def assess(self, input: ConfidenceInput) -> ConfidenceResult:
        """
        Assess confidence level based on implementation context.

        Scoring system (starting from 0.5 baseline):
        - Positive indicators: +0.2 each (max +0.6)
        - Minor blockers: -0.1 each (max -0.2)
        - Serious blockers: -0.2 each (max -0.6)

        Final score is clamped to [0.0, 1.0] range.

        Args:
            input: ConfidenceInput with assessment signals

        Returns:
            ConfidenceResult with score, verdict, reasons, and questions
        """
        score = self.BASELINE_SCORE
        reasons: List[str] = []
        signals: Dict[str, Any] = {}

        # Positive indicators (+0.2 each)
        if input.has_official_docs:
            score += self.POSITIVE_WEIGHT
            reasons.append("Official documentation reviewed")
            signals["has_official_docs"] = True
        else:
            signals["has_official_docs"] = False

        if input.has_existing_patterns:
            score += self.POSITIVE_WEIGHT
            reasons.append("Existing codebase patterns identified")
            signals["has_existing_patterns"] = True
        else:
            signals["has_existing_patterns"] = False

        if input.has_clear_path:
            score += self.POSITIVE_WEIGHT
            reasons.append("Clear implementation path")
            signals["has_clear_path"] = True
        else:
            signals["has_clear_path"] = False

        # Minor blockers (-0.1 each)
        if input.multiple_approaches:
            score -= self.MINOR_BLOCKER_WEIGHT
            reasons.append("Multiple viable approaches exist")
            signals["multiple_approaches"] = True
        else:
            signals["multiple_approaches"] = False

        if input.has_trade_offs:
            score -= self.MINOR_BLOCKER_WEIGHT
            reasons.append("Trade-offs require consideration")
            signals["has_trade_offs"] = True
        else:
            signals["has_trade_offs"] = False

        # Serious blockers (-0.2 each)
        if input.unclear_requirements:
            score -= self.SERIOUS_BLOCKER_WEIGHT
            reasons.append("Unclear requirements")
            signals["unclear_requirements"] = True
        else:
            signals["unclear_requirements"] = False

        if input.no_precedent:
            score -= self.SERIOUS_BLOCKER_WEIGHT
            reasons.append("No clear precedent")
            signals["no_precedent"] = True
        else:
            signals["no_precedent"] = False

        if input.missing_domain_knowledge:
            score -= self.SERIOUS_BLOCKER_WEIGHT
            reasons.append("Missing domain knowledge")
            signals["missing_domain_knowledge"] = True
        else:
            signals["missing_domain_knowledge"] = False

        # Clamp score to [0.0, 1.0] and round
        score = max(0.0, min(1.0, score))
        score = round(score, 2)

        # Determine verdict
        verdict = self._determine_verdict(score)

        # Generate questions for low confidence
        questions = None
        if verdict in (Verdict.ASK_USER, Verdict.STOP):
            questions = self._generate_questions(input)

        return ConfidenceResult(
            score=score,
            verdict=verdict,
            reasons=reasons,
            questions=questions,
            signals=signals,
        )

    def _determine_verdict(self, score: float) -> Verdict:
        """Determine verdict based on score."""
        if score >= self.HIGH_THRESHOLD:
            return Verdict.PROCEED
        elif score >= self.MEDIUM_THRESHOLD:
            return Verdict.PRESENT_ALTERNATIVES
        elif score >= self.LOW_THRESHOLD:
            return Verdict.ASK_USER
        else:
            return Verdict.STOP

    def _generate_questions(self, input: ConfidenceInput) -> List[str]:
        """Generate clarifying questions based on blockers."""
        questions: List[str] = []

        if input.unclear_requirements:
            questions.append(
                "What are the specific requirements for this feature?"
            )

        if input.no_precedent:
            questions.append(
                "Are there any similar implementations we can reference?"
            )

        if input.missing_domain_knowledge:
            questions.append(
                "What domain-specific constraints should I consider?"
            )

        # If no specific blockers but still low confidence, add generic question
        if not questions:
            questions.append(
                "Can you provide more context about the expected behavior?"
            )

        return questions

    def get_recommendation(self, score: float) -> str:
        """
        Get human-readable recommendation based on score.

        Args:
            score: Confidence score (0.0 - 1.0)

        Returns:
            Human-readable recommendation string
        """
        if score >= self.HIGH_THRESHOLD:
            return "High confidence (>=90%) - Proceed with implementation"
        elif score >= self.MEDIUM_THRESHOLD:
            return "Medium confidence (70-89%) - Present alternatives, recommend best"
        elif score >= self.LOW_THRESHOLD:
            return "Low confidence (50-69%) - Ask clarifying questions before proceeding"
        else:
            return "Very low confidence (<50%) - STOP and investigate further"


# Convenience function for simple usage
def check_confidence(
    has_official_docs: bool = False,
    has_existing_patterns: bool = False,
    has_clear_path: bool = False,
    multiple_approaches: bool = False,
    has_trade_offs: bool = False,
    unclear_requirements: bool = False,
    no_precedent: bool = False,
    missing_domain_knowledge: bool = False,
    task: str = "",
) -> ConfidenceResult:
    """
    Quick confidence check with keyword arguments.

    Example:
        result = check_confidence(
            has_official_docs=True,
            has_existing_patterns=True,
            has_clear_path=True,
        )
        if result.should_proceed:
            print("Ready to implement!")
    """
    checker = ConfidenceChecker()
    return checker.assess(
        ConfidenceInput(
            has_official_docs=has_official_docs,
            has_existing_patterns=has_existing_patterns,
            has_clear_path=has_clear_path,
            multiple_approaches=multiple_approaches,
            has_trade_offs=has_trade_offs,
            unclear_requirements=unclear_requirements,
            no_precedent=no_precedent,
            missing_domain_knowledge=missing_domain_knowledge,
            task=task,
        )
    )


# Global singleton for reuse
_confidence_checker: Optional[ConfidenceChecker] = None


def get_confidence_checker() -> ConfidenceChecker:
    """Get the global ConfidenceChecker instance."""
    global _confidence_checker
    if _confidence_checker is None:
        _confidence_checker = ConfidenceChecker()
    return _confidence_checker
