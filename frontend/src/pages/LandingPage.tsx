import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { useT } from "../i18n";
import { useSettings } from "../settings";

// Mapping from thinking-effort tier → i18n key — the list of legal tier values itself comes from the
// backend's /api/health (deepseek_reasoning_efforts/openai_reasoning_efforts, see
// DEEPSEEK_REASONING_EFFORTS/OPENAI_REASONING_EFFORTS in atba/agent_streaming.py); this only handles
// "given a tier string, what human-readable sentence to show," it doesn't redefine which tiers are
// legal (avoiding the two sides' criteria going out of sync — if the backend ever changes the set of
// selectable tiers, a tier missing from this mapping falls back to displaying the raw string directly,
// rather than crashing or showing blank just because "a switch branch was missed"). One shared map
// covers both providers' tiers ("minimal" is OpenAI-only, "xhigh"/"max" are DeepSeek-only) since the
// tier names themselves never collide between the two.
const REASONING_EFFORT_LABEL_KEY: Record<string, string> = {
  minimal: "landing.reasoningEffort.minimal",
  low: "landing.reasoningEffort.low",
  medium: "landing.reasoningEffort.medium",
  high: "landing.reasoningEffort.high",
  xhigh: "landing.reasoningEffort.xhigh",
  max: "landing.reasoningEffort.max",
};

// The phenomenon_input_text for weiss_radoynovska_2026 in the retrodiction validation set, original
// source at 提案初稿/回溯验证测试集.json (per project convention, the dataset itself only stores the
// Chinese original, see CLAUDE.md's "substantive content is written in Chinese") — this lets a real
// test case exercise the end-to-end pipeline right away, instead of typing something out by hand every
// time. The textarea is still editable; this is just the default value. What's prefilled under the
// English UI is this Chinese text's English translation — the source itself doesn't have two language
// versions; the dataset's/retrodiction validation's ground truth still recognizes only this one
// Chinese original.
const DEFAULT_TEST_CASE = {
  label: "Weiss & Radoynovska (2026)",
  text: {
    zh: "硅谷的科技创业公司创始人经常需要向投资人讲述公司高速增长的故事来吸引资源，这种带有夸张、选择性描述色彩的'讲故事'，在创业圈里通常被认为是正常甚至被默许的做法。但对2000年到2023年间因证券欺诈被起诉的一批硅谷创业公司的法庭卷宗进行分析后发现：其中一部分创始人的做法已经超出了单纯'讲故事'的范围——他们伪造历史财务数据、编造根本不存在的产品演示、虚构客户合同，甚至让员工配合一起演戏，营造出一个跟企业真实经营状况完全脱节的假象。而且，这种造假的精细程度，会随着'投资人对公司的预期'和'公司真实表现'之间差距的扩大而不断升级。",
    en: "Silicon Valley startup founders routinely need to tell investors a story of rapid growth to attract resources — this kind of exaggerated, selectively framed 'storytelling' is generally seen as normal, even tacitly condoned, within the startup world. But an analysis of court records from Silicon Valley startups prosecuted for securities fraud between 2000 and 2023 found that some founders' conduct went well beyond mere 'storytelling': they fabricated historical financial data, staged product demos for products that didn't actually exist, invented customer contracts, and even coached employees to play along — constructing a false picture entirely disconnected from the company's real state. Moreover, the sophistication of this fabrication escalates as the gap between investors' expectations of the company and its actual performance widens.",
  },
};

