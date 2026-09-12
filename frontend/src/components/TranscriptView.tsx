import { useMemo } from "react";
import { useT } from "../i18n";
import { Markdown } from "./Markdown";
import { GROUPED_TOOL_NAMES, ToolCallEntry, buildDoiTitleMap, type CallRecord } from "./ToolCallEntry";
import type { ChatEntry } from "../lib/transcript";

// The tool names for each step's final structured output (see the corresponding STEPN_TOOL_NAME in
// atba/stepN.py, explicitly specified via pydantic_ai.ToolOutput, not pydantic-ai's default
// "final_result") — D.4's retrieval tools (search_scopus/get_paper_abstract) aren't listed here, they
// go through pairToolCalls() and render in place as a ToolCallEntry, not a flat bubble (see that
// component's top-of-file comment: a single run may call them many times, each call gets its own
// collapsible bubble rendered in place, not pulled out and merged).
const TOOL_LABEL_KEY: Record<string, string> = {
  report_step1_output: "transcript.tool.step1",
  report_step2_output: "transcript.tool.step2",
  report_step3_output: "transcript.tool.step3",
};

// A plain function, not a component, so it can't call the useT() hook internally — the caller
// (inside a component) computes t() and passes it in.
function toolLabel(toolName: string, t: (key: string) => string): string {
  const key = TOOL_LABEL_KEY[toolName];
  return key ? t(key) : toolName;
}

type DisplayEntry = ChatEntry | { kind: "tool_call_single"; call: CallRecord };

// Takes the flat ChatEntry list parseAuditTrail produces, and pairs up D.4 retrieval tool
// (search_scopus/get_paper_abstract) calls' tool_call+tool_return by callId into a single CallRecord,
// placed at the position the tool_call originally appeared — not pulled out and merged into one
// separate widget (an earlier version did this: pulling several calls out of their original positions
// and mashing them into one big widget scrambles the real alternating order of "thinking → call →
// thinking → call ...," turning it into "a pile of thinking crammed at the front, calls crammed at the
// end," losing the real reasoning process — this was reported as feedback). thinking/text and other
// entries stay exactly where they were, unaffected — this keeps the whole transcript in
// audit_trail's original chronological order.
function pairToolCalls(entries: ChatEntry[]): DisplayEntry[] {
  const display: DisplayEntry[] = [];
  const byCallId = new Map<string, CallRecord>();

  entries.forEach((entry, i) => {
    if (entry.kind === "tool_call" && GROUPED_TOOL_NAMES.has(entry.toolName)) {
      const record: CallRecord = {
        callId: entry.callId || `noid-${i}`,
        toolName: entry.toolName,
        argsText: typeof entry.args === "string" ? entry.args : JSON.stringify(entry.args),
        status: "calling",
      };
      byCallId.set(record.callId, record);
      display.push({ kind: "tool_call_single", call: record });
    } else if (entry.kind === "tool_return" && GROUPED_TOOL_NAMES.has(entry.toolName) && byCallId.has(entry.callId)) {
      // record is a reference type, so the {call: record} already pushed into display above
      // automatically reflects this update — there's no need, and it wouldn't be right, to insert
      // another "return" entry into display; the call and its return are two halves of the same
      // event to begin with.
      const record = byCallId.get(entry.callId);
      if (record) {
        record.status = "done";
        record.resultText = entry.content;
      }
    } else {
      display.push(entry);
    }
  });
  return display;
}

export function TranscriptView({ entries, live }: { entries: ChatEntry[]; live?: boolean }) {
  // Memoized — without this, every parent re-render would freshly construct a new batch of
  // CallRecord objects in place (same content, different references). ToolCallEntry.tsx's
  // details-panel sync effect only depends on call-reference changes when live=true, so it's already
  // unaffected by this, but this is still memoized on entries anyway, to avoid rebuilding the entire
  // display array from scratch on every unrelated re-render of an already-completed round — pure
  // performance hygiene, not the actual defense the bug fix in this file relies on.
  const display = useMemo(() => pairToolCalls(entries), [entries]);
  // An already-completed transcript gets every call at once, and doesn't need to incrementally
  // recompute like live does — just pull every tool_call_single's call out of display and build the
  // doi→title table once, see buildDoiTitleMap in ToolCallEntry.tsx.
  const titleByDoi = useMemo(
    () => buildDoiTitleMap(display.filter((e): e is Extract<DisplayEntry, { kind: "tool_call_single" }> => e.kind === "tool_call_single").map((e) => e.call)),
    [display],
  );
  return (
    <>
      {display.map((entry, i) =>
        entry.kind === "tool_call_single" ? (
          <ToolCallEntry key={i} call={entry.call} titleByDoi={titleByDoi} />
        ) : (
          <TranscriptEntry key={i} entry={entry} live={live} />
        ),
      )}
    </>
  );
}

