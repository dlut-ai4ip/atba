import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, IS_DEMO, getRunStep1, getRunStep2, selectStep2Directions, streamStep2 } from "../api";
import { Step2ResultSummary } from "../components/Step2ResultSummary";
import { TranscriptView } from "../components/TranscriptView";
import { useT } from "../i18n";
import { usePageOutline } from "../lib/PageOutlineContext";
import { parseAuditTrail, type ChatEntry } from "../lib/transcript";
import { useAutoScroll } from "../lib/useAutoScroll";
import { useSettings } from "../settings";
import type { Step1Result, Step2Request, Step2Result } from "../types";

interface Turn {
  result: Step2Result;
  entries: ChatEntry[];
}

interface FreshStartState {
  fresh: true;
}

interface StepPanelProps {
  onStatusChange?: (status: string | null, loading: boolean) => void;
}

// This page corresponds to the route /runs/:runId/step2 — the same pattern as Step1RunPage (see its
// comment), the difference being that step 2 has no independent phenomenon text input: its only input
// is step 1's output, so entering this page also fetches step 1's result to display "the current
// phenomenon" to the user. "Advance to the next step" isn't a simple navigation — the checked
// directions need to be persisted first (handleConfirmSelection) — so this doesn't need the onAdvance
// passed in by AgentRunPage; after the selection is successfully confirmed, it navigates to step 3
// itself, letting step 3's corresponding AgentRunPage instance remount.
export function Step2RunPage({ onStatusChange }: StepPanelProps) {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { provider, model, reasoningEffort, lang } = useSettings();
  const t = useT();
  const { setItems: setOutlineItems } = usePageOutline();

  const [step1, setStep1] = useState<Step1Result | null>(null);
  const [step1Error, setStep1Error] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [liveEntries, setLiveEntries] = useState<ChatEntry[]>([]);

  // The set of indices the user checked on the candidate theoretical direction cards — indices
  // correspond to the subscripts of lastTurn.result.candidate_theory_directions. This is
  // re-initialized every time a fresh step-2 result comes in (first run/retry/reading a persisted
  // result on page refresh): if this result already carries a previously saved
  // selected_theory_directions (backfilling the corresponding indices by theory_name), it means the
  // user selected something before; otherwise it starts from an empty set. Not stored in a ref/
  // localStorage — selected_theory_directions itself is the persistence layer, and the frontend state
  // is just a mirror of what's currently being edited.
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [confirmingSelection, setConfirmingSelection] = useState(false);

  // Same as Step1RunPage: guards against StrictMode's development-mode double effect calls causing
  // streamStep2 to be genuinely submitted twice.
  const startedFreshForRunId = useRef<string | null>(null);

  const { bottomRef, follow } = useAutoScroll();
  useEffect(() => {
    follow(!loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns, loading, liveEntries]);

  // Re-initializes the checked state every time turns changes (a new round of results arrives):
  // - If this round already had a specific selection saved before (selected_theory_directions is
  //   non-empty), the corresponding indices are backfilled by theory_name — not simply assuming order/
  //   subscripts stay the same, since the candidate list's order and content can both change after a
  //   retry; matching by name is more robust than matching by subscript.
  // - If nothing has been saved yet (the first time this round's result is seen), everything is
  //   selected by default — sparing the user from having to click each one; if they want to exclude a
  //   direction they can manually uncheck it. "Select all" is just the frontend display's default
  //   value, it doesn't mean the backend considers this "the user's choice" — the actual choice isn't
  //   written back to step2.json until the user clicks "confirm selection."
  useEffect(() => {
    const last = turns[turns.length - 1];
    if (!last) return;
    if (last.result.selected_theory_directions.length > 0) {
      const selectedNames = new Set(last.result.selected_theory_directions.map((d) => d.theory_name));
      const indices = new Set<number>();
      last.result.candidate_theory_directions.forEach((d, i) => {
        if (selectedNames.has(d.theory_name)) indices.add(i);
      });
      setSelectedIndices(indices);
    } else {
      setSelectedIndices(new Set(last.result.candidate_theory_directions.map((_, i) => i)));
    }
  }, [turns]);

  function toggleSelection(index: number) {
    setSelectedIndices((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  // Confirm selection: persists the checked candidate directions (the full objects, not indices) to
  // runs/<run_id>/step2.json, then navigates to step 3 carrying fresh=true — the same "fresh flag
  // triggers a real call" pattern used by LandingPage→Step1RunPage and the "enter step 2" link (see
  // Step3RunPage's effect). Step 3's input is only run_id (both the phenomenon card and the selected
  // directions are read from the backend, no need to pass raw text via state like step 1 does), so no
  // data needs to be carried in state here.
  async function handleConfirmSelection() {
    if (!runId) return;
    const last = turns[turns.length - 1];
    if (!last) return;
    const selected = [...selectedIndices]
      .sort((a, b) => a - b)
      .map((i) => last.result.candidate_theory_directions[i]);
    setConfirmingSelection(true);
    setError(null);
    try {
      await selectStep2Directions(runId, { selected_theory_directions: selected });
      navigate(`/runs/${runId}/step3`, { state: { fresh: true } });
    } catch (e) {
      setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
    } finally {
      setConfirmingSelection(false);
    }
  }

  useEffect(() => {
    if (!runId) return;
    getRunStep1(runId)
      .then(setStep1)
      .catch((e) => setStep1Error(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e)));
  }, [runId]);

  // replace=true (retry-exclusive): the same as Step1RunPage's callStep1 — clicking "re-run" should
  // clear the previous display, not stack a new one below it.
  async function callStep2(req: Step2Request, opts?: { replace?: boolean }) {
    setLoading(true);
    setError(null);
    setLiveEntries([]);
    if (opts?.replace) setTurns([]);

    let thinkingBuf = "";
    let toolCallBuf = "";
    const pushLive = () => {
      const entries: ChatEntry[] = [];
      if (thinkingBuf) entries.push({ kind: "thinking", text: thinkingBuf });
      if (toolCallBuf) entries.push({ kind: "tool_call_raw", toolName: "report_step2_output", text: toolCallBuf });
      setLiveEntries(entries);
    };

    try {
      const r = await streamStep2(req, (event) => {
        if (event.type === "thinking_delta") {
          thinkingBuf += event.text;
          pushLive();
        } else if (event.type === "tool_call_delta") {
          toolCallBuf += event.text;
          pushLive();
        }
      });
      setTurns((prev) => [...prev, { result: r, entries: parseAuditTrail(r.audit_trail) }]);
    } catch (e) {
      setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
    } finally {
      setLoading(false);
      setLiveEntries([]);
    }
  }

  // Retry: re-runs step 2 as-is with the same run_id — step 2 has no independent text input to begin
  // with, so "retry" and "first run" use the same request body, differing only in whether this is the
  // first call. Same as Step1RunPage's handleRetry: every retry overwrites runs/<run_id>/step2.json,
  // only the latest one is kept on disk; the display also replaces the old result with the new one
  // rather than keeping them side by side.
  async function handleRetry() {
    if (!runId) return;
    await callStep2({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort }, { replace: true });
  }

  // On entering this page, it **first unconditionally tries reading the already-persisted result**,
  // and only falls back to genuinely triggering a costly model call when it truly can't be read (404,
  // meaning this run genuinely hasn't run this step yet) and carries the fresh flag — not like the
  // earlier version's "see the fresh flag and just run, without checking at all whether this step has
  // already run."
  //
  // This change fixes a real source of waste: when the user arrives via a forward action like the
  // "next step" button/"confirm selection," AgentRunPage.handleAdvance/handleConfirmSelection below
  // have always carried fresh=true; but if the user is reviewing a historical run that already finished
  // all six steps long ago (e.g. clicking back to some middle step from the Stepper/history list, then
  // clicking "next step" to page forward again), this step actually already has a result, and shouldn't
  // be forced to re-run just because of the fresh flag — this is exactly the user feedback of "clicking
  // next step should load the already-run result, not re-run it."
  //
  // An exception (honestly documented, not a bug): if the user goes back to step 2, **changes** the
  // checked candidate directions, and clicks "confirm selection" again, this will still only
  // auto-rerun step 3 when it has "never run" — if step 3 happens to already have a result
  // (corresponding to the old selection), that old result is shown first, and it won't automatically
  // detect that it's stale just because the selection changed. This scenario of "going back to change
  // an earlier step's selection" is itself rarer, and there's currently no downstream
  // auto-invalidation mechanism either (steps 4 through 6 don't automatically clear just because step 2
  // changed) — after changing the selection, the user clicking "retry" on step 3 themselves will
  // re-run it with the newly saved selection; this isn't a data error, it just doesn't happen
  // automatically and needs a manual click.
  useEffect(() => {
    if (!runId) return;
    setLoadingExisting(true);
    getRunStep2(runId)
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
          void callStep2({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort });
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
  // the same spot in Step4RunPage.tsx.
  useEffect(() => {
    const items: { id: string; label: string }[] = [];
    if (step1?.deconstruction) items.push({ id: "step2-phenomenon-recap", label: t("outline.phenomenonRecap") });
    if (lastTurn?.result.candidate_theory_directions.length) items.push({ id: "step2-directions", label: t("outline.step2.directions") });
    setOutlineItems(items);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step1, lastTurn, lang]);

  if (loadingExisting) {
    return <p className="landing-sub">{t("common.loadingRun", { runId: runId ?? "" })}</p>;
  }

  return (
    <div className="transcript">
        {step1?.deconstruction && (
          <div className="phenomenon-recap" id="step2-phenomenon-recap">
            <span className="summary-label">{t("common.phenomenonRecap")}</span>
            <p>{step1.deconstruction.observed_behavior}</p>
          </div>
        )}
        {step1Error && <div className="alert alert-block">{t("common.priorStepLoadFailed", { n: 1, msg: step1Error })}</div>}

        {/* Step 2 has no needs_clarification-style multi-turn follow-up, and retry replaces rather
            than appends (see callStep2's replace option), so turns here has at most one entry — no
            need to handle turn-divider the way Step1RunPage does. */}
        {turns.map((turn, i) => {
          const isLast = i === turns.length - 1;
          // Checkboxes are only enabled for the latest round, and only when it genuinely passed — a
          // failed round has no candidate directions to select, and earlier rounds in history
          // (shouldn't actually occur since retry is replace not append, but turns is still typed as
          // an array) shouldn't be interactive either, avoiding the user checking boxes against a
          // stale candidate list.
          const selectable = isLast && turn.result.status === "passed";
          return (
            <div className="turn" key={turn.result.run_id + i}>
              <TranscriptView entries={turn.entries} />
              <Step2ResultSummary
                result={turn.result}
                selectable={selectable}
                selectedIndices={selectable ? selectedIndices : undefined}
                onToggle={selectable ? toggleSelection : undefined}
                idPrefix={isLast ? "step2" : undefined}
              />
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
              {t("step2.runningIndicator")}
            </div>
          </div>
        )}
        {error && <div className="alert alert-block">{t("common.requestFailed", { msg: error })}</div>}

        <div className="step-actions-row">
          {lastStatus === "passed" && !loading && (
            <button
              className="next-step-btn"
              disabled={selectedIndices.size === 0 || confirmingSelection}
              onClick={handleConfirmSelection}
            >
              {confirmingSelection
                ? t("step2.saving")
                : t("step2.confirmBtn", { n: selectedIndices.size })}
            </button>
          )}
          {/* Hidden in demo mode — retry means re-running the agent, which a static demo build has no
              backend to do; see the top-of-file comment on IS_DEMO in api.ts. */}
          {!IS_DEMO && (lastStatus || error) && !loading && (
            <button className="retry-btn" onClick={handleRetry} title={t("step2.retryBtnTitle")}>
              {t("step2.retryBtn")}
            </button>
          )}
        </div>
        <div ref={bottomRef} />
      </div>
  );
}
