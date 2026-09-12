import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, IS_DEMO, getRunStep1, getRunStep6, streamStep6 } from "../api";
import { ReportView } from "../components/ReportView";
import { TranscriptView } from "../components/TranscriptView";
import { useT } from "../i18n";
import { useAutoScroll } from "../lib/useAutoScroll";
import { useSettings } from "../settings";
import type { Step1Result, Step6Request, Step6Result } from "../types";

interface FreshStartState {
  fresh: true;
}

// This page corresponds to the route /runs/:runId/step6 — no independent input, only accepting
// run_id, with the backend reading all the output from steps 1 through 5 and integrating it into a
// markdown report. **This step is structurally different from the other RunPages**: it isn't
// "structured result + collapsible thinking/tool_call bubbles," the report itself is one continuous
// long document that needs to be read as it's generated — during the live phase, the text accumulated
// from text_delta is fed directly into <ReportView> for real-time rendering, rather than waiting for
// the run to finish before displaying.
//
// **The thinking process still needs to be shown** (this doesn't contradict "the report's full text
// is the display content"): testing found that DeepSeek often has 30-60 seconds of internal thinking
// before it genuinely starts emitting the report body — if there's nothing on screen but a static
// "agent is writing..." message during that time, the user would think it's stuck. Same reasoning as
// the other steps (repeatedly emphasized in TranscriptView.tsx's top-of-file comment: "the thinking
// process should be displayed in real chronological order, it shouldn't be hidden"): this isn't for
// auditing, it's purely so the user can see "it's genuinely working," so it reuses the same thinking
// bubble display as the other pages, no need to invent an extra new component.
interface StepPanelProps {
  onStatusChange?: (status: string | null, loading: boolean) => void;
}

