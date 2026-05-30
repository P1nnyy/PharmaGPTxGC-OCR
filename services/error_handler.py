from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field


class ErrorType(str, Enum):
    TRANSIENT = "TRANSIENT"
    RECOVERABLE = "RECOVERABLE"
    FATAL = "FATAL"


class ErrorClassification(BaseModel):
    error_type: ErrorType
    recovery_action: str
    message: str
    original_exception_type: Optional[str] = None
    retryable: bool
    stage: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class ErrorClassifier:
    """Classify OCR pipeline failures into actionable reliability categories."""

    TRANSIENT_RULES = (
        (("cuda out of memory", "out of memory", "gpu memory"), "reduce_batch_size"),
        (("timeout", "timed out", "connection timeout"), "retry_with_timeout"),
        (("temporarily unavailable", "connection reset"), "retry_with_timeout"),
    )
    RECOVERABLE_RULES = (
        (("ppstructure returned 0 cells", "pp-structure returned 0 cells", "ppstructure 0 cells"), "use_heuristic_tsr"),
        (("tsr returned 0 cells", "0 cells", "zero cells"), "use_heuristic_tsr"),
        (("ocr confidence too low", "low ocr confidence"), "upscale_and_retry"),
        (("token mapping failed", "token coverage failure", "token coverage failed"), "use_graph_fallback"),
        (("topology validation failed",), "use_graph_fallback"),
        (("semantic classification failed",), "continue_with_unknown_semantics"),
    )
    FATAL_RULES = (
        (("invalid file format", "cannot identify image file", "image corrupted", "corrupted image", "unsupported image"), "reject_image"),
        (("validation failed", "missing required input", "permission denied"), "reject_image"),
    )

    def __init__(self, default_error_type: ErrorType = ErrorType.FATAL, default_recovery_action: str = "unknown_error"):
        self.default_error_type = default_error_type
        self.default_recovery_action = default_recovery_action

    def classify(
        self,
        error: Union[Exception, str],
        stage: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ErrorClassification:
        message = str(error)
        original_exception_type = type(error).__name__ if isinstance(error, Exception) else None
        normalized = message.lower()

        for patterns, action in self.TRANSIENT_RULES:
            if any(pattern in normalized for pattern in patterns):
                return ErrorClassification(
                    error_type=ErrorType.TRANSIENT,
                    recovery_action=action,
                    message=message,
                    original_exception_type=original_exception_type,
                    retryable=True,
                    stage=stage,
                    metadata=metadata or {},
                )

        for patterns, action in self.RECOVERABLE_RULES:
            if any(pattern in normalized for pattern in patterns):
                return ErrorClassification(
                    error_type=ErrorType.RECOVERABLE,
                    recovery_action=action,
                    message=message,
                    original_exception_type=original_exception_type,
                    retryable=False,
                    stage=stage,
                    metadata=metadata or {},
                )

        for patterns, action in self.FATAL_RULES:
            if any(pattern in normalized for pattern in patterns):
                return ErrorClassification(
                    error_type=ErrorType.FATAL,
                    recovery_action=action,
                    message=message,
                    original_exception_type=original_exception_type,
                    retryable=False,
                    stage=stage,
                    metadata=metadata or {},
                )

        return ErrorClassification(
            error_type=self.default_error_type,
            recovery_action=self.default_recovery_action,
            message=message,
            original_exception_type=original_exception_type,
            retryable=self.default_error_type == ErrorType.TRANSIENT,
            stage=stage,
            metadata=metadata or {},
        )


def classify_error(
    error: Union[Exception, str],
    stage: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    default_error_type: ErrorType = ErrorType.FATAL,
) -> ErrorClassification:
    return ErrorClassifier(default_error_type=default_error_type).classify(
        error,
        stage=stage,
        metadata=metadata,
    )
