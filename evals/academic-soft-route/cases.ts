/**
 * Academic soft-router intent eval cases.
 *
 * - 3 utterances per allowlisted skill × difficulty (easy / medium / hard)
 * - multi-skill requests (ordered expected set; primary = first)
 * - negative controls (must not soft-route / must not pick wrong allowlist skill)
 */
import type { AcademicSoftRouteSkill } from "../../src/ars/academic-router.js";

export type SoftRouteDifficulty = "easy" | "medium" | "hard";

export type SoftRouteCaseKind = "single" | "multi" | "negative";

export interface SoftRouteEvalCase {
  id: string;
  text: string;
  kind: SoftRouteCaseKind;
  difficulty: SoftRouteDifficulty;
  /** Gold primary skill; null means must not soft-route. */
  expectedPrimary: AcademicSoftRouteSkill | null;
  /** For multi: all skills that should appear in ranked matches (order = preference). */
  expectedSkills: AcademicSoftRouteSkill[];
  /** Optional academic-paper mode hint when primary is academic-paper. */
  expectedModeHint?: string;
}

function singles(
  skill: AcademicSoftRouteSkill,
  rows: Array<{ difficulty: SoftRouteDifficulty; text: string; modeHint?: string }>,
): SoftRouteEvalCase[] {
  return rows.map((row, index) => ({
    id: `${skill}-${row.difficulty}-${index + 1}`,
    text: row.text,
    kind: "single" as const,
    difficulty: row.difficulty,
    expectedPrimary: skill,
    expectedSkills: [skill],
    ...(row.modeHint ? { expectedModeHint: row.modeHint } : {}),
  }));
}

