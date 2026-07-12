# PsyClaw 上手教程(从零到第一篇通过质量检查的稿子)

> 适合第一次使用的你。跟着敲,每步都有预期输出。
> 速查表在 `docs/COMMANDS.md`;本教程只走**最常用的一条路**,其余命令用到再学。

---

## 0. PsyClaw 是什么(30 秒)

一个**心理学研究编排** CLI:把 澄清 → 文献 → 设计 → 写作 → 评审 → 质量检查 串起来,
并守住学术诚信(效应量+CI 必报、引用可溯源、探索/确证区分、原始数据不入对话)。

**它刻意不做的事**:统计计算。分析流程只**生成**委托 pingouin/statsmodels 的可复现脚本,
你在装了统计库的环境(`pip install "psyclaw[stats]"`)或 SPSS/Mplus 等 MCP 里跑。

---

## 1. 安装与首次配置(2 分钟)

```bash
python -m psyclaw doctor        # 环境自检:看配置/MCP/质量检查状态
python -m psyclaw config        # 配置向导:选 LLM provider、填 API key(写 ~/.psyclaw/.env,不入库)
```

- 没配 key 也能跑:会用 **mock provider**——流程能走通,但综述/写作是"确定性骨架"
  (看起来干巴巴的**不是坏了**,是没接 LLM)。
- 之后所有命令都在你的**研究项目目录**里跑(PsyClaw 把仓库当记忆:产物落 `notes/` `outputs/`)。

```bash
mkdir my-study && cd my-study
python -m psyclaw setup         # 铺目录(notes/outputs/data/…)+ 能力选装
```

---

## 2. 三分钟第一课:status → 聊天

任何时候先看态势:

```bash
python -m psyclaw status
```

一屏告诉你:研究目标、澄清进度、回路状态、**有没有决策在等你**(内容直接打印)、
最近产物、**建议的下一步**。迷路了就敲它。

进 REPL 聊(缺省命令):

```bash
python -m psyclaw
```

REPL 里你需要知道的 7 件事:

| 你想做 | 怎么做 |
|---|---|
| 让它看一个文件 | 直接把路径写在话里(自动检测),或 `@F:\path\paper.pdf`(PDF 自动抽正文;CSV 只给结构+样例,原始数据行不进对话) |
| 模型自己要读文件 | **默认 `access:open`**:自动读并继续;`/access safe` 后一切读取须你 `@` 显式引用 |
| 保存它写的内容 | 直接说"存到 method.txt"——自动落盘(覆盖前会确认;绝不写 `data/raw`;agent 的 save_file 只能写项目内,凭据类路径一律拒) |
| 它给了 shell 命令块 | **每条都会先问你确认**(v0.3 起,fail-closed:非交互一律不跑);`psyclaw` 自家子命令自动执行 |
| 它给了选项清单 | 会弹**键盘选择器**(方向键+空格勾选,或输编号 `1,3`/`全部`),选完自动回传 |
| 给会话起名/找回 | `/rename 焦虑元分析`(名字进提示符)· 下次 `psyclaw resume` 续接 · `/search 关键词` 全文找历史 |
| 看全部斜杠命令 | `/help` |
| 编辑/翻历史 | 方向键即可:↑↓ 翻命令历史、←→ 移光标、Ctrl-A/E 行首尾(readline);装 `psyclaw[full]` 还能得 `/` 命令实时联想下拉 |

它还**看得见你的文件夹**(每轮自动注入有界目录树;`data/raw` 只报文件数不列名)。

---

## 3. 第一个研究:run 或 auto

### 路线 A:先探索(不想先答 17 题)

正式开工前 PsyClaw 要求完成 17 个研究准备项(防 HARKing)。但**你有权显式跳过**:

```bash
python -m psyclaw run literature "正念训练对焦虑的干预效果" --exploratory
```

- 流程照跑:检索(OpenAlex/EuropePMC 合法 OA)→ PRISMA 筛选 → 合成综述 → 审稿模拟;
- 跳过前置检查会**留痕**到 `notes/gate_skips.md`,产物标**探索性**——诚信靠标注,不靠限制。
- 产物:`notes/lit_review.md`(综述)、`notes/evidence_map.json`(构念×文献证据图谱)。

### 路线 B:正式开工(推荐的完整路径)

```bash
python -m psyclaw prepare       # 17 个研究准备项逐项填写(有 LLM 时会追问模糊回答)
python -m psyclaw auto          # 自动发现该做什么 → 派发 → 独立验收 → 记状态
```

