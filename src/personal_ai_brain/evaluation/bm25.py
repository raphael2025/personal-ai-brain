"""Small dependency-free BM25 retrieval baseline with explicit metadata filters.

This is an evaluation adapter, not yet a persistent production search service.
Document IDs are stable source references (for the synthetic corpus, relative paths).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize Unicode text into case-folded word tokens."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return tuple(_TOKEN_RE.findall(text.casefold()))


@dataclass(frozen=True, slots=True)
class SearchDocument:
    doc_id: str
    text: str
    root_id: str | None = None
    document_type: str | None = None
    modified_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.doc_id, str) or not self.doc_id.strip():
            raise ValueError("doc_id must be a non-empty string")
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")
        for name in ("root_id", "document_type"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be None or a non-empty string")
        if self.modified_at is not None and not isinstance(self.modified_at, datetime):
            raise ValueError("modified_at must be a datetime or None")


@dataclass(frozen=True, slots=True)
class SearchFilters:
    root_id: str | None = None
    document_type: str | None = None
    modified_after: datetime | None = None
    modified_before: datetime | None = None

    def __post_init__(self) -> None:
        if self.modified_after and self.modified_before:
            if self.modified_after > self.modified_before:
                raise ValueError("modified_after must not be later than modified_before")


@dataclass(frozen=True, slots=True)
class SearchHit:
    document: SearchDocument
    score: float


class BM25Index:
    """Immutable in-memory BM25 index.

    Uses Robertson-style positive IDF, k1=1.5 and b=0.75 by default.
    Ties are resolved by doc_id so runs are deterministic.
    """

    def __init__(
        self,
        documents: list[SearchDocument] | tuple[SearchDocument, ...],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if not math.isfinite(k1) or k1 <= 0:
            raise ValueError("k1 must be a finite positive number")
        if not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        self.k1 = float(k1)
        self.b = float(b)
        self.documents = tuple(documents)
        ids = [document.doc_id for document in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document IDs must be unique")
        self._tokens = tuple(tokenize(document.text) for document in self.documents)
        self._lengths = tuple(len(tokens) for tokens in self._tokens)
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        frequencies: dict[str, int] = {}
        for tokens in self._tokens:
            for term in set(tokens):
                frequencies[term] = frequencies.get(term, 0) + 1
        self._document_frequency = frequencies

    def _matches(self, document: SearchDocument, filters: SearchFilters | None) -> bool:
        if filters is None:
            return True
        if filters.root_id is not None and document.root_id != filters.root_id:
            return False
        if (
            filters.document_type is not None
            and (document.document_type or "").casefold()
            != filters.document_type.casefold()
        ):
            return False
        if filters.modified_after is not None:
            if document.modified_at is None or document.modified_at < filters.modified_after:
                return False
        if filters.modified_before is not None:
            if document.modified_at is None or document.modified_at > filters.modified_before:
                return False
        return True

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[SearchHit]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        query_terms = tokenize(query)
        if not query_terms or not self.documents:
            return []

        hits: list[SearchHit] = []
        count = len(self.documents)
        for index, document in enumerate(self.documents):
            if not self._matches(document, filters):
                continue
            term_counts: dict[str, int] = {}
            for term in self._tokens[index]:
                term_counts[term] = term_counts.get(term, 0) + 1
            length = self._lengths[index]
            score = 0.0
            for term in query_terms:
                frequency = term_counts.get(term, 0)
                if frequency == 0:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_frequency = math.log(
                    1.0 + (count - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = frequency + self.k1 * (
                    1.0 - self.b
                    + self.b * (length / self._average_length if self._average_length else 0.0)
                )
                score += inverse_frequency * (
                    frequency * (self.k1 + 1.0) / denominator
                )
            if score > 0:
                hits.append(SearchHit(document=document, score=score))

        hits.sort(key=lambda hit: (-hit.score, hit.document.doc_id))
        return hits[:limit]
