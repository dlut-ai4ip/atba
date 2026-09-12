import { useEffect } from "react";
import { useT } from "../i18n";
import { useDetailsPanel } from "../lib/DetailsPanelContext";

// D.4's retrieval tools (search_scopus/get_paper_abstract) are different from steps 1/2/3's own final
// output tools (report_stepN_output): they can be called many times within one run, so they can't be
// displayed as "one call = one flat bubble" the way the final-output tools are — but they also
// shouldn't be pulled out of the position they actually occurred in and stitched into one big widget at
// the end (an earlier version did this: testing found thinking/text interleaved between batches of
// calls, and forcing them into one widget would scramble the real order of "model thinks → calls →
// thinks → calls ...," turning it into "a pile of thinking crammed at the front, a pile of calls
// crammed at the end," losing the real alternating reasoning-retrieval process).

// Each call is rendered in place as its own single-line summary, arranged naturally alongside the
// thinking/text bubbles in audit_trail's original order (not pulled out, not merged, see
// pairToolCalls() in TranscriptView.tsx and the live usage in Step3RunPage.tsx). **This line no longer
// expands on its own** — the interaction of clicking to see the result has moved to a persistent
// details sidebar on the right (design/tool_output_panel.png, per user feedback that "clicking a tool
// call's result should show it in a sidebar on the right"), see the ToolCallEntry component below and
// lib/DetailsPanelContext.tsx / components/ToolDetailsPanel.tsx.
export const GROUPED_TOOL_NAMES = new Set(["search_scopus", "get_paper_abstract"]);

export interface CallRecord {
  callId: string;
  toolName: string;
  argsText: string;
  status: "calling" | "done" | "retry";
  resultText?: string;
}

export const TOOL_ICONS: Record<string, string> = {
  search_scopus: "🔍",
  get_paper_abstract: "📄",
};

export const TOOL_LABEL_KEY: Record<string, string> = {
  search_scopus: "toolCall.searchLabel",
  get_paper_abstract: "toolCall.abstractLabel",
};

const STATUS_ICON: Record<CallRecord["status"], string> = {
  calling: "◐",
  done: "✓",
  retry: "⚠",
};

export function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// DOI comparison is case-insensitive and trims whitespace (the DOI spec itself is case-insensitive,
// but search_scopus/get_paper_abstract occasionally don't agree exactly on casing) — normalized into
// this key format before being inserted into/looked up in the map, avoiding a usability problem where
// "the title exists but a casing difference makes the lookup miss."
function normalizeDoiKey(doi: string): string {
  return doi.trim().toLowerCase();
}

