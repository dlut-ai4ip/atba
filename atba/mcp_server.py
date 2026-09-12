"""The MCP server for D.4's retrieval infrastructure: wraps UTD24-scoped Scopus retrieval as a standard
MCP tool.

Independently runnable (`python -m atba.mcp_server`, stdio transport), reachable by any MCP client, not
only ATBA itself — this is the protocol-level realization of "retrieval as an independently deployable
service" (see the technical appendix's D.4): the retrieval agent doesn't directly import functions from
`atba/retrieval.py`, it calls through the MCP protocol like connecting to any external tool — the tool's
implementation details (how the Scopus API is called, how pagination/rate-limiting are handled) are
entirely invisible to the caller, which only sees one interface: "give me a search query, get back a
list of papers."

Exposes two tools: `search_scopus` (returns a list of matching papers, including real title/authors/
year/journal/DOI, no abstract) + `get_paper_abstract` (looks up one paper's full abstract by DOI — via
Semantic Scholar/OpenAlex, two open, key-free sources, not Scopus's own Abstract Retrieval API, since
this project's current SCOPUS_API_KEY has no abstract-access entitlement for that endpoint, confirmed by
testing, see `get_abstract_via_scopus_raw()`'s docstring in `atba/retrieval.py`). Neither makes any
judgment at this layer ("should I search again," "is this worth looking up an abstract for") — that's
decided by whichever host agent loads these tools (step 3, and in the future step 4's internal novelty
check), combined with the strategic knowledge in `atba/prompts/retrieval_skill.md` — the tools
themselves only handle mechanical execution.

**This file does not define any "retrieval agent"** — an earlier version additionally built a standalone
`retrieval_agent.py`, wrapping "load the MCP tool + skill, retrieve autonomously across multiple rounds"
into a separate agent that other steps could call as a "sub-agent." This violated the architectural rule
"each step is one independent agent run" (a point repeatedly emphasized in each step's docstring) —
retrieval capability should be a tool + skill directly attached by "each step's own agent," not wrapped
in yet another standalone retrieval agent as a middleman. Now `build_retrieval_toolset()` just returns
one `MCPToolset`, for an Agent like step 3's (`atba/step3.py`) to drop directly into its own
`toolsets=[...]`; the retrieval-strategy knowledge is spliced into the host agent's own system prompt in
the form of `retrieval_skill_system_prompt()` (see atba/prompts.py), not run as a separate agent.run().
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP
from pydantic_ai.mcp import MCPToolset

from .retrieval import (
    AbstractLookupResult,
    ScopusSearchResult,
    get_abstract_by_doi,
    search_scopus_raw,
    utd24_filter_clause,
)

mcp = FastMCP(
    name="atba-utd24-retrieval",
    instructions=(
        "在UTD24（UT Dallas评选的24本管理学顶级期刊）范围内检索Scopus文献。"
        "只需要给出检索概念部分的Scopus查询语法（如 TITLE-ABS-KEY(...)），"
        "不需要自己拼期刊范围限定——这个工具会自动加上。"
    ),
)


@mcp.tool()
async def search_scopus(query: str, max_results: int = 20) -> ScopusSearchResult:
    """在UTD24期刊范围内检索Scopus文献。

    Args:
        query: Scopus检索式的概念部分，例如
            `TITLE-ABS-KEY("algorithmic management" OR "algorithmic control")`。
            不要自己拼EXACTSRCTITLE式的期刊范围限定，工具会自动加上UTD24的24本期刊过滤。
        max_results: 最多取回多少篇（默认20，建议先用较小值探索，命中量大再加大）。

    Returns:
        query: 实际执行的完整检索式（含自动拼接的UTD24期刊过滤，供审计核实"到底搜了什么"）。
        papers: 取回的论文列表（标题/作者/年份/摘要/DOI等元数据，Scopus API本身不返回全文）。
        total_results: Scopus报告的命中总数，可能大于papers长度（受max_results限制）——
            total_results很小甚至为0时，说明这条检索式在UTD24范围内确实没什么文献，
            不是取回逻辑出了问题。
    """
    filtered_query = f"({query}) AND {utd24_filter_clause()}"
    return await search_scopus_raw(filtered_query, max_results=max_results)


@mcp.tool()
async def get_paper_abstract(doi: str) -> AbstractLookupResult:
    """查一篇论文的摘要全文——search_scopus的返回结果本身不带摘要（Scopus Search API的固有限制），
    这里按DOI查两个开放的学术元数据源（Semantic Scholar优先，查不到再试OpenAlex），不是查Scopus
    自己的摘要端点（本项目现有key对那个端点没有摘要访问权限）。

    **只对你确定要放进cited_evidence引用的论文调用这个工具**，不要对每次search_scopus命中的
    所有论文都查一遍摘要——那样会浪费不必要的请求在你根本不会引用的论文上，多数检索结果只是用来
    判断"这条检索式搜出来的东西对不对题"，真正要精读、要在最终研究问题里引用的往往只有几篇。

    Args:
        doi: 来自search_scopus返回的RetrievedPaper.doi字段（真实DOI，不是scopus_id，也不能是
            编的）。

    Returns:
        abstract: 摘要全文；为null不代表查询失败，可能是两个源都确实没收录这篇论文的摘要——
            看note字段的说明。
        source: 摘要实际取自"semantic_scholar"还是"openalex"；查不到时为null。
        note: abstract为空时的原因；查到时留空。
    """
    return await get_abstract_by_doi(doi)


def build_retrieval_toolset() -> MCPToolset:
    """For a host agent (step 3 and others) to drop directly into `Agent(toolsets=[...])`. Uses
    `client=mcp` (this file's FastMCP instance) to connect in-process — fastmcp supports this usage,
    still going through real MCP protocol messages, not a shortcut that bypasses the protocol with a
    plain function call; no extra subprocess needs to be spawned, suiting embedded use from the CLI/API.
    This file can still be run independently with `python -m atba.mcp_server` (stdio transport), for
    other MCP clients outside this project to connect to — the two usages don't conflict."""
    return MCPToolset(client=mcp)


if __name__ == "__main__":
    mcp.run()
