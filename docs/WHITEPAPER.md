# PsyClaw 使用白皮书 · v0.20.0

> 心理学研究**编排** Agent CLI。文献 → 统计 → 写作润色,全流程在对话里完成。
> 纯 Python、stdlib 为主;**统计计算整体外移到成熟库,psyclaw 自身不实现任何统计算法**。

---

## 0. 一句话:它是什么,不是什么

**是**:研究流程的编排者与把关者 —— 帮你把文献找到手、把分析脚本生成好交给成熟库跑、
把稿子按 APA/JARS 规范检查一遍,并在每个容易出学术事故的地方拦住你。

**不是**:输入课题吐论文的机器,也不是又一个统计包。

三条设计红线(违反即视为缺陷):

| 红线 | 含义 |
|---|---|
| **统计外移** | 不在仓内实现任何统计算法;生成委托 scipy/pingouin/statsmodels 的脚本再跑 |
| **文献零杜撰** | 书目条目只能来自真实检索返回;检索失败就如实报失败,**绝不凭记忆列文献** |
| **不做半吊子内容库** | 覆盖不全的内置量表/设计库宁可不要 —— 假覆盖比没有更误事 |

---

## 1. 安装

### 1.1 国际网络

```sh
uv tool install --python 3.12 "git+https://github.com/Exekiel179/psyclaw.git@v0.20.0"
```

没有 uv 先装:`curl -LsSf https://astral.sh/uv/install.sh | sh`

### 1.2 国内网络

直接抄上面那条**大概率卡住**:GitHub clone 不稳 + pypi.org 拉依赖易超时。三选一:

**① 一键脚本(推荐)** —— 自己探测 GitHub 通不通,自动切镜像:

```sh
curl -fsSL https://exekiel179.github.io/psyclaw/install.sh | sh
```

强制走国内镜像:前面加 `PSYCLAW_CN=1`。Windows PowerShell 用 `install.ps1`。

**② 手动镜像版**:

```sh
UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ \
uv tool install --python 3.12 \
  "git+https://gitclone.com/github.com/Exekiel179/psyclaw.git@v0.20.0"
```

> ⚠️ gitclone.com 是第三方镜像,非官方、代码完整性不保证 —— 能连 GitHub 就别用。

**③ 有梯子**:用 1.1 那条,再补个国内 PyPI 索引会更快。

### 1.3 分发包(离线 / 内网 / 批量部署)

仓库根目录跑 `sh scripts/build-dist.sh`,产出三件:

| 文件 | 用途 | 联网要求 |
|---|---|---|
| `psyclaw-0.20.0-py3-none-any.whl` | 标准 wheel | 装时需拉 prompt_toolkit |
| `psyclaw-0.20.0.tar.gz` | 源码分发 | 同上 |
| `psyclaw-offline-0.20.0.tar.gz` | **全离线整包**(依赖 wheel 全带) | **零联网** |

离线整包用法:拷到目标机 → 解压 → `sh install.sh`。只需本机有 Python 3.11+。

构建脚本带硬校验:wheel 内数据文件少于 25 个、或依赖没下全,**直接中止**
—— 不会产出"装了却没 skill / 假离线"的残包(这是真实踩过的坑,见 CHANGELOG v0.17.1)。

### 1.4 升级与自检

```sh
psyclaw update      # 自更新(source / uv-tool / pip 自适应 + 国内镜像)
psyclaw doctor      # 环境自检:配置 / MCP / 质量规则
psyclaw setup       # 全局首配:选能力板块 + 配 provider/key(一次配好,所有项目通用)
```

---

## 2. 怎么用:先记三件事

**① 直接说话就行。** 默认进 agent 模式,模型能自己调 83 个工具。你不需要背命令。

```
psyclaw                       # 进 REPL,开始对话
psyclaw new 我的研究           # 建独立分析目录(标准脚手架,状态隔离)
psyclaw status                # 一屏看:目标/进度/待处理/最近产物/下一步
```

**② 有副作用的操作会先问你。** 写文件、下载、写入你的 Zotero 文库、开浏览器 —— 逐条确认。
`/yolo` 可放行非危险操作;危险命令永远要确认。

**③ 产物自动归位。**
`outputs/` 成稿导出 · `figures/` 图 · `scripts/` 脚本 · `notes/` 笔记 · `data/clean` 清洗数据。
**`data/` 原始数据 psyclaw 永不写入。**

---

## 3. 文献

这是 v0.17–v0.20 打磨最多的部分,也是最容易出学术事故的环节。

### 3.1 检索

对话里直接说"帮我找 X 近三年的文献"即可。底层:

| 工具 | 作用 |
|---|---|
| `lit_search` | 多源检索(OpenAlex + Crossref + EuropePMC,可加 Semantic Scholar/arXiv) |
| `lit_snowball` | **引用滚雪球**:从种子 DOI 沿引用网络扩展 —— 做综述的正道,比关键词精准 |

要点:

