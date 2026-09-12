"""The system prompts each step uses — loaded from standalone files, never hardcoded in the code.

The actual content lives in:
- atba/prompts/step1.{zh,en}.md              — step 1's complete single-agent-run system prompt
  (causal-presupposition check + phenomenon deconstruction + theory-jargon check merged into one task
  description, per the "one agent loop per stage" design)
- atba/prompts/step1_jargon_retry.{zh,en}.md — the retry-prompt template fed to pydantic_ai.ModelRetry
  when the theory-jargon check hits (triggered within the same run(), not a separate outside call)
- atba/prompts/step2.{zh,en}.md              — step 2's complete single-agent-run system prompt
  (matches candidate theoretical directions against step 1's phenomenon card, doesn't judge whether a
  gap exists, no retry template — step 2 has no verification loop needing ModelRetry)
- atba/prompts/step3.{zh,en}.md              — step 3's task-framework system prompt (role setup,
  input format, multi-direction exploration logic, when to escalate to a human, cross-reference
  requirements) — doesn't include "how to search well with the search_scopus tool" or "how to judge
  whether to take the gap-spotting or problematization path" — those two live separately in
  retrieval_skill and problematization_skill below, and all three are spliced together into one
  complete prompt inside step3_system_prompt(), not three independent calls each handling one part.
- atba/prompts/retrieval_skill.{zh,en}.md    — the strategic knowledge of "how to retrieve" itself
  (Scopus syntax, the three-tier degrading retrieval + rewrite-retry protocol, a self-check list after
  each retrieval, audit requirements), a **reusable skill fragment**, not a prompt exclusive to one
  step — step 3 uses it now, and step 5's relabeling-suspicion follow-up also splices the same one into
  its own system prompt, rather than maintaining two copies of the retrieval strategy description
  (step 4 also used to use it, no longer needed once the construct-novelty check was removed from step
  4, see step4_system_prompt()). This is **not** reused by standing up a separate "retrieval agent"
  called as a sub-agent — that was this project's earlier design, since abandoned (it violates the
  architectural rule "each step is one independent agent run," see the docstring at the top of
  atba/mcp_server.py): the real reuse mechanism is the host step's agent directly attaching the
  retrieval tool via `toolsets=[build_retrieval_toolset()]` (see atba/mcp_server.py), with this skill's
  text spliced into its system prompt — retrieval happens inside the host step's own agent run.
- atba/prompts/problematization_skill.{zh,en}.md — the methodological knowledge of "should a research
  question take the gap-spotting or the problematization path" itself, per Alvesson & Sandberg (2011,
  AMR): the definitions of gap-spotting vs. problematization, the five types of problematizable
  assumption, adapting the A&S original's six methodological principles into judgment steps fitting
  ATBA's retrieval-driven pipeline, Davis's (1971) obvious/absurd/interesting self-check criteria, and
  a cautionary counter-example of "prepackaged problematization." Likewise a **reusable skill fragment**
  (not exclusive to step 3), spliced in the same way as retrieval_skill.
- atba/prompts/step4.{zh,en}.md              — step 4's task-framework system prompt (five internal
  sub-steps: theoretical deep retrieval / candidate generation / relation-graph construction /
  four-virtue scoring / selection, including special requirements for revision rounds) — **scope
  narrowed at the user's request**: no construct-novelty check, no Lakatos hard-core/protective-belt
  judgment (both were once part of six sub-steps, now removed, see the module-level comment on
  CandidateTheory in atba/schemas.py). **But retrieval itself was added back for a different purpose**:
  a dedicated deep retrieval on the anchor theory before candidate generation
  (`TheoreticalGroundingRecord`), the opposite direction from the removed novelty_check (before
  candidate generation vs. after), so step4_system_prompt() splices retrieval_skill back in — reusing
  the same retrieval-strategy knowledge as steps 3/5, not maintaining a separate copy.
- atba/prompts/step5.{zh,en}.md              — step 5's task-framework system prompt (adversarial
  interrogation: falsifiability/boundary-conditions/relabeling-suspicion follow-ups) — **the one place
  in the whole system where the system prompt deliberately doesn't tell the agent how the candidate
  theory was generated/scored/selected by step 4** — it's given only the candidate theory's own
  object-level content, to create genuine adversariality rather than self-affirmation (see the
  module-level comment on "Step 5" in atba/schemas.py, and how atba/step5.py's _task_text trims down
  what's fed to it). The relabeling-suspicion question needs independent retrieval verification, so
  retrieval_skill is spliced in — with step 4's novelty check removed, **this is the only place left in
  the whole pipeline that still uses retrieval to verify "is this just an existing construct wearing a
  new label,"** not a dispensable duplicate check.
- atba/prompts/step6.{zh,en}.md              — step 6's complete single-agent-run system prompt —
  **the output isn't JSON, it's the full text of a markdown report itself** (the Agent in
  `atba/step6.py` carries no `output_type`, whose default output type is `str`), a different mode from
  the first five steps' ToolOutput pattern, needing no retrieval/skill fragment spliced in — step 6
  produces no new reasoning, it purely integrates the judgments the first five steps already made into
  a report, needing no extra methodological knowledge.

Tools no longer need a separate prompt-side JSON-schema wrapper: pydantic-ai generates one
automatically from the Pydantic models in atba/schemas.py; a readable version is in
atba/schemas/<step>.schema.json (generated by atba/export_schemas.py — don't hand-edit it).
"""

