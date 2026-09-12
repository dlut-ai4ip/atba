import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, IS_DEMO, getRunStep1, getRunStep4, getRunStep5, streamStep5 } from "../api";
import { Step4ResultSummary } from "../components/Step4ResultSummary";
import { Step5ResultSummary } from "../components/Step5ResultSummary";
import { GROUPED_TOOL_NAMES, ToolCallEntry, buildDoiTitleMap } from "../components/ToolCallEntry";
import { TranscriptView } from "../components/TranscriptView";
import { useT } from "../i18n";
import { useDetailsPanel } from "../lib/DetailsPanelContext";
import { usePageOutline } from "../lib/PageOutlineContext";
import { parseAuditTrail, type ChatEntry } from "../lib/transcript";
import { useAutoScroll } from "../lib/useAutoScroll";
import { useLiveTranscript, type LiveSegment } from "../lib/useLiveTranscript";
import { useSettings } from "../settings";
import type { Step1Result, Step4Result, Step5Request, Step5Result } from "../types";

// One phase within one round of the loop (a step 4 revision or a step 5 interrogation) — unlike the
// other pages' Turn, phase/round are required here: a single call to /api/step5/stream may genuinely
// run several rounds of step 5 internally, interleaved with several rounds of step 4 revisions (see
// atba/abductive_loop.py); each phase is its own independent agent run, each with its own complete
// thinking/tool_call trace, and they can't be spliced into one transcript — that would smear together
// "which round's step 4 is revising what, which round's step 5 is interrogating what," making the
// genuine loop process unreadable (the same lesson as the top-of-file comment in TranscriptView.tsx:
// an earlier version got feedback for pulling multiple calls out of their original position and
// merging them for display; this doesn't repeat that mistake).
interface RoundTurn {
  phase: "step4" | "step5";
  round: number;
  result: Step4Result | Step5Result;
  entries: ChatEntry[];
}

interface FreshStartState {
  fresh: true;
}

const PHASE_LABEL_KEY: Record<"step4" | "step5", string> = {
  step4: "step5.phaseStep4",
  step5: "step5.phaseStep5",
};

interface StepPanelProps {
  onStatusChange?: (status: string | null, loading: boolean) => void;
  onAdvance?: () => void;
}

