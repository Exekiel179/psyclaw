# PsyClaw ARS 模式与保护边界

状态：profile v3（内置 Nature 查漏补缺 + `ars:` 对话模式）  
上游：`Imbad0202/academic-research-skills` 及其仓库内 `pi/` wrapper  
固定版本：`v3.21.1`（commit `127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb`）  
许可：CC BY-NC 4.0，仅限符合许可证的非商业用途

## 1. 两种运行方式

PsyClaw ARS 是轻量工作模式。它让锁定的官方 Pi runtime 直接加载 ARS 上游仓库提供的四个原始 Skill、`/ars-*` 命令模板和 Pi wrapper。它不要求先执行 `/init` 或 `/run`，也不把 PsyClaw 的证据账本、工作流状态机和细粒度审批注入 ARS 的每一步。

PsyClaw 受控研究模式仍通过 `/init` 后再 `/run` 启动。需要可恢复 run、结构化研究决策、证据账本、workflow verdict 或 PsyClaw 工作台时使用该模式。首版不允许两个控制面相互冒充：ARS 决定 ARS 流程，PsyClaw 只补宿主边界；PsyClaw 的 `/run` 状态也不会被 ARS 命令自动创建。

## 2. 使用

```text
ars<Tab>          → 输入框变为 ars: （边框高亮），直接对话
ars: <research task>
/ars doctor
/ars full <research task>
/ars status       → 查看 profile 与内置技能状态（可选）
```

在输入框键入 `ars` 后按 Tab，或运行无参数的 `/ars`，进入 ARS 对话模式：前缀为 `ars:`，边框使用强调色。回车发送后去掉前缀并激活上游 ARS；`/ars stop` 退出。首次启用仍会确认 CC BY-NC 许可。

ARS 已随 PsyClaw 的 npm 包内置，无需额外下载、安装或 `/reload`。也可以运行 `/ars start`，确认非商业许可后用自然语言让 ARS 自动选择 Skill。通过国内 npm 镜像安装 PsyClaw 时，ARS 与 Nature/compose 资源包含在同一 npm 包中，不会再访问 GitHub。

## 3. v3 补丁

PsyClaw 不修改 ARS Skill 正文；锁定版本的原始文件按 CC BY-NC 4.0 原样随 npm 包分发。ARS 是否激活以上游 Pi wrapper 写入 session branch 的 `ars-pi-state` 为唯一真源，恢复会话和 `/tree` 切换分支时不另存一份可能漂移的状态。只有上游 wrapper 已激活 ARS 的当前回合，PsyClaw 才追加兼容约束，并在完整流水线中只补 ARS 本身偏薄的三处末端能力：

1. 保留关键阶段确认；普通、可恢复的阶段内工具调用不逐项确认。
2. 没有真实编排能力时允许顺序执行，但必须明确它不是独立多智能体评审。
3. 引用、统计值、实验、文件和外部提交只有得到工具结果或可检查产物支持后才能声称已核验。
4. 原始数据、凭据、受限材料、破坏性操作和外部发布仍服从宿主授权，Skill 文本不能扩大工具权限。
5. 查漏补缺，不替换 ARS 阶段、Material Passport、审稿席位或 Claim/来源门禁（三项均已内置，无需 `/plugin install`）：
   - `nature-figure`：稿件需要出版图时调用，不手写默认 matplotlib，也不改写论文（示例大图资产未打进包，脚本与 references 可用）。
   - `nature-ref-verifier`：在 ARS citation-check / integrity 之后做 DOI/作者/年份字段交叉核对，不替代 Claim–来源蕴含检查。
   - `nature-polishing`：终稿/格式化阶段做文体润色，不得改研究主张、引用、数值或章节结构。
6. 学术写作配套内置：`academic-paper-strategist`（大纲规划）与 `academic-paper-composer`（按大纲成稿）。

不把 Nature 的检索、审稿或其余写作 Skill 并进 ARS 控制面。`ars:` 前缀由上游 Pi wrapper 识别并激活会话；无参数 `/ars` 不再弹出 profile 面板。

