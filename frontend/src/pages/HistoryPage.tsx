import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listRuns } from "../api";
import { AppShell } from "../components/AppShell";
import { ProgressRing } from "../components/ProgressRing";
import { useT } from "../i18n";
import { parseStageNumber, STAGES } from "../lib/stepStatus";
import type { RunSummary } from "../types";

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// r.last_stage is "the most recent stage a product was genuinely written for" as recorded in the
// backend's manifest.json ("step1".."step6", see save_stage_output/_touch_manifest in
// atba/context_store.py) — not "the stage that has already passed and can advance to the next one";
// the two aren't necessarily the same (e.g. stuck on a step needing clarification/handed off to a
// human, last_stage is still that same step). But this is exactly what's wanted: reviewing history
// should land the user on "where this run is actually stopped," regardless of whether that step
// passed cleanly or got stuck, rather than always starting the review over from step 1 (per user
// feedback, "if it's already done it should jump straight to the step 6 report"). Falls back to step 1
// if the number can't be parsed or is out of the 1-6 range — a defensive fallback that shouldn't
// actually happen.
function lastStepNumber(lastStage: string): number {
  return parseStageNumber(lastStage) ?? 1;
}

// Route /runs — the entry point for "reviewing past history": lists every phenomenon that's been run,
// clicking into one jumps straight to that run's most recently progressed step (see lastStepNumber
// above), a read-only display (doesn't re-trigger any model call, see Step1RunPage).
export function HistoryPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const t = useT();

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <AppShell title={t("history.shellTitle")} subtitle={t("history.shellSubtitle")}>
      <div className="history-header">
        <Link to="/">{t("history.newLink")}</Link>
      </div>

      {error && <div className="alert alert-block">{t("common.loadFailed", { msg: error })}</div>}
      {!runs && !error && <p className="landing-sub">{t("common.loading")}</p>}
      {runs && runs.length === 0 && <p className="landing-sub">{t("history.empty")}</p>}

      <ul className="history-list">
        {runs?.map((r) => {
          const stepN = lastStepNumber(r.last_stage);
          return (
            <li key={r.run_id} className="history-item">
              <Link to={`/runs/${r.run_id}/step${stepN}`}>
                {/* Displays "which step" rather than r.status — r.status only reflects step 1's own
                    status (see the RunSummary comment in types.ts: only present when step1.json
                    exists); a run that's already progressed to step 3/4 would, as long as step 1
                    originally passed cleanly, keep showing "passed" here forever, looking like "the
                    whole run is done" when it might actually still be stuck somewhere in the middle —
                    the user gave feedback that this label was "kind of strange," see the comment on
                    lastStepNumber above; here, the real progress — which step it's reached — is
                    displayed directly. */}
                <span className="history-step-group">
                  <ProgressRing step={stepN} />
                  <span className="history-step">{t("history.stepBadge", { n: stepN, name: t(STAGES[stepN - 1].nameKey) })}</span>
                </span>
                <span className="history-preview">{r.phenomenon_preview || r.run_id}</span>
                <span className="history-time">{formatTime(r.updated_at)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </AppShell>
  );
}
