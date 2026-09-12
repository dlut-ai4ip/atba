"""The low-level implementation of D.4's retrieval infrastructure: raw HTTP calls to the Scopus Search
API and result parsing.

**Reworked this round**: an earlier version turned "LLM generates one search query → call the Scopus
API once" into a fixed two-step pipeline function (`generate_scopus_query()` + `search_scopus()`
chained into `search_utd24_literature()`) — that design was wrong: it assumed one search query would
be enough, which contradicts the multi-round, adaptive retrieval that appendix B's "three-tier
degrading retrieval + rewrite retry" protocol requires by design (that protocol was designed for an
agent that can judge for itself "is this search good enough, should I rephrase it / drop a tier and
search again," not a one-shot call). It's now organized as:

1. **This file** keeps only the lowest-level, mechanical part — issuing HTTP requests to the external
   API, parsing the returned content, translating common error codes. It contains no judgment logic
   about "how to write a search query," "whether to search again," or "whether to look up an abstract."
   `search_scopus_raw()` (the Scopus Search API — returns a list of matching papers, including real
   title/authors/year/journal/DOI, but no abstract — the Scopus Search API itself doesn't return an
   abstract field, see the "known limitation" in its docstring) + `get_abstract_by_doi()` (looks up an
   abstract by DOI, going through Semantic Scholar → OpenAlex, two open, key-free sources, not Scopus's
   own Abstract Retrieval API — this project's current SCOPUS_API_KEY has no abstract-access
   entitlement for that endpoint, confirmed by testing, see `get_abstract_via_scopus_raw`'s docstring;
   that function's code is kept for future use, not part of the current call chain).
2. `atba/mcp_server.py` wraps these two low-level calls into two MCP tools (`search_scopus` +
   `get_paper_abstract`), runnable as an independent process (`python -m atba.mcp_server`), and usable
   by any MCP client (not only ATBA itself); it also provides `build_retrieval_toolset()` for a host
   agent to drop directly into its own `toolsets=[...]`.
3. `atba/prompts/retrieval_skill.{zh,en}.md` — the strategic knowledge of "how to retrieve" itself
   (Scopus field syntax, the three-tier degrading retrieval protocol, rewrite-retry rules, when to
   stop, coverage-report requirements) is written as one reusable skill document, spliced in by
   whichever host step's agent needs retrieval when it loads its system prompt (see
   `step3_system_prompt()` in `atba/prompts.py`). This is **not** done by standing up a separate
   "retrieval agent" as a middleman that other steps "call" — an earlier version was built that way
   (`atba/retrieval_agent.py`), and has since been abandoned: it violates the architectural rule "each
   step is one independent agent run." The retrieval actually happens inside the host step's own
   agent run — currently `atba/step3.py`, which within **one** `run()` can call `search_scopus`
   separately for multiple candidate directions, at multiple degrading tiers per direction, judging for
   itself from the results whether to rephrase the query / drop a tier and search again, until it hits
   or exhausts all three tiers plus rewrites.

The UTD24 journal list and Scopus exact-name mapping are in `atba/data/utd24_journals.py`. The
pagination/rate-limiting strategy and troubleshooting tips for common error codes are drawn from an
already-validated implementation in an earlier project (a single request tops out at 25 records,
requests are spaced 1.5 seconds apart, and 401/403/429 each correspond to a specific issue) — not made
up out of thin air.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

from .data.utd24_journals import UTD24_SCOPUS_NAMES

SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
# Scopus's own Abstract Retrieval API — this project's current key has no abstract-access entitlement
# for this endpoint (confirmed by testing, see get_abstract_via_scopus_raw's docstring), currently not
# wired into the real call chain, code kept for future use.
SCOPUS_ABSTRACT_URL = "https://api.elsevier.com/content/abstract/scopus_id"
# The actual source of abstracts: two open, key-free academic-metadata aggregation services, queried by
# DOI, see get_abstract_by_doi.
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper"
OPENALEX_URL = "https://api.openalex.org/works"

# Tested limits/recommended values for the Scopus API, drawn from an already-validated earlier project:
# a single request tops out at 25 records, requests are spaced 1.5 seconds apart to avoid triggering
# 429s.
SCOPUS_BATCH_SIZE = 25
SCOPUS_REQUEST_DELAY_SECONDS = 1.5


class RetrievedPaper(BaseModel):
    """Paper metadata parsed from a single Scopus API entry."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    scopus_id: Optional[str] = None
    citation_count: Optional[int] = None
    source_title: Optional[str] = None
    publication_type: Optional[str] = None


