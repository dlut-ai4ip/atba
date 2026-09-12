import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, IS_DEMO, getRunStep1, getRunStep3, getRunStep4, streamStep4 } from "../api";
import { Step4ResultSummary } from "../components/Step4ResultSummary";
import { GROUPED_TOOL_NAMES, ToolCallEntry, buildDoiTitleMap } from "../components/ToolCallEntry";
import { TranscriptView } from "../components/TranscriptView";
import { useT } from "../i18n";
import { useDetailsPanel } from "../lib/DetailsPanelContext";
import { usePageOutline } from "../lib/PageOutlineContext";
import { parseAuditTrail, type ChatEntry } from "../lib/transcript";
import { useAutoScroll } from "../lib/useAutoScroll";
import { useLiveTranscript, type LiveSegment } from "../lib/useLiveTranscript";
import { useSettings } from "../settings";
import type { Step1Result, Step3Result, Step4Request, Step4Result } from "../types";

interface Turn {
  result: Step4Result;
  entries: ChatEntry[];
}

interface FreshStartState {
  fresh: true;
}

interface StepPanelProps {
  onStatusChange?: (status: string | null, loading: boolean) => void;
  onAdvance?: () => void;
}

// This page corresponds to the route /runs/:runId/step4 — the same pattern as Step3RunPage (see its
// comment): no independent input, only accepting run_id, with the backend reading step 1's
// phenomenon card + step 3's research question itself. This page additionally fetches steps 1 and 3's
// results, purely to display "which research question theories are currently being constructed for"
// to the user.
//
// **This page only triggers one round (round_number=1) of candidate generation** — the revision rounds
// triggered by step 5's loop don't go through this page/this endpoint; that happens automatically
// inside the backend after clicking "run" on the step 5 page, see Step5RunPage.tsx and
// atba/abductive_loop.py. Clicking "retry" on this page still only regenerates round_number=1
// candidates (a brand-new start, not "continuing from the last revision round").
export function Step4RunPage({ onStatusChange, onAdvance }: StepPanelProps) {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { provider, model, reasoningEffort, lang } = useSettings();
  const t = useT();

  const [step1, setStep1] = useState<Step1Result | null>(null);
  const [step3, setStep3] = useState<Step3Result | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Thinking and tool calls are interleaved in their real order of arrival (see
  // lib/useLiveTranscript.ts), not accumulated into two separate buckets.
  const live = useLiveTranscript();
  // get_paper_abstract only shows a DOI, which is hard to recognize — a doi→title lookup table is
  // built on the fly from the search_scopus results that have already streamed in so far (see
  // buildDoiTitleMap in ToolCallEntry.tsx) — live.segments grows incrementally with streaming, and this
  // is recomputed along with it each time, no need to wait for this round of streaming to finish.
  const liveTitleByDoi = useMemo(
    () =>
      buildDoiTitleMap(
        live.segments.filter((s): s is Extract<LiveSegment, { kind: "tool_call" }> => s.kind === "tool_call").map((s) => s.call),
      ),
    [live.segments],
  );
  const { close: closeDetailsPanel } = useDetailsPanel();
  const { setItems: setOutlineItems } = usePageOutline();

  const startedFreshForRunId = useRef<string | null>(null);

  const { bottomRef, follow } = useAutoScroll();
  useEffect(() => {
    follow(!loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns, loading, live.segments]);

  useEffect(() => {
    if (!runId) return;
    Promise.all([getRunStep1(runId), getRunStep3(runId)])
      .then(([r1, r3]) => {
        setStep1(r1);
        setStep3(r3);
      })
      .catch((e) => setContextError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e)));
  }, [runId]);

  async function callStep4(req: Step4Request, opts?: { replace?: boolean }) {
    setLoading(true);
    setError(null);
    live.reset();
    closeDetailsPanel();
    if (opts?.replace) setTurns([]);

    try {
      const r = await streamStep4(req, (event) => {
        if (event.type === "thinking_delta") {
          live.pushThinking(event.text);
        } else if (event.type === "tool_call_delta") {
          live.upsertToolCall(event.call_id, (existing) =>
            existing
              ? { ...existing, argsText: existing.argsText + event.text, toolName: event.tool_name ?? existing.toolName }
              : { callId: event.call_id, toolName: event.tool_name ?? "", argsText: event.text, status: "calling" },
          );
        } else if (event.type === "tool_result") {
          live.upsertToolCall(event.call_id, (existing) =>
            existing
              ? { ...existing, status: "done", resultText: event.content }
              : { callId: event.call_id, toolName: "", argsText: "", status: "done", resultText: event.content },
          );
        } else if (event.type === "tool_result_retry") {
          live.upsertToolCall(event.call_id, (existing) =>
            existing
              ? { ...existing, status: "retry", resultText: event.text }
              : { callId: event.call_id, toolName: "", argsText: "", status: "retry", resultText: event.text },
          );
        }
      });
      setTurns((prev) => [...prev, { result: r, entries: parseAuditTrail(r.audit_trail) }]);
    } catch (e) {
      setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
    } finally {
      setLoading(false);
      live.reset();
    }
  }

  async function handleRetry() {
    if (!runId) return;
    await callStep4({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort }, { replace: true });
  }

  // First unconditionally tries reading the already-persisted result, and only falls back to
  // genuinely triggering a costly model call when it truly gets a 404 (this run really hasn't run this
  // step yet) and carries the fresh flag — see the reasoning in the comment at the same spot in
  // Step2RunPage.tsx.
  useEffect(() => {
    if (!runId) return;
    setLoadingExisting(true);
    getRunStep4(runId)
      .then((r) => {
        setTurns([{ result: r, entries: parseAuditTrail(r.audit_trail) }]);
        setLoadingExisting(false);
      })
      .catch((e) => {
        const state = location.state as FreshStartState | null;
        if (e instanceof ApiError && e.status === 404 && state?.fresh) {
          if (startedFreshForRunId.current === runId) return; // Guards against StrictMode's double call, see the comment where the ref is declared
          startedFreshForRunId.current = runId;
          setLoadingExisting(false);
          navigate(".", { replace: true, state: null });
          void callStep4({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort });
        } else {
          setLoadingExisting(false);
          setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const lastTurn = turns[turns.length - 1];
  const lastStatus = lastTurn?.result.status ?? null;

  useEffect(() => {
    onStatusChange?.(lastStatus, loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastStatus, loading]);

  // On-page nav (PageOutlineNav.tsx, per user feedback "the output is pretty long, add a jump-to nav")
  // — anchors are only attached to "the round currently being displayed" (lastTurn, the last round
  // when there have been multiple manual retries); the "step4" id prefix must match the idPrefix
  // passed when Step4ResultSummary.tsx renders this turn (see the JSX below), otherwise a nav item
  // would be clicked but find no matching id. Whether each section appears is conditional
  // (mechanism_grounding could be null, selection_rationale could be an empty string, etc.), matched
  // item-for-item against Step4ResultSummary.tsx's "this block renders only when this field has a
  // value" logic — it must not be assumed in reverse that they always exist, otherwise a nav item
  // could be clicked with no corresponding content, or content could exist with no corresponding nav
  // item — either way inconsistent.
  useEffect(() => {
    const items: { id: string; label: string }[] = [];
    if (step1?.deconstruction) items.push({ id: "step4-phenomenon-recap", label: t("outline.phenomenonRecap") });
    if (step3?.research_question) items.push({ id: "step4-research-question-recap", label: t("outline.step4.researchQuestion") });
    const r = lastTurn?.result;
    if (r?.mechanism_grounding) items.push({ id: "step4-mechanism-grounding", label: t("outline.step4.mechanismGrounding") });
    if (r?.selection_rationale) items.push({ id: "step4-selection-rationale", label: t("outline.step4.selectionRationale") });
    if (r && r.pairwise_comparisons.length > 0) items.push({ id: "step4-pairwise-comparisons", label: t("outline.step4.pairwiseComparisons") });
    if (r && r.candidates.length > 0) items.push({ id: "step4-candidates", label: t("outline.step4.candidates") });
    setOutlineItems(items);
    // lang is deliberately in the dependency array — when the interface language is switched, the
    // labels returned by t() need to refresh along with it; this effect shouldn't have to wait for
    // step1/step3/lastTurn's own data to change before re-running.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step1, step3, lastTurn, lang]);

  if (loadingExisting) {
    return <p className="landing-sub">{t("common.loadingRun", { runId: runId ?? "" })}</p>;
  }

  return (
    <div className="transcript">
        {step1?.deconstruction && (
          <div className="phenomenon-recap" id="step4-phenomenon-recap">
            <span className="summary-label">{t("common.phenomenonRecap")}</span>
            <p>{step1.deconstruction.observed_behavior}</p>
          </div>
        )}
        {step3?.research_question && (
          <div className="phenomenon-recap" id="step4-research-question-recap">
            <span className="summary-label">{t("step4.researchQuestionRecap")}</span>
            <p>{step3.research_question}</p>
          </div>
        )}
        {contextError && <div className="alert alert-block">{t("step3.contextLoadFailed", { msg: contextError })}</div>}

        {turns.map((turn, i) => (
          <div className="turn" key={turn.result.run_id + i}>
            {i > 0 && <div className="turn-divider">{t("step4.retryDivider")}</div>}
            <TranscriptView entries={turn.entries} />
            {/* idPrefix is only given to the last round — the on-page nav's anchor ids (see the
                setOutlineItems effect above) only recognize these fixed "step4-*" ids, and when
                multiple rounds appear on the same page, the same id can't be attached to every round
                (invalid HTML, getElementById would only find the first one) — an old retry round
                that's been superseded in history doesn't need to be reachable from the nav. */}
            <Step4ResultSummary result={turn.result} idPrefix={i === turns.length - 1 ? "step4" : undefined} />
          </div>
        ))}

        {loading && (
          <div className="turn">
            {/* Thinking and tool calls render interleaved in their real order of arrival, see the
                reasoning in the comment at the same spot in Step3RunPage.tsx. */}
            {live.segments.map((seg) =>
              seg.kind === "thinking" ? (
                <TranscriptView key={seg.key} entries={[{ kind: "thinking", text: seg.text }]} live />
              ) : GROUPED_TOOL_NAMES.has(seg.call.toolName) ? (
                <ToolCallEntry key={seg.key} call={seg.call} live titleByDoi={liveTitleByDoi} />
              ) : (
                <div className="bubble bubble-tool" key={seg.key}>
                  <div className="bubble-label">
                    ⚙ {t("transcript.callSkill")} · <code>report_step4_output</code>
                  </div>
                  <div className="bubble-sub">{t("stages.4")}</div>
                  <details className="bubble-details">
                    <summary>
                      {t("transcript.generating")}
                      <span className="thinking-live-dots">
                        <span className="dot" />
                        <span className="dot" />
                        <span className="dot" />
                      </span>
                    </summary>
                    <pre className="bubble-pre">{seg.call.argsText}</pre>
                  </details>
                </div>
              ),
            )}
            <div className="thinking-indicator">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
              {t("step4.runningIndicator")}
            </div>
          </div>
        )}
        {error && <div className="alert alert-block">{t("common.requestFailed", { msg: error })}</div>}

        <div className="step-actions-row">
          {lastStatus === "passed" && !loading && (
            <button className="next-step-btn" onClick={onAdvance}>
              {t("step4.nextBtn")}
            </button>
          )}
          {/* Hidden in demo mode — retry means re-running the agent, which a static demo build has no
              backend to do; see the top-of-file comment on IS_DEMO in api.ts. */}
          {!IS_DEMO && (lastStatus || error) && !loading && (
            <button className="retry-btn" onClick={handleRetry} title={t("step4.retryBtnTitle")}>
              {t("step4.retryBtn")}
            </button>
          )}
        </div>
        <div ref={bottomRef} />
      </div>
  );
}
