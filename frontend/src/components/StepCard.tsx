import type { ReactNode } from "react";
import { useT } from "../i18n";

// The card shell for each step in design/agent_run.png — a purely presentational container with no
// business logic. Each of the six StepNRunPage's content (the thinking/tool-call timeline, follow-up
// questions, candidate-direction checkboxes, etc.) drops straight into children as-is; this layer only
// handles the shared title bar (status icon + title + "approved" tag), an optional action-button row,
// and the card's border/corner radius. Class names correspond one-to-one with the hand-written
// .step-card* rules in App.css — changing one side always means checking the other (see the comment on
// the "StepCard — the card shell for each 'Step N: ...' in design/agent_run.png" section in App.css).
export function StepCard({
  title,
  status,
  running,
  pending,
  actions,
  children,
}: {
  title: string;
  status?: string | null;
  running?: boolean;
  /** This step's turn hasn't come yet (e.g. step 5 while step 4 hasn't finished) — displayed
   * de-emphasized/translucent, but still renders a placeholder title. */
  pending?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const t = useT();
  const done = status === "passed";
  return (
    <section className={`step-card${pending ? " step-card-pending" : ""}`}>
      <header className="step-card-header">
        <span
          className={`step-card-status-icon${done ? " step-card-status-done" : ""}${running ? " step-card-status-running" : ""}`}
          aria-hidden="true"
        >
          {done ? "✓" : running ? "◐" : ""}
        </span>
        <h2 className="step-card-title">{title}</h2>
        {done && <span className="step-card-approved-tag">✓ {t("stepCard.approved")}</span>}
      </header>
      {actions && <div className="step-card-actions">{actions}</div>}
      <div className="step-card-body">{children}</div>
    </section>
  );
}

export function StepCardActionButton({
  children,
  onClick,
  primary,
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      className={`step-card-action-btn${primary ? " step-card-action-primary" : ""}`}
      onClick={onClick}
      disabled={disabled}
      type="button"
    >
      {children}
    </button>
  );
}