// get_paper_abstract's call arguments only carry a doi, and the tool's own return value
// (AbstractLookupResult) doesn't carry a title either (the two open sources atba/retrieval.py uses for
// this endpoint only give an abstract + authors, see that file's docstring) — the only source for a
// title is an earlier search_scopus call's result in the same transcript (ScopusSearchResult.papers
// has title+doi on every entry). This builds a doi→title lookup table on the fly from search_scopus
// calls that already have results, scanning resultText and pulling titles from the papers list, no
// extra request needed. Added after user feedback that "showing just the DOI when querying an abstract
// is hard to recognize" — this is purely a frontend-display-layer stitch, it doesn't affect the
// persisted CitedEvidence itself (that title is separately filled in by the model when it claims a
// citation, independent of this table).
export function buildDoiTitleMap(calls: CallRecord[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (const call of calls) {
    if (call.toolName !== "search_scopus" || !call.resultText) continue;
    const result = tryParseJson(call.resultText) as { papers?: unknown } | null;
    if (!Array.isArray(result?.papers)) continue;
    for (const paper of result.papers) {
      const p = paper as { doi?: unknown; title?: unknown };
      if (typeof p.doi === "string" && typeof p.title === "string" && p.doi) {
        map[normalizeDoiKey(p.doi)] = p.title;
      }
    }
  }
  return map;
}

// Not a component, so it has no access to useT(); the caller passes t in (same as toolLabel() in
// TranscriptView.tsx).
function callSummaryLabel(call: CallRecord, t: (key: string) => string, titleByDoi?: Record<string, string>): string {
  const args = tryParseJson(call.argsText) as Record<string, unknown> | null;
  if (call.toolName === "search_scopus" && typeof args?.query === "string") {
    const q = args.query.replace(/\s+/g, " ").trim();
    return q.length > 40 ? q.slice(0, 40) + "…" : q;
  }
  if (call.toolName === "get_paper_abstract" && typeof args?.doi === "string") {
    const title = titleByDoi?.[normalizeDoiKey(args.doi)];
    return title ? `${title}（${args.doi}）` : args.doi;
  }
  return call.argsText ? call.argsText.slice(0, 40) : t("toolCall.generating");
}

// A single call's in-place summary line — clicking it hands this call off to the right-hand details
// panel (useDetailsPanel().open), no longer a local <details> expanding in place. The call prop keeps
// getting swapped for a new object with the same callId during streaming (see upsertToolCall in
// useLiveTranscript.ts): if this happens to be the currently selected call with the panel already
// open, its content needs to keep updating along with the stream (e.g. search_scopus going from
// "retrieving" to having a result) — it can't just take a snapshot the moment it's clicked and stop
// updating after that. The effect below is what handles this: whenever the call prop changes and this
// is the selected item, it actively calls open() again with the new snapshot to push it into the
// Context.
//
// **This sync only runs when live=true** — hit a real pitfall here once: for an already-completed
// round (TranscriptView.tsx's pairToolCalls()), the display array gets recomputed on every parent
// re-render, freshly constructing CallRecord objects in place (no memoization, so the call reference
// differs on every render even with identical content); if the subscription to call-reference changes
// weren't split by live/non-live, an already-completed call that's still selected would loop: "call
// reference changes → effect reruns → open(new reference) → setSelected → triggers a parent re-render
// → pairToolCalls produces an updated reference again → ..." (this really flooded the console with
// "Maximum update depth exceeded" in testing). An already-completed call's data will never change
// again, so opening it once at the moment of the click is enough — it doesn't need this effect
// continuously chasing updates; only a call that's genuinely receiving live incremental updates
// (live=true, see Step3/4/5RunPage.tsx's live.segments) needs this effect.
export function ToolCallEntry({
  call,
  live,
  titleByDoi,
}: {
  call: CallRecord;
  live?: boolean;
  // The paper title looked up by DOI for a get_paper_abstract call (from an earlier search_scopus
  // result in the same transcript, see buildDoiTitleMap) — the caller computes the whole table from
  // its own full call list and passes it in; this component itself only sees a single call, and can't
  // compute this table on its own. Falls back to showing just the DOI when this is missing (e.g. no
  // search_scopus result exists yet).
  titleByDoi?: Record<string, string>;
}) {
  const t = useT();
  const { selected, open } = useDetailsPanel();
  const toolLabelKey = TOOL_LABEL_KEY[call.toolName];
  const isActive = selected?.callId === call.callId;

  useEffect(() => {
    if (live && isActive) open(call);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call, isActive, live]);

  return (
    <button
      type="button"
      className={`bubble bubble-tool-call-single tool-call-status-${call.status}${isActive ? " tool-call-single-active" : ""}`}
      onClick={() => open(call)}
    >
      <span className="tool-call-single-icon">{STATUS_ICON[call.status]}</span>
      <span className="tool-call-single-tool">{TOOL_ICONS[call.toolName] ?? "⚙"}</span>
      {toolLabelKey ? t(toolLabelKey) : call.toolName} · {callSummaryLabel(call, t, titleByDoi)}
      {live && call.status === "calling" && (
        <span className="thinking-live-dots">
          <span className="dot" />
          <span className="dot" />
          <span className="dot" />
        </span>
      )}
    </button>
  );
}