from .registry import load_prompt


def _wrap_thinking_language(lang: str, body: str) -> str:
    """要求模型的内部思考过程（extended thinking/reasoning）*和*最终结构化输出都跟着lang走——
    光把system prompt整篇写成目标语言，并不会让模型自动跟随：实测（用户反馈）lang="zh"时思考
    内容仍然经常是英文，这是模型本身的默认倾向（训练数据里长链推理/CoT绝大部分是英文），不会
    因为"周围上下文是中文"就自动跟随，需要显式指示。

    **第一版只在开头加了一句"请用中文思考"，实测无效**（DeepSeek默认模型下思考内容依旧是
    英文）——不是"要不要提这件事"的问题，是"提得够不够重"的问题：一句夹在一大段任务说明最前面
    的普通句子，容易被后面几百行具体任务指令盖过去。现在改成：(1) 用【】/[]标出的显眼硬性要求，
    而不是普通陈述句；(2) 同一份指令在整个system prompt的开头和结尾各放一次——长prompt里
    模型对开头/结尾的指令遵从度通常好于中段，掐头去尾各放一次比只放一次更可靠；(3) 明确说
    "优先级高于任务说明里的任何默认习惯"，不是一句可有可无的提醒。

    放在这里、由每个stepN_system_prompt()统一调用，而不是塞进具体某个stepN.<lang>.md
    文件里——"用什么语言"是跟"这一步具体要做什么任务"正交的横切关注点，一个地方改就能
    覆盖全部六步，不用在八份.md文件里各自维护一遍、还容易漏改。

    **lang="en"曾经不处理**（旧版理由：英文本来就是大多数模型思考过程的默认语言，不需要额外
    强调）——**这个假设只对"思考过程"成立，对"最终结构化输出内容"不成立，已被真实case推翻**：
    用lang="en"跑第四步（DeepSeek），thinking确实是英文，但`candidate_name`/`theory_elements`
    等最终输出字段的实际内容整段是中文——模型显然把"任务说明本身是英文"当成了排版语言，不等于
    "回答也要用英文"。现在改为zh/en对称处理：两个分支都显式声明最终输出内容必须用目标语言写。"""
    if lang == "zh":
        directive = (
            "【硬性语言要求】本次任务中，你的思考过程（thinking / reasoning）必须全程使用中文，"
            "不允许出现英文思考内容；最终的结构化输出/文本产出同样使用中文（除非任务说明里明确要求"
            "保留英文的专有名词/理论术语）。这条要求的优先级高于下面任务说明里的任何默认习惯。"
        )
    else:
        directive = (
            "[HARD LANGUAGE REQUIREMENT] For this task, all final structured-output field content "
            "(not just your thinking) must be written in English — do not switch to any other "
            "language for the substantive content, even if it would otherwise feel natural to you. "
            "Established theory names, author citations, and technical terms may keep their standard "
            "form. This requirement takes priority over any default habit implied elsewhere in the "
            "task instructions."
        )
    return f"{directive}\n\n---\n\n{body}\n\n---\n\n{directive}"


