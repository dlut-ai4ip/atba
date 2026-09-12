// The small ring progress indicator used in the history list — the horizontal Stepper at the top of
// design/agent_run.png doesn't fit in a dense one-row-per-item list like the history list (six nodes +
// connecting lines is too wide); the ring is a compact substitute carrying the same information ("how
// far through the 6 steps"), letting a glance across a batch of runs show which went further and which
// just started, without having to read "step N" text on each line to compare.
//
// Pure SVG, no <progress> element — <progress>'s native browser styling is a horizontal bar, with no
// easy way to make it a ring; two concentric circles here (one stroked as the track, one clipped by
// stroke-dasharray into an arc for the completed portion) is the standard CSS/SVG ring-progress
// pattern, no need to pull in a charting library (it's just drawing one ring, not worth a whole
// charting dependency).
export function ProgressRing({ step, total = 6, size = 20 }: { step: number; total?: number; size?: number }) {
  const strokeWidth = 2.5;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  // Clamped — step is in principle always 1..total (see lastStepNumber in HistoryPage.tsx); this is
  // just a defensive fallback, so an unexpected input value doesn't draw a ring with a negative offset
  // or more than one full turn.
  const progress = Math.max(0, Math.min(1, step / total));
  const offset = circumference * (1 - progress);
  const center = size / 2;
  // Having finished all 6 steps swaps the accent color for --ok (the same green used elsewhere for
  // "passed," e.g. ToolCallEntry's ✓ icon) — letting a glance across a row of rings pick out which runs
  // genuinely finished everything, without having to zoom in and count segments/read the in-step text.
  // Note this only reflects "all 6 steps have produced output" (last_stage=step6, see
  // lastStepNumber), not that step 6 itself has status=passed — that would need reading step6.json's
  // status field, which this history-list layer doesn't have, and doesn't need that level of detail.
  const complete = step >= total;

  return (
    <svg
      className={`progress-ring${complete ? " progress-ring-complete" : ""}`}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`${step}/${total}`}
    >
      <circle className="progress-ring-track" cx={center} cy={center} r={radius} strokeWidth={strokeWidth} fill="none" />
      <circle
        className="progress-ring-fill"
        cx={center}
        cy={center}
        r={radius}
        strokeWidth={strokeWidth}
        fill="none"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        // Starts drawing from the 12-o'clock position (SVG's default 0 degrees is at 3 o'clock) — the
        // conventional orientation for progress-bar/clock-style ring indicators.
        transform={`rotate(-90 ${center} ${center})`}
      />
    </svg>
  );
}