## 4. 保留的保护

| 保护 | ARS 轻量模式 | `/run` 受控模式 | 原因 |
| --- | --- | --- | --- |
| 首次开始 ARS 时确认来源与非商业许可 | 保留 | 不适用 | ARS 随系统内置，但使用仍受上游许可证约束 |
| ARS 阶段转换确认 | 保留 | 不适用 | 研究方向、方法和稿件阶段应由研究者决定 |
| 普通阶段内写入逐项确认 | 不增加 | `/run` 范围内自动记录 | 避免细粒度确认拖垮工作流 |
| 原始数据、凭据、破坏性操作、外部发布授权 | 保留 | 保留 | 后果高或不可逆，不能由 Skill 授权 |
| Claude `PreToolUse` 写入 hook | 不声称存在 | 不依赖 | Pi 不运行 Claude hooks；上游 wrapper 也明确这是降级项 |
| PsyClaw evidence/workflow gates | 不默认启用 | 启用 | 让 ARS 获得干净环境，同时保留需要强可追溯性时的选择 |

## 5. 已知限制

- ARS 的 Pi wrapper 不提供真实 agent isolation 或 orchestration；是否能做独立多智能体工作取决于当前 Pi 环境实际提供的能力。
- Claude Code hooks 不会在 Pi 中执行。ARS 的 write-scope guard 在轻量模式下不是硬安全边界。
- ARS 可以检查被报告的流程和稿件一致性，但不能单靠内部一致性证明实验真实执行、原始数据完整或统计结果可复现。
- 当前版本不自动安装 Python、Pandoc、Tectonic、网页检索或多智能体依赖；`/ars doctor` 只报告能力，不代替用户选择。
- PsyClaw profile v3 内置上游 `v3.21.1`（commit `127ff85e...`），并随 PsyClaw 整包更新。若用户另外加载其他 ARS 版本，应视为未验证组合，而不是继续声称 profile 已验证。
- `nature-figure` 省略了上游示例 assets；需要图库示例时仍可另行安装完整 Nature Skills Plugin。

## 6. 后续优化方向

先收集真实 ARS 使用中的失败样例，再决定是否加入更窄的补丁。优先级是：Pi 能力映射、独立评审真实性、引用与统计产物证据、跨阶段上下文体积；不恢复对每个文件名、每次普通写入和每条脚本命令的启发式拦截。


## PsyClaw 隔离审稿桥接

ARS 激活且项目受信时，wrapper 可发现 `psyclaw_ars_multi_agent`。`reviewer_full` 固定执行 EIC/R1/R2/R3/DA 五席；每席一个独立 Pi RPC 进程，同席按 paper-blind Phase 1、paper-visible Phase 2 顺序调用，调度为四席并发加一席。任一席、Python/jsonschema 或 vendored conformance checker 失败均阻断综合，不缩席补写。五席完成后才串行综合，并由 `check_panel_synthesis.py` 和 provenance 构建器复核。

`reviewer_re_review` 不套用五席 schema，而按专用协议串行执行 Phase 1、Phase 2A、Phase 2B；每一门先落盘并校验后才可进入下一门。PsyClaw 记录 RPC attempt、输入 digest、输出与 checkpoint；Material Passport、author adjudication、阶段确认和转移仍由 ARS 主会话管理。当前桥不自动处理需要用户裁决的 2B′ deferral loop，checker 若返回 `user_review_required` 或失败则保持阻断。Stage 3 支持以 `resumeRunId` 恢复已落盘且哈希一致的席位；稿件、合同、cards、passport 或 upstream 绑定漂移时拒绝恢复。Stage 3′ 目前明确拒绝 resume，避免伪恢复与重复外部调用。

代价与边界：完整 Stage 3 至少包含十次 reviewer 调用和一次综合调用，Stage 3′ 至少三次调用；四 worker 是并发上限。进程和上下文隔离不是统计独立，同一 provider/model family 仍可能产生相关误差。只读工具白名单也不是 OS sandbox；未发表稿件是否交给所选 provider 仍取决于用户授权和 provider 数据政策。