export function Step6RunPage({ onStatusChange }: StepPanelProps) {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { provider, model, reasoningEffort, lang } = useSettings();
  const t = useT();

  const [step1, setStep1] = useState<Step1Result | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);

  const [result, setResult] = useState<Step6Result | null>(null);
  const [liveMarkdown, setLiveMarkdown] = useState("");
  const [liveThinking, setLiveThinking] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const startedFreshForRunId = useRef<string | null>(null);

  const { bottomRef, follow } = useAutoScroll();
  useEffect(() => {
    follow(!loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMarkdown, liveThinking, loading]);

  useEffect(() => {
    if (!runId) return;
    getRunStep1(runId)
      .then(setStep1)
      .catch((e) => setContextError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e)));
  }, [runId]);

  async function callStep6(req: Step6Request) {
    setLoading(true);
    setError(null);
    setLiveMarkdown("");
    setLiveThinking("");
    setResult(null);

    try {
      const r = await streamStep6(req, (event) => {
        // The parameter isn't named t — avoiding a naming collision with the translation function t
        // returned by the component's top-level useT() (see the comment at the same spot in
        // Step3RunPage.tsx).
        if (event.type === "text_delta") {
          setLiveMarkdown((prev) => prev + event.text);
        } else if (event.type === "thinking_delta") {
          setLiveThinking((prev) => prev + event.text);
        }
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleRetry() {
    if (!runId) return;
    await callStep6({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort });
  }

  function handleExport() {
    const markdown = result?.report_markdown;
    if (!markdown) return;
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${t("step6.exportFilenamePrefix")}-${runId}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // First unconditionally tries reading the already-persisted result, and only falls back to
  // genuinely triggering a costly model call when it truly gets a 404 (this run really hasn't run this
  // step yet) and carries the fresh flag — see the reasoning in the comment at the same spot in
  // Step2RunPage.tsx.
  useEffect(() => {
    if (!runId) return;
    setLoadingExisting(true);
    getRunStep6(runId)
      .then((r) => {
        setResult(r);
        setLoadingExisting(false);
      })
      .catch((e) => {
        const state = location.state as FreshStartState | null;
        if (e instanceof ApiError && e.status === 404 && state?.fresh) {
          if (startedFreshForRunId.current === runId) return; // Guards against StrictMode's double call, see the comment where the ref is declared
          startedFreshForRunId.current = runId;
          setLoadingExisting(false);
          navigate(".", { replace: true, state: null });
          void callStep6({ run_id: runId, lang, provider, model, reasoning_effort: reasoningEffort });
        } else {
          setLoadingExisting(false);
          setError(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const lastStatus = result?.status ?? null;
  const displayedMarkdown = result?.report_markdown ?? liveMarkdown;

  useEffect(() => {
    onStatusChange?.(lastStatus, loading);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastStatus, loading]);

  if (loadingExisting) {
    return <p className="landing-sub">{t("common.loadingRun", { runId: runId ?? "" })}</p>;
  }

  return (
    <div className="transcript">
        {step1?.deconstruction && (
          <div className="phenomenon-recap">
            <span className="summary-label">{t("common.phenomenonRecap")}</span>
            <p>{step1.deconstruction.observed_behavior}</p>
          </div>
        )}
        {contextError && <div className="alert alert-block">{t("step3.contextLoadFailed", { msg: contextError })}</div>}

        {loading && (
          // The agent often has a fairly long stretch of internal thinking before emitting the body
          // (testing observed DeepSeek take 30-60 seconds) — if there's no feedback at all on screen
          // during that time, the user would think it's stuck — reusing the same thinking bubble as
          // the other steps lets "it's genuinely working" be visible before the report body even
          // appears, rather than "starting" only counting once the first bit of text shows up.
          <TranscriptView entries={liveThinking ? [{ kind: "thinking", text: liveThinking }] : []} live />
        )}
        {displayedMarkdown && (
          <div className="turn">
            <ReportView markdown={displayedMarkdown} />
            {loading && (
              <div className="thinking-indicator">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
                {t("step6.stillGenerating")}
              </div>
            )}
            {/* This run's statistics — only shown once it has genuinely finished running (not
                during streaming) and the backend has computed the total, see _aggregate_run_usage
                in atba/step6.py: this aggregates the token consumption of the whole run from step 1
                through step 6 (including every round of the step 4/5 loop), not just this one step-6
                report-generation call's own amount. models_used is the deduplicated set of
                provider+model combinations — normally just one (the one selected in Settings), unless
                the user switched provider partway through this run. */}
            {!loading && result?.status === "passed" && result.total_run_usage && (
              <div className="run-usage-summary">
                <span className="summary-label">{t("step6.usageSummaryTitle")}</span>
                <p>{t("step6.usageModel", { models: result.models_used.join(t("common.listSeparator")) })}</p>
                <p>
                  {t("step6.usageTokens", {
                    input: result.total_run_usage.input_tokens.toLocaleString(),
                    output: result.total_run_usage.output_tokens.toLocaleString(),
                    total: result.total_run_usage.total_tokens.toLocaleString(),
                  })}
                </p>
              </div>
            )}
          </div>
        )}
        {loading && !displayedMarkdown && (
          <div className="thinking-indicator">
            <span className="dot" />
            <span className="dot" />
            <span className="dot" />
            {t("step6.runningIndicator")}
          </div>
        )}
        {result && result.status !== "passed" && (
          <div className="alert alert-block">{t("step6.notPassed", { note: result.note })}</div>
        )}
        {error && <div className="alert alert-block">{t("common.requestFailed", { msg: error })}</div>}

        <div className="step-actions-row">
          {lastStatus === "passed" && !loading && (
            <button className="next-step-btn" onClick={handleExport}>
              {t("step6.exportBtn")}
            </button>
          )}
          {/* Hidden in demo mode — retry means re-running the agent, which a static demo build has no
              backend to do; see the top-of-file comment on IS_DEMO in api.ts. */}
          {!IS_DEMO && (lastStatus || error) && !loading && (
            <button className="retry-btn" onClick={handleRetry} title={t("step6.retryBtnTitle")}>
              {t("step6.retryBtn")}
            </button>
          )}
        </div>
        <div ref={bottomRef} />
      </div>
  );
}
