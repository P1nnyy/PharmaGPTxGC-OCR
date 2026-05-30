import json
from dataclasses import dataclass
from types import SimpleNamespace

from services.layout_pipeline.token_validator import TokenMappingValidator


@dataclass
class ObjectToken:
    id: str
    text: str
    confidence: float = 0.9
    geometry: dict = None


def test_full_coverage_when_all_tokens_are_mapped():
    tokens = [
        {"id": "t1", "text": "GST"},
        {"id": "t2", "text": "100.00"},
    ]
    assignments = {"cells": [{"mapped_block_ids": ["t1", "t2"]}]}

    report = TokenMappingValidator().validate(tokens, assignments)

    assert report.total_tokens == 2
    assert report.mapped_tokens == 2
    assert report.unmapped_tokens == 0
    assert report.coverage_percentage == 100.0
    assert report.orphan_count == 0
    assert report.passed is True


def test_partial_coverage_reports_orphan_tokens():
    tokens = [
        {"id": "t1", "text": "GST", "confidence": 0.91, "geometry": {"min_x": 1}},
        {"id": "t2", "text": "ROUND", "confidence": 0.72, "bbox": [1, 2, 3, 4]},
        {"id": "t3", "text": "TOTAL"},
    ]
    assignments = {"cells": [{"mapped_block_ids": ["t1"]}]}

    report = TokenMappingValidator(threshold=95.0).validate(tokens, assignments)

    assert report.mapped_tokens == 1
    assert report.unmapped_tokens == 2
    assert report.coverage_percentage == 33.33
    assert report.orphan_count == 2
    assert report.passed is False
    assert report.orphan_tokens[0]["text"] == "ROUND"
    assert report.orphan_tokens[0]["confidence"] == 0.72
    assert report.orphan_tokens[0]["bbox"] == [1, 2, 3, 4]


def test_zero_tokens_input_passes_with_100_percent_coverage():
    report = TokenMappingValidator().validate([], {"cells": []})

    assert report.total_tokens == 0
    assert report.mapped_tokens == 0
    assert report.unmapped_tokens == 0
    assert report.coverage_percentage == 100.0
    assert report.passed is True


def test_dict_style_tokens_and_direct_assignment_mapping():
    tokens = [
        {"block_id": "b1", "text": "A"},
        {"block_id": "b2", "text": "B"},
    ]
    assignments = {"b1": "row_1_col_1", "b2": "row_1_col_2"}

    report = TokenMappingValidator().validate(tokens, assignments)

    assert report.mapped_tokens == 2
    assert report.orphan_tokens == []


def test_object_style_tokens_and_cell_assignments():
    tokens = [
        ObjectToken(id="o1", text="Alpha", geometry={"min_x": 0, "max_x": 10}),
        ObjectToken(id="o2", text="Beta"),
    ]
    assignments = [SimpleNamespace(mapped_block_ids=["o1"])]

    report = TokenMappingValidator(threshold=0.95).validate(tokens, assignments)

    assert report.threshold == 95.0
    assert report.mapped_tokens == 1
    assert report.orphan_tokens == [{"text": "Beta", "id": "o2", "confidence": 0.9}]


def test_missing_confidence_and_geometry_do_not_crash():
    tokens = [SimpleNamespace(id="x1", text="Loose")]
    assignments = []

    report = TokenMappingValidator().validate(tokens, assignments)

    assert report.orphan_count == 1
    assert report.orphan_tokens[0] == {"text": "Loose", "id": "x1"}


def test_report_is_json_serializable():
    tokens = [{"id": "t1", "text": "GST", "polygon": [(1, 2), (3, 4)]}]
    report = TokenMappingValidator().validate(tokens, [])

    payload = report.to_dict()
    encoded = json.dumps(payload)

    assert json.loads(encoded)["orphan_tokens"][0]["polygon"] == [[1, 2], [3, 4]]
    assert "timestamp" in payload