// design/input.png's new skin — the outer layer changed from a standalone centered card to being
// nested inside AppShell (sharing the same sidebar/header as the other pages); the content area itself
// is still the same form, with the fields/submit logic completely unchanged, just wrapped in a
// different visual container: an extra "character count" line at the top of the card, the submit
// button moved from directly below the form to the card footer's right side, and when non-empty an
// extra "ready" hint banner is shown (pure visual feedback, doesn't affect submit logic).
export function LandingPage() {
  const navigate = useNavigate();
  const { provider, model, setModel, reasoningEffort, setReasoningEffort, health, lang } = useSettings();
  const [text, setText] = useState(DEFAULT_TEST_CASE.text[lang]);
  const t = useT();

  // The interface language reuses settings.tsx's global lang toggle (the same toggle also decides the
  // prompt language, see the top-of-file comment in i18n/index.ts) — if the user switches language on
  // this page, the prefilled default example also needs to switch to the text in the corresponding
  // language, it shouldn't be left showing the previous language's text. But this only replaces it
  // while the text is still equal to "the default example in the other language" (i.e. the user hasn't
  // edited it by hand yet); once the user has changed the textarea's content, this effect no longer
  // overwrites it, respecting the user's input.
  useEffect(() => {
    setText((prev) =>
      prev === DEFAULT_TEST_CASE.text.zh || prev === DEFAULT_TEST_CASE.text.en ? DEFAULT_TEST_CASE.text[lang] : prev,
    );
  }, [lang]);

  // The model dropdown — currently only has one real option per provider: that provider's currently
  // configured default model itself (health.providers.<provider>, falling back to a hardcoded value
  // when health hasn't come back yet, so the dropdown isn't empty while the request is in flight).
  // Selecting it has the same effect as not selecting it — this dropdown itself is scaffolding prepared
  // for when there are more model options in the future, not a genuine multiple-choice scenario right
  // now. Anthropic has no dropdown at all (see the JSX below) — model/reasoning-effort are only
  // meaningful for DeepSeek and OpenAI, see the top-of-file comment on REASONING_EFFORT_LABEL_KEY.
  const currentProviderModel =
    provider === "openai" ? health?.providers.openai ?? "gpt-5" : health?.providers.deepseek ?? "deepseek-v4-flash";
  const currentProviderModelLabel = provider === "openai" ? "OpenAI GPT-5" : "DeepSeek V4 Flash";
  const reasoningEfforts =
    provider === "openai"
      ? health?.openai_reasoning_efforts ?? ["minimal", "low", "medium", "high"]
      : health?.deepseek_reasoning_efforts ?? ["low", "medium", "high", "xhigh", "max"];

  function handleStart(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    // run_id is generated right here (client-side) instead of waiting on the backend to return one —
    // this way the URL is deterministic and directly shareable/refreshable from the moment of
    // submission, without waiting for the first streaming event to come back before knowing which
    // route to jump to. The format is kept consistent with the backend's new_run_id() in
    // atba/context_store.py (uuid4().hex), so both sides agree.
    const runId = crypto.randomUUID().replaceAll("-", "");
    // Navigates over carrying text and a "fresh" flag via location.state — when AgentRunPage/the
    // Step 1 panel sees fresh=true, it knows this is a brand-new submission and should genuinely call
    // streamStep1; if it's not fresh (e.g. visiting this URL directly, or clicking in from the history
    // list), it only reads the result already persisted by the backend, without re-triggering a model
    // call.
    navigate(`/runs/${runId}/step1`, { state: { fresh: true, text } });
  }

  return (
    <AppShell title={t("landing.shellTitle")} subtitle={t("landing.shellSubtitle")}>
      <div className="input-page-header">
        <h1>{t("landing.heading")}</h1>
        <p>{t("landing.sub")}</p>
      </div>

      <form onSubmit={handleStart}>
        <div className="input-card">
          <div className="input-card-header">
            <span className="input-card-header-label">
              <PhenomenonIcon /> {t("landing.fieldLabel")}
            </span>
            <span className="input-card-counter">{t("landing.charCount", { n: text.length })}</span>
          </div>
          <textarea
            autoFocus
            placeholder={t("landing.placeholder")}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="input-card-footer">
            {/* Model/thinking effort — shown for provider="deepseek" or "openai" (provider itself
                currently has no toggle entry point in this UI, see settings.tsx; picking which one is
                active is a matter of changing that file's hardcoded default). Neither option applies
                under anthropic: the model dropdown is DeepSeek/OpenAI-exclusive, and thinking effort is
                their tiered reasoning_effort, whereas Anthropic uses a separate budget-based extended
                thinking, see atba/agent_streaming.py. */}
            {(provider === "deepseek" || provider === "openai") && (
              <div className="input-card-options">
                <label className="input-card-option">
                  <span>{t("landing.modelLabel")}</span>
                  <select value={model ?? currentProviderModel} onChange={(e) => setModel(e.target.value)}>
                    <option value={currentProviderModel}>{currentProviderModelLabel}</option>
                  </select>
                </label>
                <label className="input-card-option">
                  <span>{t("landing.reasoningEffortLabel")}</span>
                  <select value={reasoningEffort} onChange={(e) => setReasoningEffort(e.target.value)}>
                    {reasoningEfforts.map((effort) => (
                      <option key={effort} value={effort}>
                        {REASONING_EFFORT_LABEL_KEY[effort] ? t(REASONING_EFFORT_LABEL_KEY[effort]) : effort}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            <button type="submit" className="input-submit-btn" disabled={!text.trim()}>
              {t("landing.submit")}
            </button>
          </div>
        </div>

        {text.trim() && (
          <div className="input-ready-banner">
            <span aria-hidden="true">✓</span>
            <div>
              <strong>{t("landing.readyTitle")}</strong>
              <p>{t("landing.readyBody")}</p>
            </div>
          </div>
        )}
      </form>

      <Link className="input-history-link" to="/runs">
        {t("landing.historyLink")}
      </Link>
    </AppShell>
  );
}

function PhenomenonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3a5 5 0 0 0-5 5c0 1.6.7 2.7 1.6 3.7.5.6.9 1.1.9 1.8v1a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1c0-.7.4-1.2.9-1.8.9-1 1.6-2.1 1.6-3.7a5 5 0 0 0-5-5Z" strokeLinejoin="round" />
      <path d="M10 18h4M10.5 20.5h3" />
    </svg>
  );
}