// This page corresponds to the route /runs/:runId/step5. Clicking "run" calls /api/step5/stream,
// which **internally auto-runs the entire step 4/5 loop** (not a single round of interrogation) — when
// the interrogation finds a core-mechanism flaw in the candidate theory, this request internally
// automatically sends it back to step 4 for revision then re-interrogates, looping up to a few rounds
// until it passes or gets escalated to a human, see atba/abductive_loop.py. This page therefore has an
// extra layer of "group the display by round" logic on top of the other RunPages (see the RoundTurn
// type above); the rest (live buffering, retry, advancing to the next step) follows the same pattern
// as Step3RunPage/Step4RunPage.
export function Step5RunPage({ onStatusChange, onAdvance }: StepPanelProps) {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { provider, model, reasoningEffort, lang } = useSettings();
  const t = useT();

  const [step1, setStep1] = useState<Step1Result | null>(null);
  const [step4, setStep4] = useState<Step4Result | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);

  // rounds is the complete loop history produced by **this one click of "run"/"retry"** — unlike the
  // other pages' turns, the "multiple turns = multiple retries" semantics don't apply here; a single
  // loop call by itself can already produce several round entries, and "retry" clears rounds and
  // triggers a brand-new loop (callStep5's replace option), rather than appending onto the end of
  // rounds.
  const [rounds, setRounds] = useState<RoundTurn[]>([]);
  const [finalResult, setFinalResult] = useState<Step5Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Within a single round, thinking and tool calls are interleaved in their real order of arrival (see
  // lib/useLiveTranscript.ts) — this resets on every round_marker/phase_final, and that's deliberate:
  // different rounds are independent agent runs to begin with, and shouldn't interleave with each
  // other (see the RoundTurn/rounds comment above) — "interleaving" only happens within the same
  // round.
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
  const [livePhase, setLivePhase] = useState<{ phase: "step4" | "step5"; round: number } | null>(null);
  const { close: closeDetailsPanel } = useDetailsPanel();
  const { setItems: setOutlineItems } = usePageOutline();

  const startedFreshForRunId = useRef<string | null>(null);

  const { bottomRef, follow } = useAutoScroll();
  useEffect(() => {
    follow(!loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rounds, loading, live.segments, livePhase]);

  useEffect(() => {
    if (!runId) return;
    Promise.all([getRunStep1(runId), getRunStep4(runId)])
      .then(([r1, r4]) => {
        setStep1(r1);
        setStep4(r4);
      })
      .catch((e) => setContextError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e)));
  }, [runId]);

  async function callStep5(req: Step5Request, opts?: { replace?: boolean }) {
    setLoading(true);
    setError(null);
    live.reset();
    setLivePhase(null);
    closeDetailsPanel();
    if (opts?.replace) {
      setRounds([]);
      setFinalResult(null);
    }

    // Accumulates intermediate rounds (phase_final); the last round is replaced directly with the r
    // returned by streamStep5 — r is the loop's genuine final state (including the complete
    // loop_history), which the same round's version in the phase_final event hasn't had a chance to
    // carry yet (see stream_step4_5_loop in atba/abductive_loop.py: loop_history is only attached as a
    // whole once the loop ends).
    const collected: RoundTurn[] = [];

    try {
      const r = await streamStep5(req, (event) => {
        if (event.type === "round_marker") {
          setLivePhase({ phase: event.phase, round: event.round });
          live.reset();
        } else if (event.type === "phase_final") {
          const result = event.result as Step4Result | Step5Result;
          collected.push({
            phase: event.phase,
            round: event.round,
            result,
            entries: parseAuditTrail(result.audit_trail),
          });
          setRounds([...collected]);
          live.reset();
          setLivePhase(null);
        } else if (event.type === "thinking_delta") {
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
      // r is the loop's genuine final-state Step5Result — it replaces the last already-collected step
      // 5 round entry (the same round, just this copy additionally carries the complete loop_history),
      // rather than appending an extra duplicate entry.
      setRounds((prev) => {
        if (prev.length === 0) {
          return [{ phase: "step5", round: r.round_number, result: r, entries: parseAuditTrail(r.audit_trail) }];
        }
        const next = [...prev];
        next[next.length - 1] = { phase: "step5", round: r.round_number, result: r, entries: parseAuditTrail(r.audit_trail) };
        return next;
      });
      setFinalResult(r);
    } catch (e) {
      setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
    } finally {
      setLoading(false);
      live.reset();
      setLivePhase(null);
    }
  }

  async function handleRetry() {
    if (!runId) return;
    await callStep5({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort }, { replace: true });
  }

  // First unconditionally tries reading the already-persisted result, and only falls back to
  // genuinely triggering a costly model call when it truly gets a 404 (this run really hasn't run this
  // step yet) and carries the fresh flag (even more expensive here — a fresh trigger runs the entire
  // step 4/5 loop, making it even more important not to mistakenly trigger it when the result already
  // exists) — see the reasoning in the comment at the same spot in Step2RunPage.tsx.
  useEffect(() => {
    if (!runId) return;
    setLoadingExisting(true);
    getRunStep5(runId)
      .then((r) => {
        setRounds([{ phase: "step5", round: r.round_number, result: r, entries: parseAuditTrail(r.audit_trail) }]);
        setFinalResult(r);
        setLoadingExisting(false);
      })
      .catch((e) => {
        const state = location.state as FreshStartState | null;
        if (e instanceof ApiError && e.status === 404 && state?.fresh) {
          if (startedFreshForRunId.current === runId) return; // Guards against StrictMode's double call, see the comment where the ref is declared
          startedFreshForRunId.current = runId;
          setLoadingExisting(false);
          navigate(".", { replace: true, state: null });
          void callStep5({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort });
        } else {
          setLoadingExisting(false);
          setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const lastStatus = finalResult?.status ?? null;

  useEffect(() => {
    onStatusChange?.(lastStatus, loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastStatus, loading]);

  // On-page nav — step 5 has no concept of "the round currently being displayed" (every round in the
  // step 4/5 loop is its own complete independent agent run, see the top-of-file comment), so the
  // rounds array itself is the entirety of what needs displaying, one nav item per round, using the
  // array index as the id (not the round number: the same round number appears once each under both
  // the step4 and step5 phases, so the number itself isn't unique, only the index is). lang is
  // deliberately in the dependency array, for the same reason as the comment at the same spot in
  // Step4RunPage.tsx.
  useEffect(() => {
    const items: { id: string; label: string }[] = [];
    if (step1?.deconstruction) items.push({ id: "step5-phenomenon-recap", label: t("outline.phenomenonRecap") });
    if (step4?.selected_candidate_name) items.push({ id: "step5-candidate-recap", label: t("outline.step5.candidateRecap") });
    rounds.forEach((rt, i) => {
      items.push({ id: `step5-round-${i}`, label: t("step5.roundHeader", { n: rt.round, phase: t(PHASE_LABEL_KEY[rt.phase]) }) });
    });
    setOutlineItems(items);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step1, step4, rounds, lang]);

  if (loadingExisting) {
    return <p className="landing-sub">{t("common.loadingRun", { runId: runId ?? "" })}</p>;
  }

  return (
    <div className="transcript">
        {step1?.deconstruction && (
          <div className="phenomenon-recap" id="step5-phenomenon-recap">
            <span className="summary-label">{t("common.phenomenonRecap")}</span>
            <p>{step1.deconstruction.observed_behavior}</p>
          </div>
        )}
        {step4?.selected_candidate_name && (
          <div className="phenomenon-recap" id="step5-candidate-recap">
            <span className="summary-label">{t("step5.candidateRecap")}</span>
            <p>{step4.selected_candidate_name}</p>
          </div>
        )}
        {contextError && <div className="alert alert-block">{t("step3.contextLoadFailed", { msg: contextError })}</div>}

        {rounds.map((rt, i) => (
          <div className="turn" key={i}>
            <div className="round-divider" id={`step5-round-${i}`}>
              {t("step5.roundHeader", { n: rt.round, phase: t(PHASE_LABEL_KEY[rt.phase]) })}
            </div>
            <TranscriptView entries={rt.entries} />
            {rt.phase === "step4" ? (
              <Step4ResultSummary result={rt.result as Step4Result} />
            ) : (
              <Step5ResultSummary result={rt.result as Step5Result} />
            )}
          </div>
        ))}

        {loading && (
          <div className="turn">
            {livePhase && (
              <div className="round-divider">
                {t("step5.roundHeaderInProgress", { n: livePhase.round, phase: t(PHASE_LABEL_KEY[livePhase.phase]) })}
              </div>
            )}
            {/* Within a single round, thinking and tool calls render interleaved in their real order
                of arrival, see the reasoning in the comment at the same spot in Step3RunPage.tsx. The
                final tool call (report_step4_output for step 4, report_step5_output for step 5) —
                the same single-bubble "structured result being generated" display as Step3RunPage/
                Step4RunPage, not grouped */}
            {live.segments.map((seg) =>
              seg.kind === "thinking" ? (
                <TranscriptView key={seg.key} entries={[{ kind: "thinking", text: seg.text }]} live />
              ) : GROUPED_TOOL_NAMES.has(seg.call.toolName) ? (
                <ToolCallEntry key={seg.key} call={seg.call} live titleByDoi={liveTitleByDoi} />
              ) : (
                <div className="bubble bubble-tool" key={seg.key}>
                  <div className="bubble-label">
                    ⚙ {t("transcript.callSkill")} · <code>{seg.call.toolName}</code>
                  </div>
                  <div className="bubble-sub">
                    {seg.call.toolName === "report_step4_output" ? t("step5.revisionSubLabel") : t("stages.5")}
                  </div>
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
              {t("step5.runningIndicator")}
            </div>
          </div>
        )}
        {error && <div className="alert alert-block">{t("common.requestFailed", { msg: error })}</div>}

        <div className="step-actions-row">
          {lastStatus === "passed" && !loading && (
            <button className="next-step-btn" onClick={onAdvance}>
              {t("step5.nextBtn")}
            </button>
          )}
          {/* Hidden in demo mode — retry means re-running the agent, which a static demo build has no
              backend to do; see the top-of-file comment on IS_DEMO in api.ts. */}
          {!IS_DEMO && (lastStatus || error) && !loading && (
            <button className="retry-btn" onClick={handleRetry} title={t("step5.retryBtnTitle")}>
              {t("step5.retryBtn")}
            </button>
          )}
        </div>
        <div ref={bottomRef} />
      </div>
  );
}
