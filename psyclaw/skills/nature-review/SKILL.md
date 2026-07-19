---
name: nature-review
description: Nature 级同行评审 + 回复信——从 1287 篇 Nature 审稿报告蒸馏的方法(12 关注类别 / 6 稿件→审稿人映射 / 21 回复策略 / 8 行动状态)。审稿或写 rebuttal 时用。
category: review
---

# Nature 级同行评审(review)+ 回复信(respond)

方法源自 mumdark/nature-review-studio(1287 篇 Nature 2025–2026 审稿报告蒸馏)。下面是即用
的结构化流程;完整 1287 案例知识库 + 自动 .docx 生成见「装全量」。

## review —— 审稿

1. **检测方法类型**,据此分派 2–5 个审稿人视角(6 稿件→审稿人映射):
   wet-lab / clinical / machine-learning / omics / computational / theory——一篇稿件通常需
   2–5 个互补视角,别只用一个。
2. **按 12 关注类别逐维审**(审计式,别漏维):
   ① 实验设计 ② 新颖性/增量 ③ 可复现性 ④ 临床/生态效度 ⑤ 统计严谨(效应量+CI、多重比较、
   功效)⑥ 因果 vs 相关 ⑦ 样本/对照充分性 ⑧ 数据与代码可得性 ⑨ 文献定位/遗漏 ⑩ 过度声称
   ⑪ 伦理/预注册 ⑫ 图表与报告规范(JARS)。
3. **每条关注定级**:major / minor / optional,并给可操作的修改建议(不是泛泛"写得不清楚")。
4. 输出结构化审稿意见:摘要评价 → major concerns → minor concerns → 给编辑的保密建议。

## respond —— 写回复信(rebuttal)

对每条审稿意见,从 **21 回复策略**里选最合适的一个,并标 **8 行动状态**:
- 策略(举例):acknowledge_and_correct(认并改)、add_experiment(补实验)、add_analysis(补分析)、
  moderate_claim(弱化声称)、clarify_text(澄清)、provide_evidence(给证据)、
  respectfully_disagree(有据反驳)、defer_to_scope(超出本文范围)……
- 状态:DONE / TODO_EXPERIMENT / TODO_ANALYSIS / TEXT_ONLY / NOT_FEASIBLE / PARTIAL /
  DISAGREE / DEFERRED。
- 逐条对应、逐条闭环:每条审稿意见都要有"策略 + 状态 + 具体回应";别遗漏、别笼统认错。

## 红线

- 审稿要具体、可操作、分级;不做人身评价,对事不对人。
- rebuttal 有据反驳可以,但不 p-hacking、不掩盖局限;补的实验/分析要真做(交给 psyclaw 的
  统计外移脚本),不编数据。
- 与 psyclaw 一致:效应量+CI 必报、区分探索/确证、相关≠因果。

## 装全量(1287 案例知识库 + 自动 docx)

`psyclaw skill install https://github.com/mumdark/nature-review-studio` —— 稀疏检出到
.claude/skills,含 review-axes / response-axes references 与 1287 案例蒸馏 index(方法/严重度/
关注轴),以及成对 .docx/.md 生成。装后本 skill 自动升级为全量。
