from app.domain import ParseReport, ParseStatus, QualityWarning
from app.observability import get_logger

logger = get_logger(__name__)


class ParseQualityGate:
    """Evaluates parse quality and decides whether parsed output can be trusted for indexing.

    PR-0: Interface + default implementation.
    PR-1+: Full scoring with thresholds per warning type.
    """

    MIN_QUALITY_SCORE = 0.3
    CRITICAL_WARNINGS = {
        QualityWarning.OCR_NEEDED,
        QualityWarning.EMPTY_PAGE,
        QualityWarning.PAGE_NUMBER_POLLUTION,
        QualityWarning.LOW_CLAUSE_RECOGNITION,
        QualityWarning.TABLE_CANDIDATE,
    }

    def evaluate(self, report: ParseReport) -> bool:
        """Return True if the parsed output passes quality gate and can be indexed."""
        if report.parse_status == ParseStatus.FAILED:
            logger.warning("quality_gate_rejected", extra={"extra_fields": {"reason": "parse_failed"}})
            return False

        if report.quality_score < self.MIN_QUALITY_SCORE:
            logger.warning(
                "quality_gate_rejected",
                extra={"extra_fields": {"reason": "low_quality_score", "score": report.quality_score}},
            )
            return False

        for warning in report.warnings:
            if warning in self.CRITICAL_WARNINGS:
                logger.warning(
                    "quality_gate_rejected",
                    extra={"extra_fields": {"reason": f"critical_warning_{warning}"}},
                )
                return False

        return True

    def needs_manual_review(self, report: ParseReport) -> list[str]:
        """Return warnings that suggest manual review is needed."""
        if report.quality_score < self.MIN_QUALITY_SCORE:
            return ["quality_below_threshold"]
        if report.needs_ocr:
            return ["ocr_needed"]
        return []