def step1_system_prompt(lang: str = "en") -> str:
    return _wrap_thinking_language(lang, load_prompt("step1", lang=lang))


def step1_jargon_retry_message(lang: str, terms: list[str], reason: str) -> str:
    # The separator and the no-terms fallback text must follow lang too — this template is spliced
    # into a ModelRetry message sent back to the model, and leaving these hardcoded in Chinese would
    # mix languages into an otherwise-English retry prompt when lang="en" (the same class of bug fixed
    # in _wrap_thinking_language: hardcoded fill-in text doesn't automatically follow the surrounding
    # prompt's language).
    separator = "、" if lang == "zh" else ", "
    no_terms = "（未列出具体术语）" if lang == "zh" else "(no specific terms listed)"
    template = load_prompt("step1_jargon_retry", lang=lang)
    return template.format(terms=separator.join(terms) or no_terms, reason=reason)


def step2_system_prompt(lang: str = "en") -> str:
    return _wrap_thinking_language(lang, load_prompt("step2", lang=lang))


def retrieval_skill_system_prompt(lang: str = "en") -> str:
    return load_prompt("retrieval_skill", lang=lang)


def problematization_skill_system_prompt(lang: str = "en") -> str:
    return load_prompt("problematization_skill", lang=lang)


def step3_system_prompt(lang: str = "en") -> str:
    """Step 3's complete system prompt = task framework + retrieval skill + problematization skill
    spliced together — the latter two are reusable fragments (see the module docstring above); step
    3's system prompt splices them into its own task description on load, rather than three separate
    calls/three agents each handling one part. The language directive is only added once, at the
    front — no need to add it again before each skill fragment spliced in."""
    body = (
        f"{load_prompt('step3', lang=lang)}\n\n---\n\n{load_prompt('retrieval_skill', lang=lang)}"
        f"\n\n---\n\n{load_prompt('problematization_skill', lang=lang)}"
    )
    return _wrap_thinking_language(lang, body)


def step4_system_prompt(lang: str = "en") -> str:
    """Step 4's complete system prompt = task framework + retrieval skill spliced together — the
    theoretical-deep-retrieval sub-step needs to reuse the same retrieval-strategy knowledge (see
    TheoreticalGroundingRecord in atba/schemas.py), the same skill file as steps 3/5, not a separate
    copy."""
    body = f"{load_prompt('step4', lang=lang)}\n\n---\n\n{load_prompt('retrieval_skill', lang=lang)}"
    return _wrap_thinking_language(lang, body)


def step5_system_prompt(lang: str = "en") -> str:
    """Step 5's complete system prompt = task framework + retrieval skill spliced together — the
    relabeling-suspicion follow-up needs the agent to independently verify via retrieval itself; now
    that step 4 no longer does a novelty check, this is the only place left in the whole pipeline that
    still uses retrieval to verify "is this just an existing construct wearing a new label," reusing
    the same retrieval-skill fragment."""
    body = f"{load_prompt('step5', lang=lang)}\n\n---\n\n{load_prompt('retrieval_skill', lang=lang)}"
    return _wrap_thinking_language(lang, body)


def step6_system_prompt(lang: str = "en") -> str:
    """Step 6's complete system prompt — just the task framework itself, no skill fragment spliced in
    (see the module docstring above: step 6 produces no new reasoning, needing no extra methodological
    knowledge)."""
    return _wrap_thinking_language(lang, load_prompt("step6", lang=lang))
