"""Early persistent lexical search over versioned extraction artifacts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from personal_ai_brain.evaluation.bm25 import BM25Index, SearchDocument, SearchFilters, tokenize


class SearchCorpusTooLargeError(RuntimeError):
    """The in-memory lexical adapter refuses to silently truncate its corpus."""


@dataclass(frozen=True, slots=True)
class SearchEvidence:
    asset_id: str
    asset_version_id: str
    root_id: str
    relative_path: str
    source_sha256: str
    media_type: str | None
    modified_at: datetime | None
    score: float
    snippet: str


def _snippet(text: str, query: str, *, max_chars: int = 240) -> str:
    folded = text.casefold()
    positions = [folded.find(term) for term in tokenize(query)]
    positions = [position for position in positions if position >= 0]
    match_position = min(positions, default=0)
    start = max(0, match_position - max_chars // 3)
    end = min(len(text), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    snippet = text[start:end].strip()
    if start:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return snippet


class PostgresLexicalSearchRepository:
    """Build a bounded in-memory BM25 index from persisted current text artifacts.

    This is the first persistent-data adapter, not a scalable inverted-index
    service. It fails explicitly when the selected corpus exceeds max_documents
    rather than returning results from an undocumented partial corpus.
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        max_documents: int = 5000,
        close_connections: bool = True,
    ) -> None:
        if type(max_documents) is not int or max_documents <= 0:
            raise ValueError("max_documents must be a positive integer")
        self._connect = connection_factory
        self.max_documents = max_documents
        self._close_connections = close_connections

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            with connection.transaction():
                yield connection
        finally:
            if self._close_connections:
                connection.close()

    @staticmethod
    def _optional_datetime(value: datetime | None, field_name: str) -> None:
        if value is not None and (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(f"{field_name} must be a timezone-aware datetime")

    def search(
        self,
        query: str,
        *,
        root_id: str | None = None,
        document_type: str | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        limit: int = 10,
    ) -> list[SearchEvidence]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        root_uuid = None
        if root_id is not None:
            try:
                root_uuid = UUID(root_id)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("root_id must be a UUID string") from exc
        if document_type is not None:
            if not isinstance(document_type, str) or not document_type.strip():
                raise ValueError("document_type must be a non-empty string")
            document_type = document_type.strip().casefold().lstrip(".")
        self._optional_datetime(modified_after, "modified_after")
        self._optional_datetime(modified_before, "modified_before")
        filters = SearchFilters(
            root_id=str(root_uuid) if root_uuid else None,
            document_type=document_type,
            modified_after=modified_after,
            modified_before=modified_before,
        )
        if not tokenize(query):
            return []

        with self._connection() as connection:
            rows = connection.execute(
                """
                WITH current_text AS (
                    SELECT DISTINCT ON (
                        p.asset_version_id, l.storage_root_id, l.relative_path
                    )
                        a.id AS asset_id,
                        v.id AS asset_version_id,
                        l.storage_root_id AS root_id,
                        l.relative_path,
                        v.sha256 AS source_sha256,
                        v.detected_mime_type AS media_type,
                        v.observed_modified_at AS modified_at,
                        p.payload ->> 'text' AS extracted_text
                    FROM processing_artifacts AS p
                    JOIN asset_versions AS v ON v.id = p.asset_version_id
                    JOIN assets AS a ON a.id = v.asset_id
                    JOIN asset_locations AS l
                      ON l.asset_id = a.id
                     AND l.current_version_id = v.id
                     AND l.valid_to IS NULL
                     AND l.availability = 'available'
                    WHERE p.artifact_type = 'extracted_text'
                      AND p.status = 'ready'
                      AND p.payload IS NOT NULL
                      AND jsonb_typeof(p.payload -> 'text') = 'string'
                      AND (%s::uuid IS NULL OR l.storage_root_id = %s::uuid)
                      AND (
                          %s::text IS NULL
                          OR lower(substring(l.relative_path FROM '\\.([^./]+)$')) = %s::text
                      )
                      AND (
                          %s::timestamptz IS NULL
                          OR v.observed_modified_at >= %s::timestamptz
                      )
                      AND (
                          %s::timestamptz IS NULL
                          OR v.observed_modified_at <= %s::timestamptz
                      )
                    ORDER BY
                        p.asset_version_id, l.storage_root_id, l.relative_path,
                        p.created_at DESC, p.id DESC
                )
                SELECT asset_id, asset_version_id, root_id, relative_path,
                       source_sha256, media_type, modified_at, extracted_text
                  FROM current_text
                 ORDER BY root_id, relative_path, asset_version_id
                 LIMIT %s
                """,
                (
                    root_uuid, root_uuid,
                    document_type, document_type,
                    modified_after, modified_after,
                    modified_before, modified_before,
                    self.max_documents + 1,
                ),
            ).fetchall()

        if len(rows) > self.max_documents:
            raise SearchCorpusTooLargeError(
                f"selected corpus exceeds the in-memory limit of {self.max_documents} documents"
            )

        documents: list[SearchDocument] = []
        evidence_by_id: dict[str, tuple[Any, ...]] = {}
        for row in rows:
            asset_id, version_id, source_root_id, relative_path = row[:4]
            text = row[7]
            if not isinstance(text, str):
                raise ValueError("persisted extracted_text artifact has no text payload")
            source_root_id = str(source_root_id)
            version_id = str(version_id)
            doc_id = f"{version_id}:{source_root_id}:{relative_path}"
            suffix = PurePosixPath(relative_path).suffix.casefold().lstrip(".") or "unknown"
            documents.append(
                SearchDocument(
                    doc_id=doc_id,
                    text=text,
                    root_id=source_root_id,
                    document_type=suffix,
                    modified_at=row[6],
                )
            )
            evidence_by_id[doc_id] = row

        index = BM25Index(documents)
        hits = index.search(query, limit=limit, filters=filters)
        results: list[SearchEvidence] = []
        for hit in hits:
            row = evidence_by_id[hit.document.doc_id]
            results.append(
                SearchEvidence(
                    asset_id=str(row[0]),
                    asset_version_id=str(row[1]),
                    root_id=str(row[2]),
                    relative_path=row[3],
                    source_sha256=str(row[4]).strip(),
                    media_type=row[5],
                    modified_at=row[6],
                    score=hit.score,
                    snippet=_snippet(hit.document.text, query),
                )
            )
        return results
