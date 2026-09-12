import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, IS_DEMO, getRunStep1, streamStep1 } from "../api";
import { ClarificationCard } from "../components/ClarificationCard";
import { ResultSummary } from "../components/ResultSummary";
import { TranscriptView } from "../components/TranscriptView";
import { useT } from "../i18n";
import { usePageOutline } from "../lib/PageOutlineContext";
import { parseAuditTrail, type ChatEntry } from "../lib/transcript";
import { useAutoScroll } from "../lib/useAutoScroll";
import { useSettings } from "../settings";
import type { Step1Request, Step1Result } from "../types";

interface Turn {
  result: Step1Result;
  entries: ChatEntry[];
}

interface FreshStartState {
  fresh: true;
  text: string;
}

interface StepPanelProps {
  /** Reports this step's latest status/loading up to AgentRunPage, used for the top Stepper's
      real-time display. */
  onStatusChange?: (status: string | null, loading: boolean) => void;
  /** "Advance to next step" — AgentRunPage decides where to go (switching the active step within the
      same AgentRunPage, not a full-page navigation). */
  onAdvance?: () => void;
}

// This page corresponds to the route /runs/:runId/step1 — every step has its own independent route
// (step 2 is /runs/:runId/step2, and so on), and under the same runId this URL is stable —
// refreshable/shareable/directly reviewable from the history list, not dependent on any React state
// that only lives in memory. The outer page-level chrome (Stepper/StepCard) is now uniformly provided
// by AgentRunPage; this component is only responsible for step 1's own content and state machine.
export function Step1RunPage({ onStatusChange, onAdvance }: StepPanelProps) {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { provider, model, reasoningEffort, lang, maxRetries } = useSettings();
  const t = useT();
  const { setItems: setOutlineItems } = usePageOutline();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The real-time display content for the currently running call, before it settles into a Turn —
  // accumulated from thinking_delta/tool_call_delta; once it finishes (the final event arrives), this
  // is cleared and the authoritative version produced by parseAuditTrail(r.audit_trail) takes over the
  // display.
  const [liveEntries, setLiveEntries] = useState<ChatEntry[]>([]);

  // React StrictMode (enabled in main.tsx) calls the effects of the same mount twice in a row in
  // development, to flush out side effects that don't write a cleanup — firing streamStep1 inside the
  // effect below is a classic "non-idempotent side effect," and two calls would cause the same
  // phenomenon to be genuinely submitted twice, producing two duplicate entries in turns. A ref records
  // "which runId a fresh request has already been fired for" — the two effect calls share the same ref
  // instance, so the second call can recognize "already fired" and skip, unaffected by StrictMode's
  // double call; in production (StrictMode off) this ref only ever gets set once anyway.
  const startedFreshForRunId = useRef<string | null>(null);

  const { bottomRef, follow } = useAutoScroll();
  // liveEntries is put into the dependency array — not just checking whether to scroll when
  // turns/loading change (a new round starting/ending), but checking on every single incremental
  // update of thinking/tool_call too, so "scrolling down along with the streaming output" is
  // continuous rather than jumping only once per whole round; whether it actually scrolls is still
  // decided by useAutoScroll's internal sticky state, so the user manually scrolling up to read other
  // content won't be interrupted by this (see useAutoScroll.ts).
  useEffect(() => {
    follow(!loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns, loading, liveEntries]);

  // replace=true (retry-exclusive): clicking "re-run" should clear the previous result and display
  // fresh, not stack another one below it — turns is cleared before the request is actually fired, so
  // the loading indicator appears in a clean area rather than sitting under the old result; when it's
  // not replace (first submission, answering a needs_clarification follow-up), the original "append a
  // new turn" behavior is kept, since that's genuine multi-turn conversation history that needs to be
  // preserved.
  async function callStep1(req: Step1Request, opts?: { replace?: boolean }) {
    setLoading(true);
    setError(null);
    setLiveEntries([]);
    if (opts?.replace) setTurns([]);

    let thinkingBuf = "";
    let toolCallBuf = "";
    const pushLive = () => {
      const entries: ChatEntry[] = [];
      if (thinkingBuf) entries.push({ kind: "thinking", text: thinkingBuf });
      if (toolCallBuf) entries.push({ kind: "tool_call_raw", toolName: "report_step1_output", text: toolCallBuf });
      setLiveEntries(entries);
    };

    try {
      const r = await streamStep1(req, (event) => {
        if (event.type === "thinking_delta") {
          thinkingBuf += event.text;
          pushLive();
        } else if (event.type === "tool_call_delta") {
          toolCallBuf += event.text;
          pushLive();
        }
        // The "final" event isn't handled here — streamStep1 resolves as soon as it receives it, and
        // the return value below wraps things up uniformly.
      });
      setTurns((prev) => [...prev, { result: r, entries: parseAuditTrail(r.audit_trail) }]);
    } catch (e) {
      setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
    } finally {
      setLoading(false);
      setLiveEntries([]);
    }
  }

  // On entering this page, one of two paths:
  // (a) a brand-new run just submitted from LandingPage (location.state.fresh=true, carrying the
  //     original text) — genuinely fires a streamStep1 call;
  // (b) visiting this URL directly / clicking in from the history list / browser back-forward — this
  //     run has already run on the backend, so this just reads the already-persisted final result for
  //     display, without re-triggering a model call (this is the core behavior of "every step has its
  //     own independent route, so past history can be reviewed").
  useEffect(() => {
    if (!runId) return;
    const state = location.state as FreshStartState | null;
    if (state?.fresh) {
      if (startedFreshForRunId.current === runId) return; // See the ref comment above: guards against StrictMode's duplicate firing
      startedFreshForRunId.current = runId;
      setLoadingExisting(false);
      // Consumes location.state: uses replace to avoid "refreshing this page" or "browser back then
      // forward" reading fresh=true again, which would mistakenly trigger a historical review into
      // resubmitting a model call.
      navigate(".", { replace: true, state: null });
      void callStep1({
        text: state.text,
        run_id: runId,
        lang,
        provider,
        model,
        reasoning_effort: reasoningEffort,
        max_jargon_retries: maxRetries,
      });
    } else {
      setLoadingExisting(true);
      getRunStep1(runId)
        .then((r) => setTurns([{ result: r, entries: parseAuditTrail(r.audit_trail) }]))
        .catch((e) => setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e)))
        .finally(() => setLoadingExisting(false));
    }
    // Only re-decide the entry path when runId changes — changes to provider/lang/maxRetries shouldn't
    // cause a re-fetch/re-submission.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  async function handleAnswer(answer: string) {
    if (!runId) return;
    // The original phenomenon text for the follow-up answer is read back from the first round's
    // result (Step1Result.raw_text echoes the input verbatim) — no need to keep a separate text state
    // in this component.
    const rawText = turns[0]?.result.raw_text ?? "";
    await callStep1({
      text: rawText,
      prior_expectation_hint: answer,
      run_id: runId,
      lang,
      provider,
      model,
      reasoning_effort: reasoningEffort,
      max_jargon_retries: maxRetries,
    });
  }

  // Retry: re-runs step 1 as-is with the same phenomenon, same run_id — not answering a follow-up (no
  // prior_expectation_hint). Purpose: after passed, seeing whether another generation would come out
  // differently (echoing 02_技术附录初稿.md D.7's "stability check: run the same phenomenon multiple
  // times, compare... the degree of variation"); after blocked_agent_error, it's mostly transient
  // failures like network/rate-limit issues, and retrying is the most direct recovery. The same run_id
  // means every retry overwrites the content persisted at runs/<run_id>/step1.json — only the latest
  // one is kept on disk; the display no longer keeps the previous one either (see callStep2's replace
  // option) — clicking retry means "swap in the new result for the old one," not keeping an extra copy
  // for comparison.
  async function handleRetry() {
    if (!runId) return;
    const rawText = turns[0]?.result.raw_text ?? "";
    await callStep1(
      { text: rawText, run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort, max_jargon_retries: maxRetries },
      { replace: true },
    );
  }

  const lastTurn = turns[turns.length - 1];
  const lastStatus = lastTurn?.result.status ?? null;

  useEffect(() => {
    onStatusChange?.(lastStatus, loading);
    // onStatusChange is a new inline closure AgentRunPage passes in on every render — it's not put in
    // the dependency array, so this only reports once when status/loading genuinely change, avoiding
    // triggering an extra effect every time the parent component re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastStatus, loading]);

  // On-page nav — under needs_clarification status, ClarificationCard is displayed, not
  // ResultSummary, and there's no corresponding section to jump to (nor is an id attached, see the
  // JSX below), so items is left empty in this state. lang is deliberately in the dependency array:
  // labels need to refresh when the interface language is switched, for the same reason as the
  // comment at the same spot in Step4RunPage.tsx.
  useEffect(() => {
    const items: { id: string; label: string }[] = [];
    if (lastStatus !== "needs_clarification") {
      const r = lastTurn?.result;
      if (r?.prior_expectation?.identified) items.push({ id: "step1-prior-expectation", label: t("outline.step1.priorExpectation") });
      if (r?.causal_check?.hit) items.push({ id: "step1-causal-check", label: t("outline.step1.causalCheck") });
      if (r?.deconstruction) items.push({ id: "step1-deconstruction", label: t("outline.step1.deconstruction") });
      if (r?.jargon_check) items.push({ id: "step1-jargon-check", label: t("outline.step1.jargonCheck") });
    }
    setOutlineItems(items);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastTurn, lastStatus, lang]);

  if (loadingExisting) {
    return <p className="landing-sub">{t("common.loadingRun", { runId: runId ?? "" })}</p>;
  }

  return (
    <div className="transcript">
        {turns.map((turn, i) => {
          const isLast = i === turns.length - 1;
          const needsClarify = isLast && turn.result.status === "needs_clarification";
          // When the previous round was needs_clarification, this round is "re-run after answering
          // the follow-up"; otherwise it's a plain retry (re-run the same phenomenon as-is) — the two
          // cases have different copy, they can't both be hardcoded to the same sentence.
          const dividerLabel =
            i > 0 && turns[i - 1].result.status === "needs_clarification"
              ? t("step1.dividerClarify")
              : t("step1.dividerRetry");
          return (
            <div className="turn" key={turn.result.run_id + i}>
              {i > 0 && <div className="turn-divider">{dividerLabel}</div>}
              <TranscriptView entries={turn.entries} />
              {needsClarify && turn.result.prior_expectation ? (
                <ClarificationCard prior={turn.result.prior_expectation} loading={loading} onAnswer={handleAnswer} />
              ) : (
                <ResultSummary result={turn.result} idPrefix={isLast ? "step1" : undefined} />
              )}
            </div>
          );
        })}

        {loading && (
          <div className="turn">
            <TranscriptView entries={liveEntries} live />
            <div className="thinking-indicator">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
              {t("step1.runningIndicator")}
            </div>
          </div>
        )}
        {error && <div className="alert alert-block">{t("common.requestFailed", { msg: error })}</div>}

        <div className="step-actions-row">
          {lastStatus === "passed" && !loading && (
            <button className="next-step-btn" onClick={onAdvance}>
              {t("step1.nextBtn")}
            </button>
          )}
          {/* Retry doesn't cover the needs_clarification state — under that state ClarificationCard
              already offers the more specific next-step action of "answer the follow-up," and stacking
              on a generic "retry" button would just leave the user unsure which one to click.
              (lastStatus || error) — retry isn't offered only after "a round has already run"; it
              should also be offered when the request itself fails (no turn exists yet, lastStatus is
              null), otherwise the user gets stuck in front of an error message with no clickable
              action at all (per user feedback). */}
          {/* Hidden in demo mode — retry means re-running the agent, which a static demo build has no
              backend to do; see the top-of-file comment on IS_DEMO in api.ts. */}
          {!IS_DEMO && (lastStatus || error) && lastStatus !== "needs_clarification" && !loading && (
            <button className="retry-btn" onClick={handleRetry} title={t("step1.retryBtnTitle")}>
              {t("step1.retryBtn")}
            </button>
          )}
        </div>
        <div ref={bottomRef} />
      </div>
  );
}