- 源名写 `pubmed` 会自动映射到 EuropePMC(它就索引 PubMed);写不认识的源会**明确报出**
  并退回默认源,**不会静默返回 0 条**。
- 年份筛选:`year_from` / `year_to` 真生效(各源支持不一,结果侧统一再兜一刀)。
  区间内无命中会明说,**不会让人误以为"该领域没有新研究"**。
- 系统提示每轮注入**真实当前日期**,所以"近三年"是按今年算,不是按模型训练截止年算。

CLI 等价:`psyclaw lit "关键词" --limit 15 --year-from 2024`

### 3.2 拿全文(付费墙三级链路)

**开放获取**直接下:`lit_download`(OA + 已配机构权限)。

**付费墙不是终点** —— 用的是**你自己的机构权限**,psyclaw 不绕过任何付费墙,也不碰你的账号密码:

| 级别 | 工具 | 你要做什么 | 前提 |
|---|---|---|---|
| ① 全自动 | `lit_fetch_via_browser` | **什么都不用做** | 装 WebBridge 扩展 |
| ② 半自动 | `lit_open_institutional` → `lit_capture_pdf` | 点一下 Download | 无 |
| ③ 兜底 | —— | 按提示走 | 无 |

- **① 全自动**:在你**已登录的真实浏览器**里 fetch,带着机构会话拿到字节流直接落盘。
  装桥:`psyclaw webbridge install`(要在浏览器里点「添加」)。
- **② 半自动**:自动打开机构入口(LibKey → EZProxy → doi.org 依次降级),
  你点 Download **下到平时的下载目录就行**,不用另存、不用改名 ——
  `lit_capture_pdf` 会盯住下载目录,自动收进 `outputs/pdfs/` 并按「作者_年份_题名」改名。

配机构权限效果更好:`psyclaw auth --set`(EZProxy / LibKey)。

### 3.3 Zotero 文库

| 工具 | 作用 |
|---|---|
| `zotero_search` | 先搜你自己的库(别重复下载) |
| `zotero_fulltext` | 取你库里已索引的全文 —— 付费墙文献的合法全文源 |
| `zotero_add` | 把检索到的文献写入你的库(已在库不重复添加) |

配置:环境变量 `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID`
(Zotero 网站 → 设置 → 安全 → 应用程序 → 新建私钥)。

### 3.4 引用保真(最要紧的一环)

```sh
psyclaw cite <稿件.md> --verify
```

逐条参考文献拿去 Crossref **查证是否真实存在**,三态:

| 状态 | 含义 | 后果 |
|---|---|---|
| `verified` | 索引命中**且作者姓氏+年份都对得上** | 通过 |
| `not_found` | 索引可达、查了、无匹配 | **疑似杜撰,退出码 1** |
| `unresolvable` | 网络不可达 / 该类型本就不被收录 | 只提示,**不拦截** |

为什么非有不可:一条**格式规整、卷期页码俱全、文内与文末完全自洽**的虚构条目,
能通过所有离线核查(语料溯源、一致性),**只有联网查证能揪出来**。

> 相关命令:`cite`(元数据 → 规范 APA7 参考文献)、`cite-check`(文内引用溯源核查)。

---

## 4. 统计分析

### 4.1 psyclaw 不算统计 —— 它生成脚本

这不是能力缺失,是设计决定:统计算法应当交给经过千万次验证的成熟库,
而不是在一个编排工具里重新实现一遍。

流程:**你描述问题 → psyclaw 生成可复现脚本(委托 scipy/pingouin/statsmodels)→ 跑 → 解读**。

装统计栈:

```sh
pip install "psyclaw[stats]"      # pingouin/pandas/numpy/scipy/statsmodels/lifelines/…
```

### 4.2 研究前:先把自由度锁住

| 命令 | 作用 |
|---|---|
| `prepare` | 完成研究准备清单(17 项:问题/变量/设计/理论/排除标准/功效…) |
| `declare-test` | **预注册一个计划分析** —— 确证性假设须先声明,防事后反标 |
| `assume` | 前提假设知识库(t 检验/ANOVA/回归/SEM/IRT 各自的假设与违反后果) |
| `method` | 方法学 skill 路由(样本量估算 / 无关变量控制) |

### 4.3 数据准备

| 命令 | 作用 |
|---|---|
| `score` | 量表自动计分:反向题翻转 + 子量表总分/均值 + 缺失处理 |
| `ethics` | 量表伦理审查提示(IRB 要求 / 危机转介 / 敏感条目) |

> **量表用你自己的定义**:v0.18.0 起 psyclaw **不内置量表库**(原来只有 7 条,
> 搜 MBI 只会得到"未收录",帮倒忙)。在 `.psyclaw/scales/*.yaml` 里写一份,
> 计分机器照跑,覆盖面由你决定。

### 4.4 分析编排

