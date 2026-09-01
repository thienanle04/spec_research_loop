"""Federated scholarly retrieval across independent provider adapters."""

import asyncio

from app.modules.research.ports import (
    BatchScholarlySourcePort,
    CitationGraphPort,
    MultiQueryScholarlySourcePort,
    ScholarlyProviderError,
    ScholarlyRecord,
    ScholarlySourcePort,
    SourcePreferences,
)


class CompositeScholarlySource:
    """Fan out discovery while allowing partial provider failures."""

    def __init__(self, sources: list[ScholarlySourcePort]) -> None:
        if not sources:
            raise ValueError("At least one scholarly source is required")
        self._sources = sources

    async def search(
        self,
        *,
        query: str,
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        results = await asyncio.gather(
            *(
                source.search(query=query, preferences=preferences, limit=limit)
                for source in self._sources
            ),
            return_exceptions=True,
        )
        records: list[ScholarlyRecord] = []
        failures: list[str] = []
        for source, result in zip(self._sources, results, strict=True):
            if isinstance(result, BaseException):
                failures.append(f"{type(source).__name__}: {result}")
            else:
                records.extend(result)
        if not records and failures:
            raise ScholarlyProviderError("; ".join(failures))
        return records

    async def search_many(
        self,
        *,
        queries: list[str],
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        async def search_source(source: ScholarlySourcePort) -> list[ScholarlyRecord]:
            if isinstance(source, MultiQueryScholarlySourcePort):
                return await source.search_many(
                    queries=queries,
                    preferences=preferences,
                    limit=limit,
                )
            normalized_queries = [query for query in queries if query.strip()]
            per_query_limit = max(
                1,
                (max(limit, 1) + len(normalized_queries) - 1)
                // max(len(normalized_queries), 1),
            )
            batches = await asyncio.gather(
                *(
                    source.search(
                        query=query,
                        preferences=preferences,
                        limit=per_query_limit,
                    )
                    for query in normalized_queries
                )
            )
            records: list[ScholarlyRecord] = []
            for query, batch in zip(normalized_queries, batches, strict=True):
                for record in batch:
                    discovery = record.metadata.setdefault("discovery_queries", [])
                    if query not in discovery:
                        discovery.append(query)
                records.extend(batch)
            return records

        results = await asyncio.gather(
            *(search_source(source) for source in self._sources),
            return_exceptions=True,
        )
        records = [
            record
            for result in results
            if isinstance(result, list)
            for record in result
        ]
        if records:
            return records
        failures = [str(result) for result in results if isinstance(result, BaseException)]
        if failures:
            raise ScholarlyProviderError("; ".join(failures))
        return []

    async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
        results = await asyncio.gather(
            *(source.get_source(identifier=identifier) for source in self._sources),
            return_exceptions=True,
        )
        return next(
            (
                result
                for result in results
                if isinstance(result, ScholarlyRecord)
            ),
            None,
        )

    async def get_sources(
        self,
        *,
        identifiers: list[str],
    ) -> list[ScholarlyRecord | None]:
        """Resolve every identifier across providers while preserving input order."""

        async def resolve_source(
            source: ScholarlySourcePort,
        ) -> list[ScholarlyRecord | None]:
            if isinstance(source, BatchScholarlySourcePort):
                return await source.get_sources(identifiers=identifiers)
            return await asyncio.gather(
                *(source.get_source(identifier=item) for item in identifiers)
            )

        provider_results = await asyncio.gather(
            *(resolve_source(source) for source in self._sources),
            return_exceptions=True,
        )
        resolved: list[ScholarlyRecord | None] = []
        for index in range(len(identifiers)):
            matches = [
                batch[index]
                for batch in provider_results
                if isinstance(batch, list)
                and index < len(batch)
                and isinstance(batch[index], ScholarlyRecord)
            ]
            if not matches:
                resolved.append(None)
                continue
            primary = matches[0]
            for incoming in matches[1:]:
                _merge_resolved_metadata(primary, incoming)
            resolved.append(primary)
        return resolved

    async def expand_related(
        self,
        *,
        seeds: list[ScholarlyRecord],
        limit: int = 20,
    ) -> list[ScholarlyRecord]:
        graph_sources = [
            source for source in self._sources if isinstance(source, CitationGraphPort)
        ]
        if not graph_sources or not seeds:
            return []
        results = await asyncio.gather(
            *(source.expand_related(seeds=seeds, limit=limit) for source in graph_sources),
            return_exceptions=True,
        )
        return [
            record
            for result in results
            if isinstance(result, list)
            for record in result
        ]


def _merge_resolved_metadata(
    target: ScholarlyRecord,
    incoming: ScholarlyRecord,
) -> None:
    """Combine provider metadata so OA/full-text links survive identity resolution."""

    if len(incoming.abstract or "") > len(target.abstract or ""):
        target.abstract = incoming.abstract
    if not target.doi:
        target.doi = incoming.doi
    if not target.venue:
        target.venue = incoming.venue
    provider_ids = dict(target.metadata.get("provider_ids") or {})
    provider_ids.update(incoming.metadata.get("provider_ids") or {})
    if incoming.provider and incoming.provider_source_id:
        provider_ids[incoming.provider] = incoming.provider_source_id
    target_full_text = str(target.metadata.get("full_text_url") or "")
    incoming_full_text = str(incoming.metadata.get("full_text_url") or "")
    merged = {**incoming.metadata, **target.metadata, "provider_ids": provider_ids}
    if not target_full_text and incoming_full_text:
        merged["full_text_url"] = incoming_full_text
        target.url = incoming.url or target.url
    target.metadata = merged