export const ACADEMIC_SOFT_ROUTE_EVAL_CASES: SoftRouteEvalCase[] = [
  ...singles("deep-research", [
    { difficulty: "easy", text: "请做文献调研，整理近期相关实证论文" },
    { difficulty: "medium", text: "帮我做一个 annotated bibliography，覆盖社会支持与抑郁的英文文献" },
    { difficulty: "hard", text: "先把这个题目相关的知识地图和检索式搭起来，再筛一轮可纳入的研究" },
  ]),
  ...singles("academic-paper", [
    { difficulty: "easy", text: "写一段文献综述放入论文引言后", modeHint: "lit-review" },
    { difficulty: "medium", text: "按 APA 写一个 structured abstract，控制在 200 词", modeHint: "abstract" },
    { difficulty: "hard", text: "核对正文引文和文末参考文献是否一一对应并做 citation-check", modeHint: "citation-check" },
  ]),
  ...singles("academic-paper-reviewer", [
    { difficulty: "easy", text: "请做一轮同行评审，给出审稿意见" },
    { difficulty: "medium", text: "根据上轮审稿意见改稿，并起草点对点回复" },
    { difficulty: "hard", text: "用 revision coach 帮我处理方法学质疑和 rebuttal 结构" },
  ]),
  ...singles("academic-pipeline", [
    { difficulty: "easy", text: "跑一遍完整的 academic pipeline 写作流程" },
    { difficulty: "medium", text: "从选题到成稿走全流程写作流水线，保留各阶段检查点" },
    { difficulty: "hard", text: "端到端论文 pipeline：检索、写作、完整性检查到可提交稿" },
  ]),
  ...singles("academic-paper-strategist", [
    { difficulty: "easy", text: "请优化这篇论文的写作策略和详细大纲" },
    { difficulty: "medium", text: "用 strategist 帮我重构论证链条和章节安排" },
    { difficulty: "hard", text: "在动笔前先做 paper strategy：贡献点、对话对象、大纲权衡" },
  ]),
  ...singles("academic-paper-composer", [
    { difficulty: "easy", text: "按这个大纲写成全文" },
    { difficulty: "medium", text: "execute the outline and compose the full manuscript chapter by chapter" },
    { difficulty: "hard", text: "大纲已定，请通篇写作并做章节级质量控制后输出完整稿" },
  ]),
  ...singles("nature-figure", [
    { difficulty: "easy", text: "帮我画一张论文配图" },
    { difficulty: "medium", text: "做一张 publication-ready forest plot，导出 SVG" },
    { difficulty: "hard", text: "需要一个 graphical abstract / 机制示意图，符合投稿图规范" },
  ]),
  ...singles("nature-ref-verifier", [
    { difficulty: "easy", text: "核对引用字段，交叉验证 DOI 和作者年份" },
    { difficulty: "medium", text: "run nature-ref-verifier to cross-check citations against Crossref" },
    { difficulty: "hard", text: "引用看起来对，但请做多源字段核验，别只信单一数据库" },
  ]),
  ...singles("nature-polishing", [
    { difficulty: "easy", text: "终稿润色一下语言" },
    { difficulty: "medium", text: "polish the manuscript prose for submission without changing claims" },
    { difficulty: "hard", text: "只做 submission-ready polish：句式与衔接，不改数据、引用和结构" },
  ]),

  // Multi-skill: primary = first; ranked matches should cover the set.
  {
    id: "multi-outline-then-compose-easy",
    text: "先优化详细大纲，再按大纲写成全文",
    kind: "multi",
    difficulty: "easy",
    expectedPrimary: "academic-paper-strategist",
    expectedSkills: ["academic-paper-strategist", "academic-paper-composer"],
  },
  {
    id: "multi-lit-then-figure-medium",
    text: "做完文献调研后，用结果画一张主效应的森林图配图",
    kind: "multi",
    difficulty: "medium",
    expectedPrimary: "deep-research",
    expectedSkills: ["deep-research", "nature-figure"],
  },
  {
    id: "multi-review-revise-polish-hard",
    text: "先同行评审，再按意见改稿，最后只做语言润色不改结论",
    kind: "multi",
    difficulty: "hard",
    expectedPrimary: "academic-paper-reviewer",
    expectedSkills: ["academic-paper-reviewer", "nature-polishing"],
  },
  {
    id: "multi-cite-then-verify-medium",
    text: "先做 citation-check，再用引用交叉核验 DOI 作者年份",
    kind: "multi",
    difficulty: "medium",
    expectedPrimary: "academic-paper",
    expectedSkills: ["academic-paper", "nature-ref-verifier"],
    expectedModeHint: "citation-check",
  },
  {
    id: "multi-pipeline-with-figure-hard",
    text: "走完整 academic pipeline，并在结果节补一张投稿级配图",
    kind: "multi",
    difficulty: "hard",
    expectedPrimary: "academic-pipeline",
    expectedSkills: ["academic-pipeline", "nature-figure"],
  },
  {
    id: "multi-abstract-then-polish-easy",
    text: "先写摘要，再对摘要做终稿润色",
    kind: "multi",
    difficulty: "easy",
    expectedPrimary: "academic-paper",
    expectedSkills: ["academic-paper", "nature-polishing"],
    expectedModeHint: "abstract",
  },

  // Negatives
  {
    id: "neg-weather",
    text: "今天天气怎么样",
    kind: "negative",
    difficulty: "easy",
    expectedPrimary: null,
    expectedSkills: [],
  },
  {
    id: "neg-explicit-skill",
    text: "/skill:academic-grill 追问我的研究设计",
    kind: "negative",
    difficulty: "easy",
    expectedPrimary: null,
    expectedSkills: [],
  },
  {
    id: "neg-explicit-ars",
    text: "/ars-lit-review social support",
    kind: "negative",
    difficulty: "easy",
    expectedPrimary: null,
    expectedSkills: [],
  },
  {
    id: "neg-stats-only",
    text: "帮我跑一下独立样本 t 检验，不要写论文",
    kind: "negative",
    difficulty: "medium",
    expectedPrimary: null,
    expectedSkills: [],
  },
  {
    id: "neg-out-of-allowlist",
    text: "请用 academic-grill 对我的方案逐题追问",
    kind: "negative",
    difficulty: "hard",
    expectedPrimary: null,
    expectedSkills: [],
  },
];