function TranscriptEntry({ entry, live }: { entry: ChatEntry; live?: boolean }) {
  const t = useT();
  switch (entry.kind) {
    case "user":
      // This text is itself in Markdown format (## headings, ordered lists, etc. — see _task_text()
      // in atba/step3.py); it used to be dropped straight into a <div> as plain text, so syntax
      // markers like "##" and "1." would display as literal characters, hard to read.
      return (
        <div className="bubble bubble-user">
          <div className="bubble-label">{t("transcript.phenomenonInput")}</div>
          <Markdown text={entry.text} />
        </div>
      );
    case "thinking":
      // Expanded by default while live (this piece of thinking is currently streaming), so the user
      // can watch it being generated as they read; once this piece of thinking finishes (no longer
      // live — usually swapped out for the final version parsed by parseAuditTrail(), which is a
      // completely different React node from the live buffer, so there's no risk of "clobbering the
      // user's manual collapse state," see the discussion in the same batch of changes as
      // useAutoScroll.ts), it's collapsed by default to save space — historical thinking is still
      // meant to be clicked open to read, not sprawled open every time.
      return (
        <details className="bubble bubble-thinking" open={live}>
          <summary>
            {t("transcript.thinking")}
            {live && (
              <span className="thinking-live-dots">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </span>
            )}
          </summary>
          <pre className="bubble-pre">{entry.text}</pre>
        </details>
      );
    case "tool_call_raw":
      // report_stepN_output isn't a side-effecting "call" — it's pydantic-ai's mechanism for forcing
      // the model to package its answer into a structured result; the JSON here is essentially the
      // model's final answer for this step's task, the same data as what's laid out in
      // ResultSummary. Collapsed by default, the raw JSON is there for anyone who wants to check the
      // details.
      return (
        <div className="bubble bubble-tool">
          <div className="bubble-label">
            ⚙ {t("transcript.callSkill")} · <code>{entry.toolName}</code>
          </div>
          <div className="bubble-sub">{toolLabel(entry.toolName, t)}</div>
          <details className="bubble-details">
            <summary>
              {t("transcript.generating")}
              <span className="thinking-live-dots">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </span>
            </summary>
            <pre className="bubble-pre">{entry.text}</pre>
          </details>
        </div>
      );
    case "text":
      // Free text the agent produces (step 3 occasionally emits a short passage between rounds of
      // retrieval, per real DeepSeek samples) can also carry Markdown syntax (lists/bold/etc.), so it
      // goes through Markdown rendering too, no longer shown as plain text.
      return (
        <div className="bubble bubble-assistant">
          <Markdown text={entry.text} />
        </div>
      );
    case "tool_call":
      // Same as above: this JSON is the model's final answer, already laid out once by
      // ResultSummary, so it's collapsed by default here, left for anyone who wants to check "what
      // did the model's raw output actually look like." Only report_stepN_output ever reaches this
      // branch — search_scopus/get_paper_abstract have already been intercepted by pairToolCalls()
      // and never fall through to here.
      return (
        <div className="bubble bubble-tool">
          <div className="bubble-label">
            ⚙ {t("transcript.callSkill")} · <code>{entry.toolName}</code>
          </div>
          <div className="bubble-sub">{toolLabel(entry.toolName, t)}</div>
          <details className="bubble-details">
            <summary>{t("transcript.viewFullJson")}</summary>
            <pre className="bubble-pre">{JSON.stringify(entry.args, null, 2)}</pre>
          </details>
        </div>
      );
    case "tool_return":
      // Same as above, this normally shouldn't be reached — kept as a defensive fallback (e.g. some
      // tool_return that failed to pair with its tool_call, which the grouping logic would let
      // through as a plain entry), not the main path.
      return (
        <div className="bubble bubble-tool-return">
          ✓ <code>{entry.toolName}</code> {t("transcript.returned")}{entry.content}
        </div>
      );
    case "retry":
      // entry.text is pydantic-ai's raw retry-prompt content — on a validation failure this is
      // almost always one whole block of JSON error detail with the full input echoed back (see the
      // output_validator in atba/step4.py and the other steps, where ModelRetry messages routinely
      // include the full error structure, so the model can read exactly what went wrong). This used
      // to be displayed flattened, and this kind of JSON often runs to hundreds of lines, pushing
      // later thinking/results far down and making them hard to find (user feedback of "there's
      // something to display here" was pointing at exactly this). Changed to the same default-
      // collapsed <details> treatment as "complete structured result (JSON)"/"structured result being
      // generated" — this "validation failed" status line itself is short and stays visible; only the
      // full error JSON is tucked into the collapsed section, to be opened by anyone who wants to
      // check exactly what failed validation.
      return (
        <div className="bubble bubble-retry">
          <div className="bubble-label">{t("transcript.retryLabel")}</div>
          <details className="bubble-details">
            <summary>{t("transcript.viewRetryDetail")}</summary>
            <pre className="bubble-pre">{entry.text}</pre>
          </details>
        </div>
      );
    case "raw":
      return (
        <details className="bubble bubble-raw">
          <summary>{t("transcript.rawOther")}</summary>
          <pre className="bubble-pre">{entry.text}</pre>
        </details>
      );
  }
}
