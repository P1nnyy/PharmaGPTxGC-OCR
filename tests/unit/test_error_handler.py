import json
from services.error_handler import ErrorType, classify_error


def test_timeout_classified_as_transient_retry_with_timeout_retryable():
    result = classify_error("Connection timeout during OCR request")

    assert result.error_type == ErrorType.TRANSIENT
    assert result.recovery_action == "retry_with_timeout"
    assert result.retryable is True


def test_low_ocr_confidence_classified_as_recoverable():
    result = classify_error("OCR confidence too low")

    assert result.error_type == ErrorType.RECOVERABLE
    assert result.recovery_action == "retry_with_high_dpi"
    assert result.retryable is False


def test_invalid_file_format_classified_as_fatal_reject_image():
    result = classify_error("Invalid file format: not an image")

    assert result.error_type == ErrorType.FATAL
    assert result.recovery_action == "reject_image"
    assert result.retryable is False


def test_corrupted_image_classified_as_fatal_reject_image():
    result = classify_error("Image corrupted; cannot identify image file")

    assert result.error_type == ErrorType.FATAL
    assert result.recovery_action == "reject_image"


def test_unknown_exception_classified_as_fatal_unknown_error():
    result = classify_error("Unexpected parser failure")

    assert result.error_type == ErrorType.FATAL
    assert result.recovery_action == "unknown_error"
    assert result.retryable is False


def test_exception_object_preserves_original_exception_type():
    exc = ValueError("semantic classification failed for main table")
    result = classify_error(exc, metadata={"invoice_id": "abc"})

    assert result.error_type == ErrorType.RECOVERABLE
    assert result.recovery_action == "continue_with_unknown_semantics"
    assert result.original_exception_type == "ValueError"
    assert result.metadata == {"invoice_id": "abc"}


def test_to_dict_is_json_serializable():
    result = classify_error(RuntimeError("temporarily unavailable"), stage="ocr").to_dict()

    encoded = json.dumps(result)
    decoded = json.loads(encoded)

    assert decoded["error_type"] == "TRANSIENT"
    assert decoded["recovery_action"] == "retry_with_timeout"
    assert decoded["original_exception_type"] == "RuntimeError"
