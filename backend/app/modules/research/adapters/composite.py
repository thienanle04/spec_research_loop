"""Federated scholarly retrieval across independent provider adapters."""

import asyncio

from app.modules.research.ports import (
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
            batches = await asyncio.gather(
                *(
                    source.search(
                        query=query,
                        preferences=preferences,
                        limit=limit,
                    )
                    for query in queries
                )
            )
            records: list[ScholarlyRecord] = []
            for query, batch in zip(queries, batches, strict=True):
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
