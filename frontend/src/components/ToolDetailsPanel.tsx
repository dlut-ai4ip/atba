import { useT } from "../i18n";
import { TOOL_ICONS, TOOL_LABEL_KEY, tryParseJson, type CallRecord } from "./ToolCallEntry";

// The persistent details panel on the right — the "TOOL OUTPUT DETAILS" panel from
// design/tool_output_panel.png, replacing ToolCallEntry.tsx's old in-place <details> expansion (per
// user feedback that "per the interaction diagram, clicking a tool call's result should show it in a
// sidebar on the right," with an explicit requirement that "the right-hand panel replaces the old
// expand/collapse, not coexists with it"). This component is only the panel's *content* (a title row +
// body); the outer fixed-position/scroll container (.shell-details-panel) is provided uniformly by
// AppShell.tsx — see its detailsPanel slot, a sibling of .shell-sidebar, so that if this slot ever
// needs to hold different content in the future, the positioning doesn't need to be reimplemented.

interface ScopusPaper {
  title: string;
  authors: string[];
  year: string | null;
  abstract: string | null;
  doi: string | null;
  citation_count: number | null;
  source_title: string | null;
}

interface ScopusSearchResultShape {
  query: string;
  papers: ScopusPaper[];
  total_results: number;
}

interface AbstractLookupResultShape {
  doi: string;
  abstract: string | null;
  source: string | null;
  note: string;
}

function PaperCard({ p }: { p: ScopusPaper }) {
  const t = useT();
  return (
    <li className="search-result-paper">
      <div className="search-result-paper-title">{p.title || t("toolCall.untitled")}</div>
      <div className="search-result-paper-meta">
        {p.authors.join(", ")}
        {p.year ? ` · ${p.year}` : ""}
        {p.source_title ? ` · ${p.source_title}` : ""}
        {p.citation_count != null ? ` · ${t("toolCall.citedBy", { n: p.citation_count })}` : ""}
        {p.doi ? (
          <>
            {" · "}
            <a href={`https://doi.org/${p.doi}`} target="_blank" rel="noreferrer">
              {p.doi}
            </a>
          </>
        ) : null}
      </div>
      {/* No placeholder hint is shown when the abstract is empty — most retrieval hits don't have an
          abstract to begin with (an abstract is only separately looked up via get_paper_abstract once
          the agent decides to cite a paper); hinting "no abstract" on every single one would just be
          noise. */}
      {p.abstract && <p className="search-result-paper-abstract">{p.abstract}</p>}
    </li>
  );
}

function SearchScopusDetail({ call }: { call: CallRecord }) {
  const t = useT();
  const args = tryParseJson(call.argsText) as { query?: string } | null;
  const result = call.resultText ? (tryParseJson(call.resultText) as ScopusSearchResultShape | null) : null;
  return (
    <div className="tool-call-detail-body">
      <div className="search-result-query">
        <span className="summary-label">{t("toolCall.query")}</span>
        <code>{args?.query ?? (call.argsText || t("toolCall.generating"))}</code>
      </div>
      {call.status === "calling" && <p className="tool-call-detail-status">{t("toolCall.searching")}</p>}
      {call.status === "retry" && (
        <p className="tool-call-detail-status tool-call-detail-status-warn">
          {t("toolCall.retrying", { msg: call.resultText ?? "" })}
        </p>
      )}
      {result && (
        <>
          <p className="search-result-summary-line">
            {t("toolCall.searchSummary", { total: result.total_results, fetched: result.papers.length })}
          </p>
          {result.papers.length === 0 ? (
            <p className="search-result-empty">{t("toolCall.noHits")}</p>
          ) : (
            <ol className="search-result-papers">
              {result.papers.map((p, i) => (
                <PaperCard key={i} p={p} />
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  );
}

function GetPaperAbstractDetail({ call }: { call: CallRecord }) {
  const t = useT();
  const args = tryParseJson(call.argsText) as { doi?: string } | null;
  const result = call.resultText ? (tryParseJson(call.resultText) as AbstractLookupResultShape | null) : null;
  const sourceLabel =
    result?.source === "semantic_scholar" ? "Semantic Scholar" : result?.source === "openalex" ? "OpenAlex" : result?.source;
  return (
    <div className="tool-call-detail-body">
      <div className="search-result-query">
        <span className="summary-label">DOI</span>
        <code>{args?.doi ?? (call.argsText || t("toolCall.generating"))}</code>
      </div>
      {call.status === "calling" && <p className="tool-call-detail-status">{t("toolCall.lookingUp")}</p>}
      {call.status === "retry" && (
        <p className="tool-call-detail-status tool-call-detail-status-warn">
          {t("toolCall.retrying", { msg: call.resultText ?? "" })}
        </p>
      )}
      {result &&
        (result.abstract ? (
          <>
            <span className="summary-label">{t("toolCall.abstractSource", { source: sourceLabel ?? "" })}</span>
            <p className="search-result-paper-abstract">{result.abstract}</p>
          </>
        ) : (
          <p className="search-result-empty">{result.note || t("toolCall.noAbstract")}</p>
        ))}
    </div>
  );
}

function GenericToolDetail({ call }: { call: CallRecord }) {
  const t = useT();
  return (
    <div className="tool-call-detail-body">
      <pre className="bubble-pre">{t("toolCall.args")}{call.argsText}</pre>
      {call.status === "calling" && <p className="tool-call-detail-status">{t("toolCall.calling")}</p>}
      {call.resultText && <pre className="bubble-pre">{t("toolCall.returns")}{call.resultText}</pre>}
    </div>
  );
}

export function ToolDetailsPanel({ call, onClose }: { call: CallRecord; onClose: () => void }) {
  const t = useT();
  const toolLabelKey = TOOL_LABEL_KEY[call.toolName];
  return (
    <>
      <div className="details-panel-header">
        <div className="details-panel-title">
          <span className="tool-call-single-tool" aria-hidden="true">
            {TOOL_ICONS[call.toolName] ?? "⚙"}
          </span>
          {toolLabelKey ? t(toolLabelKey) : call.toolName}
        </div>
        <button type="button" className="details-panel-close" onClick={onClose} aria-label={t("toolCall.closePanel")}>
          ✕
        </button>
      </div>
      <div className="details-panel-body">
        {call.toolName === "search_scopus" ? (
          <SearchScopusDetail call={call} />
        ) : call.toolName === "get_paper_abstract" ? (
          <GetPaperAbstractDetail call={call} />
        ) : (
          <GenericToolDetail call={call} />
        )}
      </div>
    </>
  );
}