```sh
psyclaw analysis-loop     # 画像数据 → 设计 → 推荐分析 + 生成可复现脚本 → 评审
psyclaw meta-loop         # 元分析:校验效应量表 → 生成脚本(statsmodels)→ 写 → 评审
psyclaw qual-loop         # 质性:载入转录稿 → 主题分析 → 写 COREQ 报告 → 评审
```

### 4.5 学术诚信硬约束(即使你明确要求也不会做)

- **未运行不造数**:脚本没真跑,绝不给带具体数值的"输出示例",用占位符并明说;
- **不用"边缘显著"话术**:p ≥ .05 就如实写不显著,报精确 p + 效应量 + CI;
- **效应量 + 95% CI 必报**;相关 ≠ 因果(因果措辞须带识别假设);
- **区分探索性 / 确证性**:确证性研究须预注册或明确标注探索性(`DESIGN.prereg` 质量检查)。

---

## 5. 论文写作与润色

### 5.1 写作纪律

- 统计数值**只用上下文里真实存在的结果**;没有的写占位「(待统计脚本运行后回填:<统计量名>)」
  并在文末集中列出待回填清单;
- 引用同理:语料里没有的条目**不写**,占位「(待检索补引:<论点>)」,由 `lit_search` 检索后回填;
- 数据清洗/剔除明细必须写进方法与结果,不得静默省略。

### 5.2 检查与导出

```sh
psyclaw check <稿件.md>        # 一键质检:JARS + 引用保真 + 期刊风格 + 复现溯源,一屏汇总
psyclaw jars <稿件.md>         # APA 2018 JARS 检查清单(Quant/Qual/Mixed)
psyclaw review <稿件.md>       # 审稿模拟:EIC + 3 审稿人 + Devil's Advocate
psyclaw export <稿.md> --docx <出.docx>   # APA7 版式 + 中文字体 + 图片真嵌入
```

`export` 支持三种格式:`apa7` / `xinlixuebao`(心理学报)/ `xinlikexue`(心理科学)。

> 内置 **nature-review** skill:1287 篇 Nature 审稿报告蒸馏的审稿 + 回复信流程
> (12 关注类别逐维审 / 21 回复策略)。对话里说"帮我审一下"即可调用。

### 5.3 图表

```python
from psyclaw.figures import apply_style
with apply_style('apa7'):
    ...  # 中文字体前置,免豆腐块
```

- 概念图/框架图/路径图用 **graphviz(dot)或 mermaid** 让布局引擎排版
  —— 别用 matplotlib 逐根画箭头(布点固定必然线条交叉成面条);
- matplotlib 只画数据图;
- `figures` 命令提供风格预设 + `FIG.honest` 诚实性核查(截断坐标轴等)。

### 5.4 期刊适配

```sh
psyclaw journal            # 期刊画像:心理学报/心理科学/Psych Science/JPSP/Psych Bulletin…
psyclaw cite <稿> --journal <刊名>    # 按目标期刊核对引用风格
```

---

## 6. 常用命令速查

| 场景 | 命令 |
|---|---|
| 开工 | `psyclaw` · `psyclaw new <名>` · `psyclaw start` |
| 看态势 | `psyclaw status` · `psyclaw goal` · `psyclaw tasks` |
| 找文献 | `psyclaw lit "关键词" --year-from 2024` |
| 查引用真伪 | `psyclaw cite <稿> --verify` |
| 投稿前 | `psyclaw check <稿>` → `psyclaw review <稿>` → `psyclaw export <稿> --docx` |
| 环境 | `psyclaw doctor` · `psyclaw config` · `psyclaw update` |
| 全部命令 | `psyclaw commands` |

全流程一把梭:`psyclaw research "一句话研究问题"`(文献 → 设计 → 写作 → 评审 → 总验收)。

---

## 7. 已知边界(用之前请知道)

1. **不内置量表库和实验设计库** —— 量表自己定义(见 4.3),设计讨论交给对话。
2. **统计一行不算** —— 生成脚本交给成熟库跑,需要 `pip install "psyclaw[stats]"`。
3. **付费墙全自动路径需装 WebBridge 扩展**(浏览器里点「添加」),
   且真实出版社页面 DOM 千差万别,找 PDF 链接可能需按刊调整。
4. **机构权限依赖你所在机构的配置**(EZProxy / LibKey),`psyclaw auth --set` 后
   建议用一篇你确实有权限的文章实测一次。
5. **模型能力决定上限** —— psyclaw 负责编排、把关与工具,不负责替你想研究问题。

---

## 8. 出问题时

```sh
psyclaw doctor        # 环境自检
psyclaw gates         # 质量规则系统自检
psyclaw eval          # 离线评测(不调 LLM、不联网)
```

若模型说"psyclaw 没有某某能力"——**多半是它够不着,而非真没有**。
把当时的原文贴到 issue 里:https://github.com/Exekiel179/psyclaw/issues

---

*本文对应 v0.20.0。命令与工具清单由 `psyclaw commands` / `build_tools()` 实测导出,非凭记忆撰写。*
