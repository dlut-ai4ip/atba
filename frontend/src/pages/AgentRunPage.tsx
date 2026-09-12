import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getRunManifest } from "../api";
import { AppShell } from "../components/AppShell";
import { PageOutlineNav } from "../components/PageOutlineNav";
import { StepCard } from "../components/StepCard";
import { Stepper } from "../components/Stepper";
import { ToolDetailsPanel } from "../components/ToolDetailsPanel";
import { useT } from "../i18n";
import { DetailsPanelProvider, useDetailsPanel } from "../lib/DetailsPanelContext";
import { PageOutlineProvider, usePageOutline } from "../lib/PageOutlineContext";
import { parseStageNumber, STAGES } from "../lib/stepStatus";
import type { RunSummary } from "../types";
import { Step1RunPage } from "./Step1RunPage";
import { Step2RunPage } from "./Step2RunPage";
import { Step3RunPage } from "./Step3RunPage";
import { Step4RunPage } from "./Step4RunPage";
import { Step5RunPage } from "./Step5RunPage";
import { Step6RunPage } from "./Step6RunPage";

// The unified shell for design/agent_run.png — the six StepNRunPages each keep their own complete
// state machine (streaming buffers, retries, clarification Q&A, grouping by round... see the
// top-of-file comment in each), and this component is only responsible for the layer they share:
// AppShell (sidebar+header) + Stepper (the top horizontal 6-step progress bar) + StepCard (the card
// shell for the currently active step).
//
// The six steps' independent routes (/runs/:runId/step1 .. step6) are unchanged — all six routes in
// App.tsx point to this same component, just passing a different `step`; this way the existing
// convention of "every step has its own independent, refreshable/shareable URL" is fully preserved,
// only the outer chrome that gets rendered is now unified.
//
// The Stepper needs the status of all 6 steps to draw the complete progress bar, but each panel only
// knows its own step's real-time status — the full status is assembled here from two pieces of
// information: (1) reaching step N implies steps 1..N-1 must all have already passed (each
// Step*Page's _load_inputs/the backend route already validates this, it isn't assumed out of thin air
// here), so they're directly marked "done"; (2) for steps after the currently active one, status can't
// be inferred from position alone — the user could well have clicked back from the Stepper/history
// list to view an earlier step while this run has actually progressed further, in which case those
// later steps shouldn't display as the gray "not started yet" (per user feedback: clicking back to an
// earlier step, later step nodes that clearly have results still showed gray) — so an extra fetch of
// this run's manifest is made (GET /api/runs/{run_id}, including completed_stages — the list of steps
// that have genuinely been persisted to disk, not a guess based on "position is before the current
// step"), and any step appearing in the manifest is also marked "done." When the manifest request
// fails/hasn't come back yet, this step has no effect, falling back to the conservative guess in (1),
// without affecting the page's main functionality.
// The currently active step's status always defers to the real value reported live by
// onStatusChange from the panel (overriding whatever judgment the manifest might otherwise give
// below) — the manifest is only a coarse present/absent signal, no match for the precise status the
// active step reports about itself in real time.
// DetailsPanelProvider wraps the outermost layer — the right-side details panel's (design/
// tool_output_panel.png) "which call is currently selected" state needs to travel all the way from a
// ToolCallEntry buried deep inside StepPanel up to here, where it's rendered into AppShell's
// detailsPanel slot, see the top-of-file comment in lib/DetailsPanelContext.tsx. The inner logic is
// moved into AgentRunPageInner, because useDetailsPanel() must be called within the Provider's
// subtree.
export function AgentRunPage({ step }: { step: number }) {
  return (
    <DetailsPanelProvider>
      <PageOutlineProvider>
        <AgentRunPageInner step={step} />
      </PageOutlineProvider>
    </DetailsPanelProvider>
  );
}

