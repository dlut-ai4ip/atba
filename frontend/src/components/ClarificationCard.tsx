import { useState } from "react";
import { useT } from "../i18n";
import type { PriorExpectationIdentification } from "../types";

// The human-in-the-loop prompt card: when there isn't enough information to judge a prior expectation,
// the agent gives a specific question + candidate options, rendered here as an interactive card that's
// clickable or free-text fillable; the answer is resubmitted with the same run_id (not started over).
export function ClarificationCard({
  prior,
  loading,
  onAnswer,
}: {
  prior: PriorExpectationIdentification;
  loading: boolean;
  onAnswer: (answer: string) => void;
}) {
  const [custom, setCustom] = useState("");
  const t = useT();

  return (
    <div className="clarify-card">
      <div className="clarify-head">{t("clarify.head")}</div>
      <p className="clarify-question">{prior.clarifying_question}</p>
      {prior.candidate_options.length > 0 && (
        <div className="chip-row">
          {prior.candidate_options.map((opt) => (
            <button key={opt} type="button" className="chip" disabled={loading} onClick={() => onAnswer(opt)}>
              {opt}
            </button>
          ))}
        </div>
      )}
      <div className="clarify-freetext">
        <input
          type="text"
          placeholder={t("clarify.freetextPlaceholder")}
          value={custom}
          disabled={loading}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && custom.trim()) onAnswer(custom.trim());
          }}
        />
        <button type="button" disabled={loading || !custom.trim()} onClick={() => onAnswer(custom.trim())}>
          {t("clarify.submit")}
        </button>
      </div>
    </div>
  );
}