class ScopusSearchResult(BaseModel):
    """The return value of search_scopus_raw(): the raw result of one Scopus API call, with no
    judgment about "is this enough" or "should we search again" baked in — those judgments are left to
    the retrieval agent."""

    query: str
    papers: list[RetrievedPaper]
    total_results: int = Field(description="Total hit count reported by Scopus, which may exceed the number of papers actually returned (bounded by max_results)")


class AbstractLookupResult(BaseModel):
    """The return value of get_abstract_by_doi(). abstract=None does not mean the lookup failed — it
    may genuinely be that neither Semantic Scholar nor OpenAlex has this paper's abstract, a different
    situation from "the DOI itself couldn't be found" — neither should be misread by the caller as
    "an error happened"; the note field explains which case it actually is.

    **authors is also filled in here, along the way**: testing found that under this key's entitlement,
    the Scopus Search API doesn't return a full authors array at all — only the single dc:creator
    string (the first author), see the comment in _parse_paper. Semantic Scholar/OpenAlex's own APIs
    both return a full author list, and get_paper_abstract is already a mandatory step ("must be called
    before deciding to cite a paper," see retrieval_skill.md) — so it carries along the full author list
    these two sources already looked up, without requiring the agent to make yet another tool call.
    This is the real source for a complete author list; search_scopus's dc:creator is only a degraded
    fallback for when an abstract — or the author here — can't be found.
    """

    doi: str
    abstract: Optional[str] = None
    authors: list[str] = Field(
        default_factory=list,
        description="The full author list obtained from the same source the abstract came from (more "
        "complete than search_scopus's dc:creator, which only has the first author); an empty list "
        "when neither source found it does not mean the paper has no authors",
    )
    source: Optional[str] = Field(
        default=None, description='Which source the abstract actually came from: "semantic_scholar" or "openalex"; null when not found'
    )
    note: str = Field(default="", description="Explanation for why abstract is empty; left blank when an abstract was found")


def utd24_filter_clause() -> str:
    """The UTD24 journal-scope filter clause (an OR of EXACTSRCTITLE terms). The tool automatically
    ANDs this into every search query — the retrieval agent doesn't need to (and shouldn't) assemble
    this long string itself; it only handles the conceptual part of the query, while the journal-scope
    restriction is the tool's own inherent behavior, written here once instead of being regenerated in
    every prompt — reducing the agent's output burden and error rate."""
    clauses = [f'EXACTSRCTITLE("{name}")' for name in UTD24_SCOPUS_NAMES.values()]
    return "(" + " OR ".join(clauses) + ")"


def _parse_paper(entry: dict[str, Any]) -> RetrievedPaper:
    """Parses one Scopus API entry into a RetrievedPaper — the field mapping copies the correspondence
    already validated by the earlier reference implementation (dc:title/dc:description/prism:doi etc.
    are the Scopus Search API's own fixed field names, not invented by this project)."""
    authors: list[str] = []
    author_field = entry.get("author")
    if isinstance(author_field, list):
        authors = [a.get("authname", "") for a in author_field if isinstance(a, dict)]
    elif isinstance(author_field, dict):
        authors = [author_field.get("authname", "")]
    elif entry.get("dc:creator"):
        # Confirmed by testing (checked the raw JSON against a real API call directly): under the
        # current SCOPUS_API_KEY's entitlement, the Search API's entry doesn't have the "author" array
        # field at all (that needs a higher-privilege view) — the only field in the entry carrying any
        # author information is "dc:creator," and it's a **single string** (only the first author, e.g.
        # "Wang F."), not a full author list. The earlier code only handled the "author"-array shape and
        # never matched this key's actual response shape at all, which is why the authors field always
        # came back an empty list in testing — not the agent failing to copy the author field over, but
        # the tool itself never having passed any author information to the agent at all. This degrades
        # to using just this one known first author from dc:creator, better than nothing; the genuinely
        # complete author list is filled in by get_paper_abstract via Semantic Scholar/OpenAlex (those
        # two sources' APIs return a full author list on their own, see get_abstract_by_doi).
        authors = [entry["dc:creator"]]

    year = None
    cover_date = entry.get("prism:coverDate")
    if cover_date:
        year = cover_date.split("-")[0]

    citation_count = entry.get("citedby-count")
    if citation_count is not None:
        try:
            citation_count = int(citation_count)
        except (ValueError, TypeError):
            citation_count = None

    return RetrievedPaper(
        title=entry.get("dc:title", ""),
        authors=authors,
        year=year,
        abstract=entry.get("dc:description"),
        doi=entry.get("prism:doi"),
        scopus_id=(entry.get("dc:identifier") or "").replace("SCOPUS_ID:", "") or None,
        citation_count=citation_count,
        source_title=entry.get("prism:publicationName"),
        publication_type=entry.get("subtypeDescription"),
    )