`auto` 每轮做五件事:**感知**(从仓库状态推导待办:有目标→综述;有数据表→实证分析;
有效应量表→元分析;有转录稿→质性)→ **派发** → **独立验收**(只认落盘产物)→ **记状态** → **决定**。
每个待办下还会列出你装的相关技能包。默认自动派发;需要逐任务确认时加 `--confirm-each`。

### 有数据了?

把清洗后的数据放 `data/clean/`(原始数据放 `data/raw/`——PsyClaw 永远不读它的内容):

```bash
python -m psyclaw run analysis data/clean/scores.csv
```

它会:画像数据列 → 写设计备忘 → 推荐分析(t 检验/ANOVA/回归/相关)→
**生成可复现脚本** `outputs/analysis.py` → 写实证稿骨架 → 审稿模拟。

**跑统计**(在装了统计库的环境):

```bash
pip install "psyclaw[stats]"
python outputs/analysis.py      # 效应量 + 95% CI + 前提诊断一并输出
python -m psyclaw provenance outputs/analysis.py   # 给脚本打复现溯源包(代码+环境+说明)
```

---

## 4. 投稿前:一键质检

```bash
python -m psyclaw check outputs/report.md --journal psych-science
```

一屏汇总 ✓/✗/⚠:
- **JARS 检查单**(缺失数据处理、剔除报告等,缺了阻断);
- **引用保真**:每条文内引用逐条溯源到你的检索语料——**孤儿引用 = 疑似杜撰**,直接点名;
- **期刊风格**(`--journal`):引用格式对不对 + 该刊退稿红线自查(`psyclaw journal` 看已收录的刊);
- **复现溯源**:生成脚本的 provenance 包齐不齐;
- **KG 关系溯源**(建了图才查)。

哪项 ✗ 就按提示修,修完重跑。

---

## 5. 进阶(用到再看)

```bash
python -m psyclaw search "焦虑研究近年趋势"    # 来源路由:事实/概念/趋势/回忆 自动选通道,主空走兜底
python -m psyclaw kg seed && python -m psyclaw kg show 焦虑   # 据证据图谱种知识图谱(每条边必带引用)
python -m psyclaw                              # 通用任务直接在 Chat 中说明
```

- **兼容入口**:`agent`、`loop`、`*-loop` 和 REPL `/agent` 暂时仍可用,新任务统一优先使用 `run`。
- **插件**:放一个 `.psyclaw/plugins/my.py`(项目级)或 `~/.psyclaw/plugins/`(全局)——

  ```python
  def register(api):
      api.add_tool("my_tool", "描述", "x:str", lambda a: f"echo {a.get('x')}")
      api.add_command("/hello", "打招呼", lambda arg: print(f"你好 {arg}"))
  ```

  `psyclaw plugins` 查看;`skills`/`mcp`/`plugins` 列表都标注 **内置/用户·项目/用户·全局**。
- **技能生态**:装过 AcademicForge/AJS(`.claude/skills`)会被自动发现;
  `psyclaw skills --for meta` 按研究类型推荐。

---

## 6. 常见问题

| 现象 | 原因 / 解法 |
|---|---|
| 综述/写作输出像干巴巴的骨架 | 没配 LLM(mock provider)。`psyclaw config` 接入后重跑 |
| 研究准备未完成 | 正式路线先 `psyclaw prepare`;只想探索加 `--exploratory`(留痕+标探索性) |
| PDF 读出乱码/读不到 | 扫描件/加密件抽不了正文;`pip install pypdf` 提升抽取质量,或先 OCR |
| 模型说"无法读取文件" | 当前为 `access:safe`。用 `/access open` 放开,或用 `@路径` 引用 |
| 统计命令去哪了 | 外移了:分析流程生成脚本 → `[stats]` 环境或 MCP 跑(见 COMMANDS.md「统计去哪了」) |
| auto 某项验收未过 | 本轮记为“需要处理”并继续;修正后再次运行 `psyclaw auto` 会重试 |

---

## 7. 一张图记住全部

```
psyclaw status        ←—— 迷路先敲这个
   │
   ├─ 对话:psyclaw
   ├─ 明确任务:run literature|analysis|meta|qualitative
   ├─ 持续推进:prepare → auto(自动发现→派发→验收→记状态)
   │        └─ 数据:data/clean/*.csv → run analysis → outputs/analysis.py
   └─ 投稿:check 稿件.md --journal <刊> → 修 ✗ → 重跑 → export
```

祝研究顺利。全部命令:`psyclaw commands`;深入架构:`docs/ARCHITECTURE.md`。
