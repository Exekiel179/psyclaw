# PsyClaw 沙箱设计(四执行面 × 四原则 × start 意图配置)

> 蓝图(2026-07-14,与用户定稿)。实现分轮:feat-125 沙箱核+策略模型 ·
> feat-126 文件面(含**私密/编码表**)· feat-127 代码执行面 · feat-128 网络面 ·
> feat-129 start 澄清式按 skill 配置沙箱。

## 一、四原则(贯穿所有面)

| 原则 | 落法 |
|---|---|
| **最小权限** | 默认全拒;按启用的 skill 声明的**能力清单**逐项开;项目根可写、data/raw 永不可写(既有铁律并入) |
| **快速失败** | 越权即刻拒绝+明确原因,不静默降级、不"尽力而为"绕过 |
| **可审计** | 每次受管操作落 `.psyclaw/sandbox_audit.jsonl`(时间/面/操作/参数摘要/裁决/原因),可事后核 |
| **可恢复** | 副作用前存快照/用临时区;文件覆盖先备份,批量操作可回滚;审计即回溯依据 |

## 二、四执行面

### 1. 文件操作(含**私密/编码表**——本项目独有)
- 读:沿用 read_denied(data/raw 原始行、密钥硬拒);
- 写:项目根允许清单,data/raw 拒,覆盖先备份到 `.psyclaw/trash/`;
- **私密操作(新)**:被标为 private 的数据(如含被试标识的原始表)**禁止完整外传**
  (进 LLM 上下文 / 网络请求 / 写出项目)——此时系统**要求提供编码表**
  (`notes/codebook.yaml`:真实值→代号映射),只有脱敏后的代号可外传;
  无编码表则拒绝外传并提示先建。区别于"拒绝访问":数据可**本地**处理,
  只是**跨信任边界**时强制脱敏。

### 2. 工具调用(区别于通用 agent 沙箱的关键)
通用 agent 沙箱只问"这个工具能不能调";psyclaw 多一层**学术语义门**:
- 工具按信任分级:内置只读(search/read)自由;副作用工具(save/shell/web/MCP)
  按 skill 能力清单放行,逐动作审批(已有);
- **语义护栏并入沙箱**:统计计算工具必须是外移路径(手写统计实现在工具层就拒,
  不只靠提示);写出的稿件过 gates 才算"交付"——沙箱管的不只是系统安全,
  还有**学术操作的合法性**。这是与 Claude Code / 通用 agent 沙箱的本质区别。

### 3. 代码执行(保护系统 + 不频繁打断)
- 静态先筛:AST/模式扫恶意(rm -rf、fork 炸弹、外连下载执行、写系统路径、
  base64+exec)→ **硬拒**(快速失败);
- 正常科研代码(pandas/pingouin/numpy 读项目数据、出图)→ **放行不打断**
  (这是"不频繁中断正常任务"的关键:白名单意图 + 黑名单模式,灰区才问);
- 资源上限:超时、内存、子进程数——超限杀掉并审计,不挂死。

### 4. 网络请求
- 域名白名单:学术 API(openalex/europepmc/crossref/arxiv/unpaywall)、
  机构库代理、已配置 MCP 端点 → 放行;
- 私密数据不出网(见文件面);上传类请求(把数据发外部服务)默认拒,须显式授权;
- 其余域名:灰区,问一次,答复记进本会话。

## 三、start 集成(澄清式按需配置)

`psyclaw start` 流程(feat-129):
1. **澄清意图**:grill 用户要做什么研究(复用 clarify 的提问能力,精简版);
2. **选定 skill**:据意图路由该装哪些 skill(复用 skills --for);
3. **询问是否启用沙箱**(默认建议启用,可关);启用则:
4. **按 skill 能力清单配置沙箱策略**——每个 skill 声明自己需要的面与范围
   (如 lit skill 需要网络[学术 API 白名单]+文件写[notes/];stats skill 需要
   代码执行[科研白名单]),沙箱取并集为本会话策略,**多余能力一律不开**(最小权限);
5. 策略落 `.psyclaw/sandbox.yaml`(可审计、可复用、用户可编辑)。

## 四、策略数据模型(feat-125)

```yaml
# .psyclaw/sandbox.yaml
enabled: true
file:   {write_allow: [outputs/, notes/], private_paths: [data/raw/], require_codebook: true}
tools:  {side_effect_approval: per-action, stats_must_delegate: true}
exec:   {timeout_s: 180, deny_patterns: [rm -rf, ...], allow_intent: [pandas, pingouin]}
net:    {allow_domains: [api.openalex.org, ...], upload: deny}
audit:  .psyclaw/sandbox_audit.jsonl
```
sandbox_check(face, action, args) → {allow: bool, reason, needs?: codebook|approval}
——单一裁决入口,四面共用,每次调用落审计。fail-closed:策略缺失/异常一律拒。