def _scopus_error_message(exc: httpx.HTTPStatusError) -> str:
    """Translates common Scopus API error status codes into actionable troubleshooting messages — these
    correspondences were tested against the reference implementation and reused directly, not guessed:
    401 means the key itself is invalid, 403 usually means a missing institutional token or an IP
    outside the authorized range, 429 means the weekly quota (typically 5000 calls) has been used up."""
    status = exc.response.status_code
    if status == 401:
        return "Scopus API key is invalid. Check SCOPUS_API_KEY in atba/.env, or apply for a valid key at https://dev.elsevier.com/."
    if status == 403:
        return "Scopus API access denied. This may require an institutional token (SCOPUS_INST_TOKEN), or the current IP isn't in the authorized range — check with your institution's library."
    if status == 429:
        return "Scopus API rate limit exceeded (usually the weekly quota, commonly capped at 5000 calls). Retry later, or check your quota at https://dev.elsevier.com/."
    return f"Scopus API returned an error (HTTP {status}): {exc.response.text[:200]}"


async def search_scopus_raw(query: str, max_results: int = 20) -> ScopusSearchResult:
    """Issues a real API request for one Scopus search query and returns the raw result — it does not
    judge "is this search good enough," that's the retrieval agent's job; this only sends the request
    and parses the result back.

    Pagination and rate-limiting copy the already-validated approach from an earlier project: a single
    batch tops out at 25 records (the Scopus API's own limit), with a 1.5-second wait between batches
    to avoid triggering 429s.

    **Validated with a real key, and one known limitation was found**: the real Scopus API call itself
    works fine (real search queries, real hit counts, real paper metadata, real DOIs). But this
    function itself **cannot obtain paper abstracts** — for two layered reasons: (1) the Scopus Search
    API's default (STANDARD) view simply doesn't include a `dc:description` (abstract) field in its
    results — this is the API's own limitation, not a flaw in this project's parsing logic; (2) adding
    the `view=COMPLETE` parameter was tried (per Scopus's docs, the COMPLETE view should include
    abstracts), and it turned out this key's entitlement doesn't include COMPLETE-view access, returning
    a flat 401 Unauthorized — worse than "found results but no abstract" (the entire search fails
    outright), so it was reverted to the no-view-parameter STANDARD view. **To get abstracts, use
    `get_abstract_raw()` below** — the Abstract Retrieval API is a separate endpoint from the Search
    API, looked up per paper by Scopus ID, and is not part of this function (nor should it be:
    automatically looking up abstracts for every paper a search hits would waste a large amount of
    quota on papers the agent will never end up citing — abstract lookups should only be issued on
    demand, for papers it has actually decided to cite).
    """
    api_key = os.environ.get("SCOPUS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Environment variable SCOPUS_API_KEY not found. Set it in atba/.env before running, "
            "apply at https://dev.elsevier.com/ (an institutional Scopus subscription is needed for a valid quota)."
        )
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    inst_token = os.environ.get("SCOPUS_INST_TOKEN")
    if inst_token:
        headers["X-ELS-Insttoken"] = inst_token

    papers: list[RetrievedPaper] = []
    total_results = 0

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # No view parameter (defaults to the STANDARD view) — view=COMPLETE was tested: this
            # project's current SCOPUS_API_KEY entitlement doesn't include COMPLETE-view access and
            # returns a flat 401 Unauthorized, meaning the search fails outright — worse than "found
            # results but no abstract." The COMPLETE view typically requires an institutional-tier
            # subscription that a personally-obtained key is unlikely to have. Under the STANDARD view,
            # the Scopus Search API simply doesn't return a dc:description (abstract) field — this isn't
            # an extraction oversight in this project, it's the Search API's inherent limitation; to
            # actually get an abstract requires a separate Abstract Retrieval API endpoint, looked up
            # again per Scopus ID (see the "known limitation" section in search_scopus_raw's docstring
            # above) — that's still unimplemented follow-up work.
            params: dict[str, Any] = {
                "query": query,
                "count": SCOPUS_BATCH_SIZE,
                "sort": "relevance",
                "start": 0,
            }

            response = await client.get(SCOPUS_SEARCH_URL, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            search_results = data.get("search-results", {})
            total_results = int(search_results.get("opensearch:totalResults", 0))

            for entry in search_results.get("entry", []) or []:
                if "error" in entry:
                    continue
                papers.append(_parse_paper(entry))

            # Keep paging until max_results is reached or total_results is exhausted.
            while len(papers) < max_results and len(papers) < total_results:
                await asyncio.sleep(SCOPUS_REQUEST_DELAY_SECONDS)
                params["start"] = len(papers)
                params["count"] = min(SCOPUS_BATCH_SIZE, max_results - len(papers))

                response = await client.get(SCOPUS_SEARCH_URL, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                entries = data.get("search-results", {}).get("entry", []) or []
                if not entries:
                    break
                for entry in entries:
                    if "error" in entry:
                        continue
                    papers.append(_parse_paper(entry))
                    if len(papers) >= max_results:
                        break

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(_scopus_error_message(exc)) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError("Scopus API request timed out.") from exc

    return ScopusSearchResult(query=query, papers=papers[:max_results], total_results=total_results)


async def get_abstract_via_scopus_raw(scopus_id: str) -> AbstractLookupResult:
    """Looks up a paper's full abstract by Scopus ID — Scopus's own Abstract Retrieval API, a separate
    endpoint from the Search API that search_scopus_raw uses.

    **Currently not called by any tool, kept for future use**: testing confirmed this project's current
    SCOPUS_API_KEY entitlement doesn't include abstract-access rights — the default view returns 200
    with no abstract field, and `view=FULL`/`META_ABS`/`ENTITLED` all return an explicit
    `AUTHORIZATION_ERROR` ("Requestor is not entitled to the requested resource"). This is a hard limit
    of the account's subscription tier, not a code/parameter problem — a personally-obtained key is
    unlikely to get abstract-access rights. The `get_paper_abstract` tool now uses
    `get_abstract_by_doi()` instead (Semantic Scholar + OpenAlex, two open, key-free sources) — this
    function's code is kept but not wired into the call chain; it'll be useful once switched to a key
    with abstract entitlement (typically requiring an institutional subscription), at which point it
    could be wired back in as a third-tier fallback for when neither Semantic Scholar nor OpenAlex has
    it.
    """
    api_key = os.environ.get("SCOPUS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Environment variable SCOPUS_API_KEY not found. Set it in atba/.env before running, "
            "apply at https://dev.elsevier.com/ (an institutional Scopus subscription is needed for a valid quota)."
        )
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    inst_token = os.environ.get("SCOPUS_INST_TOKEN")
    if inst_token:
        headers["X-ELS-Insttoken"] = inst_token

    url = f"{SCOPUS_ABSTRACT_URL}/{scopus_id}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return AbstractLookupResult(doi="", abstract=None, note="Scopus has no entry matching this scopus_id — double-check the ID is correct.")
        raise RuntimeError(_scopus_error_message(exc)) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError("Scopus Abstract Retrieval API request timed out.") from exc

    core = data.get("abstracts-retrieval-response", {}).get("coredata", {})
    abstract = core.get("dc:description")
    if not abstract or not str(abstract).strip():
        return AbstractLookupResult(doi="", abstract=None, note="Scopus returned no abstract (insufficient entitlement, or the paper simply isn't indexed with one — see this function's docstring).")
    return AbstractLookupResult(doi="", abstract=str(abstract).strip(), source="scopus")


def _reconstruct_openalex_abstract(inverted_index: dict[str, list[int]]) -> str:
    """OpenAlex doesn't return plain abstract text directly, but an "inverted index" format
    (`{word: [position, ...]}`) — a data format OpenAlex itself chose to sidestep copyright concerns (it
    doesn't directly host copy-pasteable full text), requiring the words to be reassembled into
    continuous text by position. This isn't an extra processing step this project invented; it's the
    necessary step for consuming OpenAlex's abstract data, exactly as their official docs describe."""
    if not inverted_index:
        return ""
    max_pos = max(pos for positions in inverted_index.values() for pos in positions)
    words: list[str] = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(w for w in words if w)


async def _fetch_abstract_semantic_scholar(doi: str) -> tuple[Optional[str], list[str]]:
    """Semantic Scholar's Graph API, key-free (rate-limited under the key-free tier; setting
    `SEMANTIC_SCHOLAR_API_KEY` optionally raises the quota, but it works fine unset too). Returns
    (None, []) whether the paper can't be found or has no abstract, without raising — this is the first
    tier in a "two-tier free-source fallback chain," and a miss on the first tier is common; the chain
    shouldn't be broken here.

    **Also requests the authors field along the way**: since this request is already being made,
    requesting one more field doesn't cost an extra call — Semantic Scholar's authors field is directly
    a full author list ([{name: ...}, ...]), much more complete than the dc:creator (first author only)
    this key gets from the Scopus Search API."""
    headers = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    url = f"{SEMANTIC_SCHOLAR_URL}/DOI:{doi}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params={"fields": "abstract,authors"})
            if response.status_code != 200:
                return None, []
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return None, []
    abstract = data.get("abstract")
    abstract = abstract.strip() if abstract and str(abstract).strip() else None
    authors_field = data.get("authors")
    authors = (
        [a.get("name", "") for a in authors_field if isinstance(a, dict) and a.get("name")]
        if isinstance(authors_field, list)
        else []
    )
    return abstract, authors


async def _fetch_abstract_openalex(doi: str) -> tuple[Optional[str], list[str]]:
    """OpenAlex's Works API, key-free. The `mailto` parameter is OpenAlex's "polite pool" mechanism —
    including a contact email upgrades from the default rate limit to a more generous tier; it's not a
    required parameter, see the CONTACT_EMAIL note in atba/.env.example.

    **Also requests the authorships field along the way**: the Work object OpenAlex returns by default
    already includes the full authorships array (no extra field parameter needed to request it), pulled
    out in the same request for the same reason as the Semantic Scholar function above."""
    params = {}
    contact_email = os.environ.get("CONTACT_EMAIL")
    if contact_email:
        params["mailto"] = contact_email
    url = f"{OPENALEX_URL}/doi:{doi}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                return None, []
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return None, []
    authorships = data.get("authorships")
    authors = (
        [
            a["author"]["display_name"]
            for a in authorships
            if isinstance(a, dict) and isinstance(a.get("author"), dict) and a["author"].get("display_name")
        ]
        if isinstance(authorships, list)
        else []
    )
    inverted = data.get("abstract_inverted_index")
    if not inverted:
        return None, authors
    text = _reconstruct_openalex_abstract(inverted)
    return (text if text.strip() else None), authors


async def get_abstract_by_doi(doi: str) -> AbstractLookupResult:
    """Looks up a paper's abstract by DOI (and its full author list, see AbstractLookupResult.authors)
    — not via Scopus's own Abstract Retrieval API (this project's current key has no abstract-access
    entitlement for that endpoint, see `get_abstract_via_scopus_raw`'s docstring); instead, two open,
    key-free academic-metadata services are tried in order: Semantic Scholar first, then OpenAlex if
    that misses. Modeled on an earlier project's same design of "Scopus for metadata+DOI, abstracts
    filled in by a separate free source" (that project's fallback chain was also Semantic Scholar →
    OpenAlex; the same order and reasoning are replicated here: the two sources' hit rates are
    complementary — Semantic Scholar tends to cover CS/AI literature better, OpenAlex tends to have
    broader coverage across disciplines, including management).

    doi must be a real value taken from RetrievedPaper.doi in a `search_scopus` result, never one the
    agent made up.
    """
    abstract, authors = await _fetch_abstract_semantic_scholar(doi)
    if abstract:
        return AbstractLookupResult(doi=doi, abstract=abstract, authors=authors, source="semantic_scholar")

    abstract, authors2 = await _fetch_abstract_openalex(doi)
    if abstract:
        return AbstractLookupResult(doi=doi, abstract=abstract, authors=authors2, source="openalex")

    # Neither source found an abstract, but one of them may still have found an author list (e.g.
    # OpenAlex indexes this paper's metadata but not its abstract text) — author information shouldn't
    # be discarded just because the abstract wasn't found; give whatever can be given.
    fallback_authors = authors or authors2

    return AbstractLookupResult(
        doi=doi,
        abstract=None,
        authors=fallback_authors,
        note="Neither Semantic Scholar nor OpenAlex has an abstract for this paper (the DOI may be wrong, or neither source indexes it — this does not mean the paper doesn't exist, only that these two open abstract sources don't have it).",
    )
