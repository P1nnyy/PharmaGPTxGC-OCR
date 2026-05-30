import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from pydantic import BaseModel, Field

from core.logger import logger


class TokenCoverageReport(BaseModel):
    """JSON-serializable token-to-cell assignment coverage report."""

    total_tokens: int
    mapped_tokens: int
    unmapped_tokens: int
    coverage_percentage: float
    orphan_count: int
    orphan_tokens: List[Dict[str, Any]] = Field(default_factory=list)
    threshold: float
    passed: bool
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class TokenCoverageError(ValueError):
    """Kept for backwards-compatible imports; validation is diagnostic by default."""


class TokenMappingValidator:
    """Compute OCR token-to-cell assignment coverage after IoA mapping."""

    _ID_FIELDS = ("id", "token_id", "block_id")
    _GEOMETRY_FIELDS = ("geometry", "normalized_geometry", "original_geometry", "bbox", "bounding_box")
    _ASSIGNMENT_FIELDS = (
        "mapped_block_ids",
        "mapped_token_ids",
        "token_ids",
        "block_ids",
        "tokens",
        "blocks",
        "assigned_tokens",
        "mapped_tokens",
    )

    def __init__(self, threshold: float = 95.0, orphan_log_sample_size: int = 5):
        self.threshold = self._normalize_threshold(threshold)
        self.orphan_log_sample_size = max(0, int(orphan_log_sample_size))

    def validate(self, tokens: Iterable[Any], assignments: Any = None) -> TokenCoverageReport:
        token_list = list(tokens or [])
        token_keys = [self._canonical_token_key(token, idx) for idx, token in enumerate(token_list)]
        lookup = self._build_lookup(token_list, token_keys)

        mapped_keys = self._mapped_token_keys(assignments, lookup)
        mapped_count = len(set(token_keys) & mapped_keys)
        total_tokens = len(token_list)
        unmapped_count = max(0, total_tokens - mapped_count)
        coverage = round((mapped_count / total_tokens * 100.0) if total_tokens else 100.0, 2)

        orphan_tokens = [
            self._orphan_token_dict(token, idx)
            for idx, (token, key) in enumerate(zip(token_list, token_keys))
            if key not in mapped_keys
        ]

        report = TokenCoverageReport(
            total_tokens=total_tokens,
            mapped_tokens=mapped_count,
            unmapped_tokens=unmapped_count,
            coverage_percentage=coverage,
            orphan_count=len(orphan_tokens),
            orphan_tokens=orphan_tokens,
            threshold=self.threshold,
            passed=coverage >= self.threshold,
        )

        logger.info(
            "[TOKEN COVERAGE] total_tokens=%s mapped_tokens=%s unmapped_tokens=%s coverage_percentage=%.2f threshold=%.2f passed=%s",
            report.total_tokens,
            report.mapped_tokens,
            report.unmapped_tokens,
            report.coverage_percentage,
            report.threshold,
            report.passed,
        )
        if not report.passed:
            logger.warning(
                "[TOKEN COVERAGE] coverage below threshold: coverage=%.2f threshold=%.2f orphan_sample=%s",
                report.coverage_percentage,
                report.threshold,
                report.orphan_tokens[: self.orphan_log_sample_size],
            )

        return report

    @staticmethod
    def _normalize_threshold(threshold: float) -> float:
        value = float(threshold)
        if 0.0 <= value <= 1.0:
            return round(value * 100.0, 4)
        return value

    def _build_lookup(self, tokens: List[Any], token_keys: List[str]) -> Dict[Any, str]:
        lookup: Dict[Any, str] = {}
        for idx, token in enumerate(tokens):
            canonical = token_keys[idx]
            lookup[canonical] = canonical
            lookup[idx] = canonical
            lookup[str(idx)] = canonical
            lookup[id(token)] = canonical
            for field_name in self._ID_FIELDS:
                value = self._get_value(token, field_name)
                if value is not None:
                    try:
                        lookup[value] = canonical
                    except TypeError:
                        pass
                    lookup[str(value)] = canonical
        return lookup

    def _canonical_token_key(self, token: Any, index: int) -> str:
        for field_name in self._ID_FIELDS:
            value = self._get_value(token, field_name)
            if value is not None:
                return f"id:{value}"
        return f"index:{index}"

    def _mapped_token_keys(self, assignments: Any, lookup: Dict[Any, str]) -> Set[str]:
        mapped: Set[str] = set()
        self._collect_mapped_refs(assignments, lookup, mapped)
        return mapped

    def _collect_mapped_refs(self, value: Any, lookup: Dict[Any, str], mapped: Set[str]) -> None:
        if value is None:
            return

        resolved = self._resolve_ref(value, lookup)
        if resolved is not None:
            mapped.add(resolved)
            return

        if isinstance(value, dict):
            direct_key_matches = [lookup[key] for key in value.keys() if key in lookup]
            if direct_key_matches:
                mapped.update(direct_key_matches)
                return
            for field_name in self._ASSIGNMENT_FIELDS:
                if field_name in value:
                    self._collect_mapped_refs(value.get(field_name), lookup, mapped)
            for nested_key in ("cells", "tables", "regions", "assignments"):
                if nested_key in value:
                    self._collect_mapped_refs(value.get(nested_key), lookup, mapped)
            return

        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._collect_mapped_refs(item, lookup, mapped)
            return

        for field_name in self._ASSIGNMENT_FIELDS:
            field_value = self._get_value(value, field_name)
            if field_value is not None:
                self._collect_mapped_refs(field_value, lookup, mapped)
        cells = self._get_value(value, "cells")
        if cells is not None:
            self._collect_mapped_refs(cells, lookup, mapped)

    def _resolve_ref(self, value: Any, lookup: Dict[Any, str]) -> Optional[str]:
        try:
            if value in lookup:
                return lookup[value]
        except TypeError:
            pass
        if isinstance(value, (str, int, float)) and str(value) in lookup:
            return lookup[str(value)]

        for field_name in self._ID_FIELDS:
            ref = self._get_value(value, field_name)
            try:
                if ref in lookup:
                    return lookup[ref]
            except TypeError:
                pass
            if ref is not None and str(ref) in lookup:
                return lookup[str(ref)]

        object_id = id(value)
        return lookup.get(object_id)

    def _orphan_token_dict(self, token: Any, index: int) -> Dict[str, Any]:
        orphan: Dict[str, Any] = {
            "text": self._get_value(token, "text") or self._get_value(token, "raw_text") or "",
        }

        for field_name in self._ID_FIELDS:
            value = self._get_value(token, field_name)
            if value is not None:
                orphan[field_name] = self._json_safe(value)

        confidence = self._get_value(token, "confidence")
        if confidence is not None:
            orphan["confidence"] = self._json_safe(confidence)

        for field_name in self._GEOMETRY_FIELDS:
            geometry = self._get_value(token, field_name)
            if geometry is not None:
                output_name = "bbox" if field_name in {"bbox", "bounding_box"} else "geometry"
                orphan[output_name] = self._json_safe(geometry)
                break

        polygon = self._get_value(token, "polygon")
        if polygon:
            orphan["polygon"] = self._json_safe(polygon)

        if not any(field_name in orphan for field_name in self._ID_FIELDS):
            orphan["index"] = index

        return orphan

    @staticmethod
    def _get_value(obj: Any, field_name: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(field_name)
        return getattr(obj, field_name, None)

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if is_dataclass(value):
            return self._json_safe(asdict(value))
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(v) for v in value]
        if hasattr(value, "__dict__"):
            return {
                key: self._json_safe(val)
                for key, val in vars(value).items()
                if not key.startswith("_")
            }
        return str(value)
