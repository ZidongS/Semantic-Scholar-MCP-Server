from mcp.server import FastMCP
import os
import json
import typing as t
import urllib.parse
import yaml
import requests


mcp = FastMCP("Semantic-Scholar-MCP", host="127.0.0.1", port=6666)

# -----------------------------
# Internal configuration helpers
# -----------------------------
_BASE_URL = "https://api.semanticscholar.org/graph/v1"


def _load_api_key() -> t.Optional[str]:
    """Load Semantic Scholar API key from env or optional config.yaml in this folder.

    Precedence: environment variable SEMANTIC_SCHOLAR_API_KEY > config.yaml (key: semantic_scholar.api_key).
    Returns None if no key is found; the API also works without a key but rate limits are strict.
    """
    env_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if env_key:
        return env_key.strip()
    # Best-effort read local config if yaml is available
    if yaml is not None:
        cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                key = (
                    data.get("semantic_scholar", {}) if isinstance(data, dict) else {}
                )
                api_key = None
                if isinstance(key, dict):
                    api_key = key.get("api_key")
                if api_key:
                    return str(api_key).strip()
            except Exception:
                pass
    return None


def _request_json(
    method: str,
    path: str,
    params: t.Optional[dict] = None,
    json_body: t.Optional[dict] = None,
) -> dict:
    """Make an HTTP request to Semantic Scholar Graph API and return parsed JSON.

    - Adds `x-api-key` header when an API key is available.
    - Raises a concise error when the response is not 2xx.
    """
    if requests is None:
        raise RuntimeError(
            "The 'requests' package is required. Please install it and retry."
        )

    url = _BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers: dict[str, str] = {"Accept": "application/json"}
    api_key = _load_api_key()
    if api_key:
        headers["x-api-key"] = api_key

    resp = requests.request(method=method.upper(), url=url, params=params, json=json_body, headers=headers, timeout=30)
    if not (200 <= resp.status_code < 300):
        # Try to include API error message if provided
        try:
            payload = resp.json()
        except Exception:
            payload = {"message": resp.text}
        raise RuntimeError(
            f"Semantic Scholar API error {resp.status_code} for {url}: {payload}"
        )
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _normalize_fields(fields: t.Optional[t.Union[str, t.Sequence[str]]]) -> t.Optional[str]:
    """Normalize fields parameter into a comma-separated string if provided."""
    if fields is None:
        return None
    if isinstance(fields, str):
        return fields
    try:
        return ",".join([str(f).strip() for f in fields if str(f).strip()]) or None
    except Exception:
        return None