function AgentRunPageInner({ step }: { step: number }) {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const t = useT();
  const [activeStatus, setActiveStatus] = useState<string | null>(null);
  const [activeLoading, setActiveLoading] = useState(false);
  const [manifest, setManifest] = useState<RunSummary | null>(null);
  const { selected, close } = useDetailsPanel();
  const { items: outlineItems, setItems: setOutlineItems } = usePageOutline();

  // Clear the nav first when switching steps — the six step routes share the same AgentRunPage
  // instance (only the step prop changes, it doesn't remount), so the anchor ids left over from the
  // previous step no longer exist in the new step's DOM; without clearing, stale nav items that don't
  // correspond to anything would flash briefly until the new StepPanel's own effect finishes and calls
  // setItems again. The actual new nav items are computed and set by each Step*RunPage inside
  // StepPanel itself — this effect is only responsible for "zeroing it out first."
  useEffect(() => {
    setOutlineItems([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  useEffect(() => {
    if (!runId) return;
    setManifest(null); // Clear the previous run's manifest first when switching runs, to avoid
    // briefly displaying the previous run's progress
    let cancelled = false;
    getRunManifest(runId)
      .then((m) => {
        if (!cancelled) setManifest(m);
      })
      .catch(() => {
        // Fails silently — the manifest is only used for the display optimization of "lighting up
        // later completed steps"; if it can't be fetched, this falls back to the original
        // conservative display of "only look before the current step," without affecting the page's
        // main functionality, so there's no need to show the user an error message.
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const statuses: Partial<Record<number, string | null>> = {};
  for (let s = 1; s < step; s++) statuses[s] = "passed";
  for (const stageName of manifest?.completed_stages ?? []) {
    const n = parseStageNumber(stageName);
    if (n != null) statuses[n] = "passed";
  }
  statuses[step] = activeStatus;

  function handleAdvance() {
    if (!runId || step >= 6) return;
    navigate(`/runs/${runId}/step${step + 1}`, { state: { fresh: true } });
  }

  const stageName = STAGES[step - 1] ? t(STAGES[step - 1].nameKey) : t("agentRun.fallbackStageName", { n: step });

  return (
    <AppShell
      title={stageName}
      subtitle={t("agentRun.runSubtitle", { runId: runId ?? "" })}
      stepper={runId && <Stepper runId={runId} statuses={statuses} runningStep={activeLoading ? step : null} />}
      detailsPanel={selected && <ToolDetailsPanel call={selected} onClose={close} />}
      // Only step 4 needs widening — the candidate theory horizontal cards are fixed-width columns
      // meant for side-by-side comparison, while the other steps are all narrative text meant to be
      // read continuously, for which the 980px readable line width is more suitable, see the comment
      // on the wide prop in AppShell.tsx.
      wide={step === 4}
    >
      <StepCard title={t("agentRun.cardTitle", { n: step, name: stageName })} status={activeStatus} running={activeLoading}>
        <StepPanel step={step} onStatusChange={(s, l) => { setActiveStatus(s); setActiveLoading(l); }} onAdvance={handleAdvance} />
      </StepCard>
      {/* The on-page nav — the user gave feedback "the output is pretty long, can a jump-to nav be
          added," and also specified the exact shape: "collapsed most of the time, titles for quick
          jumping appear only on hover" (the screenshot example: a row of small tick marks on the right
          edge, expanding into a floating card with a full title list on hover). A different mechanism
          from ToolDetailsPanel: it takes up no layout width (fixed-positioned, pinned to the right
          edge of the viewport itself, not participating in .shell's flex layout), and is usually just
          a few minimal tick marks that don't compete with the content for attention; it's hidden only
          when ToolDetailsPanel is open — at that point the user is actively looking at some call's
          details, and doesn't need this nav also competing for visual focus on the right edge, see
          PageOutlineNav.tsx. */}
      {!selected && <PageOutlineNav items={outlineItems} />}
    </AppShell>
  );
}

function StepPanel({
  step,
  onStatusChange,
  onAdvance,
}: {
  step: number;
  onStatusChange: (status: string | null, loading: boolean) => void;
  onAdvance: () => void;
}) {
  switch (step) {
    case 1:
      return <Step1RunPage onStatusChange={onStatusChange} onAdvance={onAdvance} />;
    case 2:
      return <Step2RunPage onStatusChange={onStatusChange} />;
    case 3:
      return <Step3RunPage onStatusChange={onStatusChange} onAdvance={onAdvance} />;
    case 4:
      return <Step4RunPage onStatusChange={onStatusChange} onAdvance={onAdvance} />;
    case 5:
      return <Step5RunPage onStatusChange={onStatusChange} onAdvance={onAdvance} />;
    case 6:
      return <Step6RunPage onStatusChange={onStatusChange} />;
    default:
      return null;
  }
}
