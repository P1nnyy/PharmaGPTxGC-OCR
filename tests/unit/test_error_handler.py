import json

from services.error_handler import ErrorType, classify_error


def test_cuda_oom_classified_as_transient_reduce_batch_size_retryable():
    result = classify_error("CUDA out of memory while running OCR", stage="ocr")

    assert result.error_type == ErrorType.TRANSIENT
    assert result.recovery_action == "reduce_batch_size"
    assert result.retryable is True
    assert result.stage == "ocr"


def test_timeout_classified_as_transient_retry_with_timeout_retryable():
    result = classify_error("Connection timeout during OCR request")

    assert result.error_type == ErrorType.TRANSIENT
    assert result.recovery_action == "retry_with_timeout"
    assert result.retryable is True


def test_ppstructure_zero_cells_classified_as_recoverable_use_heuristic_tsr():
    result = classify_error("PPStructure returned 0 cells for invoice")

    assert result.error_type == ErrorType.RECOVERABLE
    assert result.recovery_action == "use_heuristic_tsr"
    assert result.retryable is False


def test_token_mapping_failed_classified_as_recoverable_use_graph_fallback():
    result = classify_error("Token mapping failed after IoA assignment")

    assert result.error_type == ErrorType.RECOVERABLE
    assert result.recovery_action == "use_graph_fallback"


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
    exc = ValueError("topology validation failed for main table")
    result = classify_error(exc, metadata={"invoice_id": "abc"})

    assert result.error_type == ErrorType.RECOVERABLE
    assert result.recovery_action == "use_graph_fallback"
    assert result.original_exception_type == "ValueError"
    assert result.metadata == {"invoice_id": "abc"}


def test_to_dict_is_json_serializable():
    result = classify_error(RuntimeError("temporarily unavailable"), stage="ocr").to_dict()

    encoded = json.dumps(result)
    decoded = json.loads(encoded)

    assert decoded["error_type"] == "TRANSIENT"
    assert decoded["recovery_action"] == "retry_with_timeout"
    assert decoded["original_exception_type"] == "RuntimeError"