# -----------------------------
# MCP Tools
# -----------------------------
@mcp.tool()
def get_paper(
    paper_id: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "title,authors,abstract,year,venue,externalIds,url,referenceCount,citationCount,fieldsOfStudy,openAccessPdf",
) -> str:
    """Retrieve a single paper by its Semantic Scholar paper ID.

    Purpose:
        Fetch metadata for a specific paper using `/paper/{paper_id}` from the Semantic Scholar Graph API.

    Parameters:
        - paper_id (str, required):
            Semantic Scholar Paper ID or a supported external ID (e.g., DOI prefixed `DOI:`).
        - fields (str | list[str], optional, default includes common fields):
            Comma-separated string or list of fields to include in the response. If omitted, a
            practical default subset is requested.

    Response:
        - JSON string containing the paper object with the requested fields.

    Errors:
        - 400 if `paper_id` is empty.
        - RuntimeError with upstream status when the API returns non-2xx.
    """
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("Parameter 'paper_id' must be a non-empty string.")

    params: dict[str, t.Any] = {}
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields

    data = _request_json("GET", f"/paper/{urllib.parse.quote(paper_id.strip())}", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_papers_batch(
    paper_ids: t.Sequence[str],
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "title,authors,year,venue,externalIds,url",
) -> str:
    """Batch-retrieve papers by IDs using `/paper/batch`.

    Purpose:
        Request multiple papers in a single call. This tool wraps POST `/paper/batch`.

    Parameters:
        - paper_ids (list[str], required):
            List of Semantic Scholar paper IDs or supported external IDs. Must be 1..1000 items.
        - fields (str | list[str], optional):
            Comma-separated string or list of fields to include for each paper.

    Response:
        - JSON string with an array of paper objects, each corresponding to an input ID.

    Errors:
        - 400 if `paper_ids` is empty, contains non-strings, or exceeds 1000.
        - RuntimeError with upstream status when the API returns non-2xx.
    """
    if not isinstance(paper_ids, (list, tuple)) or len(paper_ids) == 0:
        raise ValueError("Parameter 'paper_ids' must be a non-empty list of strings.")
    if len(paper_ids) > 1000:
        raise ValueError("Parameter 'paper_ids' cannot exceed 1000 items per request.")
    clean_ids: list[str] = []
    for pid in paper_ids:
        if not isinstance(pid, str) or not pid.strip():
            raise ValueError("Every item in 'paper_ids' must be a non-empty string.")
        clean_ids.append(pid.strip())

    body: dict[str, t.Any] = {"ids": clean_ids}
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        body["fields"] = norm_fields

    data = _request_json("POST", "/paper/batch", json_body=body)
    return json.dumps(data, ensure_ascii=False)
@mcp.tool()
def search_papers(
    query: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "title,authors,year,venue,externalIds,url",
    limit: int = 25,
    offset: int = 0,
    year: t.Optional[str] = None,
    open_access_pdf: t.Optional[bool] = None,
    fields_of_study: t.Optional[t.Union[str, t.Sequence[str]]] = None,
) -> str:
    """Search for papers via Semantic Scholar Graph API.

    This tool queries `/paper/search` to retrieve papers matching a free-text query with
    optional filters.

    Args:
        query: Free-text search query.
        fields: Comma-separated list (or list) of fields to return. Defaults to a helpful subset.
        limit: Max results to return (API typically supports up to 100 per page).
        offset: Result offset for pagination.
        year: Optional year filter. Use single year (e.g., "2023") or range (e.g., "2018-2024").
        open_access_pdf: If True/False, filter by presence of Open Access PDF.
        fields_of_study: One or more Fields of Study filters (e.g., "Computer Science").

    Returns:
        JSON string with the search response, including `total` and `data` list of papers.
    """
    params: dict[str, t.Any] = {
        "query": query,
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    if year:
        params["year"] = str(year)
    if open_access_pdf is not None:
        params["openAccessPdf"] = "true" if open_access_pdf else "false"
    norm_fos = _normalize_fields(fields_of_study)
    if norm_fos:
        params["fieldsOfStudy"] = norm_fos

    data = _request_json("GET", "/paper/search", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def search_papers_bulk(
    queries: t.Sequence[str],
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "title,authors,year,venue,url",
    limit: int = 25,
    offset: int = 0,
) -> str:
    """Bulk search for papers via POST `/paper/search/bulk`.

    Purpose:
        Submit multiple free-text queries in one request to retrieve results for each query.

    Parameters:
        - queries (list[str], required): 1..100 queries. Each query is a free-text string.
        - fields (str | list[str], optional): Response fields for returned paper items.
        - limit (int, optional, default 25): Page size per query, clamped to [1, 100].
        - offset (int, optional, default 0): Offset per query, must be >= 0.

    Response:
        - JSON string containing results grouped per input query.

    Errors:
        - 400 for invalid `queries`, `limit`, or `offset`.
        - RuntimeError with upstream status when the API returns non-2xx.
    """
    if not isinstance(queries, (list, tuple)) or len(queries) == 0:
        raise ValueError("Parameter 'queries' must be a non-empty list of strings.")
    if len(queries) > 100:
        raise ValueError("Parameter 'queries' cannot exceed 100 items.")
    clean_q: list[str] = []
    for q in queries:
        if not isinstance(q, str) or not q.strip():
            raise ValueError("Every item in 'queries' must be a non-empty string.")
        clean_q.append(q.strip())

    page_limit = max(1, min(int(limit), 100))
    page_offset = max(0, int(offset))

    norm_fields = _normalize_fields(fields)
    body: dict[str, t.Any] = {
        "queries": clean_q,
        "limit": page_limit,
        "offset": page_offset,
    }
    if norm_fields:
        body["fields"] = norm_fields

    data = _request_json("POST", "/paper/search/bulk", json_body=body)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def search_papers_match(
    title: str,
    authors: t.Optional[t.Union[str, t.Sequence[str]]] = None,
    year: t.Optional[int] = None,
    venue: t.Optional[str] = None,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "title,authors,year,venue,url,externalIds",
    limit: int = 5,
) -> str:
    """Find likely matches for a paper by metadata using `/paper/search/match`.

    Purpose:
        Given a paper's metadata (e.g., title and optionally authors/year/venue), find the most
        likely matching records in Semantic Scholar.

    Parameters:
        - title (str, required): Paper title to match.
        - authors (str | list[str], optional): Author names; can be comma-separated or list.
        - year (int, optional): Publication year.
        - venue (str, optional): Venue/journal/conference name.
        - fields (str | list[str], optional): Fields to include in the response.
        - limit (int, optional, default 5): Max number of matches to return (1..20).

    Response:
        - JSON string with a list of candidate matches ranked by confidence.

    Errors:
        - 400 for invalid inputs (e.g., empty title, invalid limit).
        - RuntimeError with upstream status when the API returns non-2xx.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Parameter 'title' must be a non-empty string.")
    if year is not None and (not isinstance(year, int) or year < 0):
        raise ValueError("Parameter 'year' must be a non-negative integer if provided.")
    max_limit = max(1, min(int(limit), 20))

    norm_fields = _normalize_fields(fields)
    authors_norm = _normalize_fields(authors)
    body: dict[str, t.Any] = {
        "title": title.strip(),
        "limit": max_limit,
    }
    if authors_norm:
        body["authors"] = authors_norm
    if year is not None:
        body["year"] = int(year)
    if venue:
        body["venue"] = str(venue)
    if norm_fields:
        body["fields"] = norm_fields

    data = _request_json("POST", "/paper/search/match", json_body=body)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def paper_autocomplete(
    query: str,
    limit: int = 10,
) -> str:
    """Autocomplete paper titles via `/paper/autocomplete`.

    Purpose:
        Provide typeahead suggestions for paper titles.

    Parameters:
        - query (str, required): Partial text to autocomplete.
        - limit (int, optional, default 10): Number of suggestions (1..100).

    Response:
        - JSON string with suggestions for titles, potentially including IDs.

    Errors:
        - 400 for invalid inputs.
        - RuntimeError with upstream status when the API returns non-2xx.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Parameter 'query' must be a non-empty string.")
    page_limit = max(1, min(int(limit), 100))
    params = {"query": query.strip(), "limit": page_limit}
    data = _request_json("GET", "/paper/autocomplete", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_paper_authors(
    paper_id: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "authors.name,authors.authorId,authors.hIndex,authors.url",
    limit: int = 100,
    offset: int = 0,
) -> str:
    """List authors for a paper via `/paper/{paper_id}/authors`.

    Parameters:
        - paper_id (str, required): Semantic Scholar Paper ID or supported external ID.
        - fields (str | list[str], optional): Fields to include for author entries.
        - limit (int, optional, default 100): Page size (1..1000 depending on API; we clamp to 100).
        - offset (int, optional, default 0): Pagination offset, >= 0.

    Response:
        - JSON string with `data` containing author entries and pagination metadata if provided.
    """
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("Parameter 'paper_id' must be a non-empty string.")
    params: dict[str, t.Any] = {
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    data = _request_json("GET", f"/paper/{urllib.parse.quote(paper_id.strip())}/authors", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_paper_citations(
    paper_id: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "citingPaper.title,citingPaper.authors,citingPaper.year,citingPaper.url",
    limit: int = 100,
    offset: int = 0,
) -> str:
    """List citations of a paper via `/paper/{paper_id}/citations`.

    Parameters:
        - paper_id (str, required): Semantic Scholar Paper ID or supported external ID.
        - fields (str | list[str], optional): Fields to include for `citingPaper` records.
        - limit (int, optional, default 100): Page size (1..100).
        - offset (int, optional, default 0): Pagination offset.
    """
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("Parameter 'paper_id' must be a non-empty string.")
    params: dict[str, t.Any] = {
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    data = _request_json("GET", f"/paper/{urllib.parse.quote(paper_id.strip())}/citations", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_paper_references(
    paper_id: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "citedPaper.title,citedPaper.authors,citedPaper.year,citedPaper.url",
    limit: int = 100,
    offset: int = 0,
) -> str:
    """List references of a paper via `/paper/{paper_id}/references`.

    Parameters:
        - paper_id (str, required): Semantic Scholar Paper ID or supported external ID.
        - fields (str | list[str], optional): Fields to include for `citedPaper` records.
        - limit (int, optional, default 100): Page size (1..100).
        - offset (int, optional, default 0): Pagination offset.
    """
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("Parameter 'paper_id' must be a non-empty string.")
    params: dict[str, t.Any] = {
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    data = _request_json("GET", f"/paper/{urllib.parse.quote(paper_id.strip())}/references", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_author(
    author_id: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "name,authorId,affiliations,hIndex,homepage,url,paperCount,citationCount",
) -> str:
    """Retrieve an author by ID via `/author/{author_id}`.

    Parameters:
        - author_id (str, required): Semantic Scholar Author ID.
        - fields (str | list[str], optional): Fields to include in the author object.
    """
    if not isinstance(author_id, str) or not author_id.strip():
        raise ValueError("Parameter 'author_id' must be a non-empty string.")
    params: dict[str, t.Any] = {}
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    data = _request_json("GET", f"/author/{urllib.parse.quote(author_id.strip())}", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_authors_batch(
    author_ids: t.Sequence[str],
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "name,authorId,hIndex,url",
) -> str:
    """Batch-retrieve authors via POST `/author/batch`.

    Parameters:
        - author_ids (list[str], required): 1..1000 Semantic Scholar Author IDs.
        - fields (str | list[str], optional): Fields to include per author.
    """
    if not isinstance(author_ids, (list, tuple)) or len(author_ids) == 0:
        raise ValueError("Parameter 'author_ids' must be a non-empty list of strings.")
    if len(author_ids) > 1000:
        raise ValueError("Parameter 'author_ids' cannot exceed 1000 items.")
    clean_ids: list[str] = []
    for aid in author_ids:
        if not isinstance(aid, str) or not aid.strip():
            raise ValueError("Every item in 'author_ids' must be a non-empty string.")
        clean_ids.append(aid.strip())

    body: dict[str, t.Any] = {"ids": clean_ids}
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        body["fields"] = norm_fields
    data = _request_json("POST", "/author/batch", json_body=body)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def search_authors(
    query: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "name,authorId,hIndex,affiliations,url",
    limit: int = 25,
    offset: int = 0,
) -> str:
    """Search authors by name/keywords via `/author/search`.

    Parameters:
        - query (str, required): Free-text search query (e.g., author name).
        - fields (str | list[str], optional): Fields to include per author in results.
        - limit (int, optional, default 25): Page size in [1, 100].
        - offset (int, optional, default 0): Offset >= 0.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Parameter 'query' must be a non-empty string.")
    params: dict[str, t.Any] = {
        "query": query.strip(),
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    data = _request_json("GET", "/author/search", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_author_papers(
    author_id: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "papers.title,papers.year,papers.venue,papers.url",
    limit: int = 100,
    offset: int = 0,
    sort: t.Optional[str] = None,
) -> str:
    """List papers for an author via `/author/{author_id}/papers`.

    Parameters:
        - author_id (str, required): Semantic Scholar Author ID.
        - fields (str | list[str], optional): Fields to include for `papers` entries.
        - limit (int, optional, default 100): Page size (1..100).
        - offset (int, optional, default 0): Pagination offset.
        - sort (str, optional): Sort key per API (e.g., "year"). If provided, passed through.
    """
    if not isinstance(author_id, str) or not author_id.strip():
        raise ValueError("Parameter 'author_id' must be a non-empty string.")
    params: dict[str, t.Any] = {
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }
    if sort:
        params["sort"] = str(sort)
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    data = _request_json("GET", f"/author/{urllib.parse.quote(author_id.strip())}/papers", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def snippet_search(
    query: str,
    fields: t.Optional[t.Union[str, t.Sequence[str]]] = "paperId,title,authors,year,url,abstract",
    limit: int = 25,
    offset: int = 0,
    fields_of_study: t.Optional[t.Union[str, t.Sequence[str]]] = None,
) -> str:
    """Search snippets via `/snippet/search` to find relevant passages in papers.

    Purpose:
        Retrieve relevant snippets/passages given a textual query. This can return paper-level
        metadata alongside snippet context depending on API configuration.

    Parameters:
        - query (str, required): Free-text query for snippet retrieval.
        - fields (str | list[str], optional): Fields to include for returned items.
        - limit (int, optional, default 25): Page size in [1, 100].
        - offset (int, optional, default 0): Pagination offset.
        - fields_of_study (str | list[str], optional): Filter by field(s) of study.

    Response:
        - JSON string with snippet search results; may include `snippets`, `paperId`, etc.

    Errors:
        - 400 for invalid parameters.
        - RuntimeError with upstream status when the API returns non-2xx.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Parameter 'query' must be a non-empty string.")
    params: dict[str, t.Any] = {
        "query": query.strip(),
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }
    norm_fields = _normalize_fields(fields)
    if norm_fields:
        params["fields"] = norm_fields
    fos = _normalize_fields(fields_of_study)
    if fos:
        params["fieldsOfStudy"] = fos
    data = _request_json("GET", "/snippet/search", params=params)
    return json.dumps(data, ensure_ascii=False)

if __name__ == "__main__":
    mcp.run(transport="sse")