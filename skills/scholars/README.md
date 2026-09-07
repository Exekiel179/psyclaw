# 随包学者镜头 + 女娲蒸馏

## 现成吗？

- **蒸馏引擎**：随包内置花叔 [nuwa-skill](https://github.com/alchaincyf/nuwa-skill)（`vendor/nuwa-skill`，Skill 名 `huashu-nuwa`）。MIT。
- **三个人物镜头**：仓库里**没有**现成的 Kahneman / Gelman / Freud 女娲示例；以下三个是按女娲 `skill-template` 合同为心理学场景写的随包镜头（比早期手写薄摘要更贴模板），**不是**从 nuwa `examples/` 直接拷贝。
- `/grill` 仍是 academic-grill，与人物镜头分离。

## 随包调用

```text
/skill:huashu-nuwa              # 女娲：蒸馏任意人物/主题 → 新 SKILL.md
/skill:kahneman-perspective     # 判断与决策
/skill:gelman-perspective       # 统计建模诚实性
/skill:freud-perspective        # 精神分析学派代表（概念透镜，非治疗）
```

## 推荐（不随包）

花叔其余旗舰（含 `huashu-mac-use` 电脑操控、design、excel、md-html、darwin、用于调试 skill 的 freud-skill 等）在 `skills/recommended/catalog.json`，经 `/skill` 安装。
