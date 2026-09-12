import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, IS_DEMO, getRunStep1, getRunStep2, getRunStep3, streamStep3 } from "../api";
import { Step3ResultSummary } from "../components/Step3ResultSummary";
import { GROUPED_TOOL_NAMES, ToolCallEntry, buildDoiTitleMap } from "../components/ToolCallEntry";
import { TranscriptView } from "../components/TranscriptView";
import { useT } from "../i18n";
import { useDetailsPanel } from "../lib/DetailsPanelContext";
import { usePageOutline } from "../lib/PageOutlineContext";
import { parseAuditTrail, type ChatEntry } from "../lib/transcript";
import { useAutoScroll } from "../lib/useAutoScroll";
import { useLiveTranscript, type LiveSegment } from "../lib/useLiveTranscript";
import { useSettings } from "../settings";
import type { Step1Result, Step2Result, Step3Request, Step3Result } from "../types";

interface Turn {
  result: Step3Result;
  entries: ChatEntry[];
}

interface FreshStartState {
  fresh: true;
}

interface StepPanelProps {
  onStatusChange?: (status: string | null, loading: boolean) => void;
  onAdvance?: () => void;
}

// This page corresponds to the route /runs/:runId/step3 — the same pattern as Step2RunPage (see its
// comment): no independent input, only accepting run_id, with the backend reading step 1's
// phenomenon card + step 2's user-confirmed candidate directions itself. This page additionally
// fetches steps 1 and 2's results, purely to display "which phenomenon, which directions are currently
// being examined" to the user.
export function Step3RunPage({ onStatusChange, onAdvance }: StepPanelProps) {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { provider, model, reasoningEffort, lang } = useSettings();
  const t = useT();

  const [step1, setStep1] = useState<Step1Result | null>(null);
  const [step2, setStep2] = useState<Step2Result | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Thinking and tool calls are interleaved in their real order of arrival (see
  // lib/useLiveTranscript.ts) — not accumulated into two separate buckets of "all thinking together,
  // all calls together," which would break apart the genuine "thinking→call→thinking→call..." order
  // during streaming; the user gave feedback that "the thinking process and tool display are
  // separated, it doesn't match the timeline."
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
  // Closes the right-side details panel (design/tool_output_panel.png) on re-run — otherwise the panel
  // might still be sitting on some call from the previous round that's already been cleared, the same
  // timing and reasoning as live.reset().
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
    Promise.all([getRunStep1(runId), getRunStep2(runId)])
      .then(([r1, r2]) => {
        setStep1(r1);
        setStep2(r2);
      })
      .catch((e) => setContextError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e)));
  }, [runId]);

  // replace=true (retry-exclusive): same as Step1RunPage/Step2RunPage's callStepN — clicking "re-run"
  // should clear the previous display, not stack a new one below it. A single step 3 task calls
  // search_scopus many times, so the volume of thinking/tool_call incremental events is much larger
  // than the first two steps — this is expected behavior, not getting stuck.
  async function callStep3(req: Step3Request, opts?: { replace?: boolean }) {
    setLoading(true);
    setError(null);
    live.reset();
    closeDetailsPanel();
    if (opts?.replace) setTurns([]);

    try {
      const r = await streamStep3(req, (event) => {
        if (event.type === "thinking_delta") {
          live.pushThinking(event.text);
        } else if (event.type === "tool_call_delta") {
          // tool_name isn't necessarily repeated on every delta (it usually only appears in the first
          // event); when absent, this falls back to the tool_name already recorded for this call_id.
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
    await callStep3({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort }, { replace: true });
  }

  // First unconditionally tries reading the already-persisted result, and only falls back to
  // genuinely triggering a costly model call when it truly gets a 404 (this run really hasn't run this
  // step yet) and carries the fresh flag — not "seeing the fresh flag and just running, regardless of
  // whether this step has already run." This fixes the waste reported by the user: reviewing an
  // already-completed historical run via a forward action like "next step" shouldn't be forced to
  // re-run just because of the fresh flag. See the detailed reasoning in the comment at the same spot
  // in Step2RunPage.tsx.
  useEffect(() => {
    if (!runId) return;
    setLoadingExisting(true);
    getRunStep3(runId)
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
          void callStep3({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort });
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

  // On-page nav — lang is deliberately in the dependency array, for the same reason as the comment at
  // the same spot in Step4RunPage.tsx. Whether each section appears is conditional, matched
  // item-for-item against Step3ResultSummary.tsx's "this block renders only when this field has a
  // value" logic.
  useEffect(() => {
    const items: { id: string; label: string }[] = [];
    if (step1?.deconstruction) items.push({ id: "step3-phenomenon-recap", label: t("outline.phenomenonRecap") });
    if (step2 && step2.selected_theory_directions.length > 0) {
      items.push({ id: "step3-confirmed-directions", label: t("outline.step3.confirmedDirections") });
    }
    const r = lastTurn?.result;
    if (r?.research_question) items.push({ id: "step3-research-question", label: t("outline.step3.researchQuestion") });
    if (r?.anchor_theory_grounding) items.push({ id: "step3-anchor-grounding", label: t("outline.step3.anchorGrounding") });
    if (r?.cross_source_tension_note) items.push({ id: "step3-cross-source-tension", label: t("outline.step3.crossSourceTension") });
    if (r?.coverage_report) items.push({ id: "step3-coverage-report", label: t("outline.step3.coverageReport") });
    if (r?.rationale) items.push({ id: "step3-rationale", label: t("outline.step3.rationale") });
    if (r && r.examined_directions.length > 0) items.push({ id: "step3-examined-directions", label: t("outline.step3.examinedDirections") });
    setOutlineItems(items);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step1, step2, lastTurn, lang]);

  if (loadingExisting) {
    return <p className="landing-sub">{t("common.loadingRun", { runId: runId ?? "" })}</p>;
  }

  return (
    <div className="transcript">
        {step1?.deconstruction && (
          <div className="phenomenon-recap" id="step3-phenomenon-recap">
            <span className="summary-label">{t("common.phenomenonRecap")}</span>
            <p>{step1.deconstruction.observed_behavior}</p>
          </div>
        )}
        {step2 && step2.selected_theory_directions.length > 0 && (
          <div className="phenomenon-recap" id="step3-confirmed-directions">
            <span className="summary-label">
              {t("step3.confirmedDirections", { n: step2.selected_theory_directions.length })}
            </span>
            <p>{step2.selected_theory_directions.map((d) => d.theory_name).join(t("common.listSeparator"))}</p>
          </div>
        )}
        {contextError && <div className="alert alert-block">{t("step3.contextLoadFailed", { msg: contextError })}</div>}

        {turns.map((turn, i) => (
          <div className="turn" key={turn.result.run_id + i}>
            {i > 0 && <div className="turn-divider">{t("step3.retryDivider")}</div>}
            <TranscriptView entries={turn.entries} />
            <Step3ResultSummary result={turn.result} idPrefix={i === turns.length - 1 ? "step3" : undefined} />
          </div>
        ))}

        {loading && (
          <div className="turn">
            {/* Thinking and tool calls render interleaved in their real order of arrival (see
                lib/useLiveTranscript.ts) — not displayed separately as "all thinking together, all
                calls together," which would break apart the genuine
                "thinking→call→thinking→call..." order during streaming. The thinking bubble reuses
                TranscriptView's existing rendering, without reimplementing the collapsible bubble
                styling; the D.4 retrieval tools (search_scopus/get_paper_abstract) go through
                ToolCallEntry (one independent bubble per call); the final report_step3_output keeps
                the single-bubble "structured result being generated" style. */}
            {live.segments.map((seg) =>
              seg.kind === "thinking" ? (
                <TranscriptView key={seg.key} entries={[{ kind: "thinking", text: seg.text }]} live />
              ) : GROUPED_TOOL_NAMES.has(seg.call.toolName) ? (
                <ToolCallEntry key={seg.key} call={seg.call} live titleByDoi={liveTitleByDoi} />
              ) : (
                <div className="bubble bubble-tool" key={seg.key}>
                  <div className="bubble-label">
                    ⚙ {t("transcript.callSkill")} · <code>report_step3_output</code>
                  </div>
                  <div className="bubble-sub">{t("stages.3")}</div>
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
              {t("step3.runningIndicator")}
            </div>
          </div>
        )}
        {error && <div className="alert alert-block">{t("common.requestFailed", { msg: error })}</div>}

        <div className="step-actions-row">
          {/* Only when a research question was genuinely produced (status=passed) can step 4 be
              entered — neither no_gap_found nor retrieval_unavailable has a usable
              research_question, and step 4's _load_inputs would refuse to run on a run without a
              research_question; the frontend doesn't show this entry point, avoiding a 400 error
              discovered only after clicking. */}
          {lastStatus === "passed" && !loading && (
            <button className="next-step-btn" onClick={onAdvance}>
              {t("step3.nextBtn")}
            </button>
          )}
          {/* Hidden in demo mode — retry means re-running the agent, which a static demo build has no
              backend to do; see the top-of-file comment on IS_DEMO in api.ts. */}
          {!IS_DEMO && (lastStatus || error) && !loading && (
            <button className="retry-btn" onClick={handleRetry} title={t("step3.retryBtnTitle")}>
              {t("step3.retryBtn")}
            </button>
          )}
          {/* This entry point is also shown on error — step 3's most common cause of a 404 is
              "arriving directly at this URL without going through the fresh flow after selecting
              directions in step 2," and in that case "going back to step 2 to reselect" is usually a
              better fit than "retrying in place." */}
          {runId && (lastStatus || error) && !loading && (
            <Link className="retry-btn" to={`/runs/${runId}/step2`}>
              {t("step3.backToStep2")}
            </Link>
          )}
        </div>
        <div ref={bottomRef} />
      </div>
  );
}
