# Changelog
> 主题:**仓库精简,开箱即用**。功能无变更,面向新用户的第一印象整体重做。
开发脚手架此前散落在仓库顶层,占据大量篇幅而对使用者毫无意义。现统一收入 `dev/`:
- 自主开发循环脚本(`ralph.*` / `nostop.*` / `plan.*` / `init.sh`)及其提示词
  (`PROMPT.md` / `PLAN_PROMPT.md`);
- 计划与状态文件(`TODO.md` / `feature_list.json` / `progress.md` /
  `session-handoff.md` / `AGENTS.md` / `skills-lock.json`);
- harness 工具链 `.agents/` → `dev/agents/`;
- 评测夹具 `evalcase*/`;
- `docs/` 中的内部审计报告(混沌报告、迁移审计、优化记录、记忆设计、superpowers 规格)
  → `dev/docs/`。
脚本内部路径已同步修正并实测:各脚本切到仓库根执行、提示词从 `dev/` 读取,
`dev/init.sh` 从任意目录调用均可。`CLAUDE.md` 中的 harness 契约路径一并更新。
- 移除开发残留 `notes/_diag_meta.py`(内含早期 `F:/Projects/psyclaw` 路径)
  与两份层级回归报告;
- `.gitignore` 补充运行期产物(`outputs/` `figures/` `notes/` `data/` `dist2/`
  `.remember/` 等)——新用户克隆后跑一遍不会带出一堆脏文件。
面向使用者而非开发者:开篇即指向使用白皮书,安装后直接给对话示例,
四个入口一张表说清。修正多处陈旧内容——版本号仍钉在 v0.15.0,
命令清单里仍在介绍 v0.18.0 已移除的 `norms` / `design` / `preregister`。
新增校验:README 中出现的每个命令与每条相对链接均经实测确认有效。
随版本重新生成为 `docs/PsyClaw使用白皮书_v0.21.0.docx/.pdf`。
## v0.20.0(2026-07-20)

> 主题:**付费墙全文三级取全文链路打通**——从「无法获取」到全自动。

### 新增(feat-191):`lit_fetch_via_browser` —— WebBridge 全自动抓取
装了 WebBridge 扩展后**连点下载都不用**:在用户已登录的真实浏览器里 `fetch`
(`credentials: 'include'`),带着他机构登录后的会话拿到字节流直接落盘。
用的仍是用户本人的权限,不绕过任何付费墙——不是"psyclaw 去下载",
而是"让用户自己的浏览器去下载,再把字节交出来"。

- **找链接**:优先 `meta[name="citation_pdf_url"]`(学术出版社事实标准),
  拿不到再退回扫页面链接;
- **分块回传**:一篇 PDF 动辄几 MB、base64 后更大,单次响应会被截断(工具层还有
  6000 字符上限)。故先把字节存进页面 `window` 变量,再按 180KB 分片取回并拼接;
- **落盘前三道校验**:`%PDF` 魔数(出版社常把登录页/拦截页当 200 返回)、
  字节数与声明长度一致、分片中断即整篇作废——**绝不落一个半截或伪装成 PDF 的 HTML**;
- **桥不可用时说清缺哪一步**(没装 / 守护进程没起 / 扩展没连),并退回手动路径,
  而不是一句"不可用"。

### 现在付费墙有三级路径(依次降级,均为用户自己的权限)
1. `lit_fetch_via_browser` —— 装了 WebBridge:全自动,零点击;
2. `lit_open_institutional` + `lit_capture_pdf` —— 零额外安装:开机构入口 →
   用户点 Download → 自动收进项目并改名;
3. 都不行时如实说明并给出具体下一步——**不再回「无法获取」**。

`lit_download` 撞墙提示与 `capability_map` 同步更新为这条三级链路。

`tests/test_bridge_fetch.py` +8(分片拼接字节级一致 / 大文件多次分片 /
非 PDF 拒收 / HTTP 403 如实报 / 找不到链接给退路 / 传输中断不落盘 /
`bridge_ready` 精确指出缺失环节)。全量 pytest → 2209 passed;gates ✓;eval 28/28。

> 实机验证边界:本机守护进程已实测可启动(v1.11.3,端口 10086),`bridge_ready`
> 正确报出"扩展没连上"。**浏览器扩展需用户在浏览器里点「添加」**,该步骤无法在
> 此环境完成,故端到端真实抓取待用户实测。

## v0.19.2(2026-07-20)

> 主题:**下好的 PDF 自动收进项目**——不再让用户另存到指定路径 + 起对文件名。

### 新增(feat-190):`lit_capture_pdf`
用户问「不能帮我下载么」。**直接下不了**:登录后的会话在浏览器里,Python 侧拿不到
那个 cookie——这是浏览器安全模型,不是 psyclaw 偷懒。但用户点一下「下载」本就是最
自然的动作;真正多余的是让他记住「另存到 `outputs/pdfs/`、文件名还得叫
`Ang_2025_Doomscrolling-and-Secondary-Traumatic-Stress.pdf`」。那份麻烦由 psyclaw 接过来:

- `capture_from_downloads` 盯住系统下载目录(尊重 `XDG_DOWNLOAD_DIR`),
  新 PDF 一出现就**移进** `outputs/pdfs/` 并按「作者_年份_题名」改名;
- **只认新出现的文件**(调用开始时先拍快照)——绝不动用户下载目录里原有的东西;
- **必须过 `%PDF` 魔数**:出版社的登录页/错误页常被存成 `.pdf`,靠扩展名会把垃圾
  收进项目,还会让后续解析莫名其妙地失败;
- 等 `.crdownload`/`.part`/`.download` 消失才算下完,不半截收走;
- 同名不覆盖(自动加 `-1`)。工具标 `side_effect=True`(会移动用户文件,先问)。

`browser_handoff` 的引导文案同步改口:「直接下到你平时的下载目录就行,不用另存到
别处、也不用改名」,然后调 `lit_capture_pdf` 收。

`tests/test_capture_pdf.py` +9(新文件才收 / 原有文件不动 / 非 PDF 内容拒收 /
下载中不半截收 / 同名不覆盖 / 文件名净化)。全量 pytest → 2201 passed;gates ✓;eval 28/28。

## v0.19.1(2026-07-20)

> 主题:**付费墙不再是终点**——唤起浏览器走机构登录取全文。

### 新增(feat-189):`lit_open_institutional`
此前 `lit_download` 撞到付费墙只报「付费墙无权限跳过 N 篇」,`fetch_and_save`
也只返回一句「配置机构权限/用 Zotero」,**不做任何事**。用户看到的就是
「❌ 付费墙 ——」然后没有下一步,模型据此告诉用户「无法获取」。

**但用户本人往往是有权限的**(在校 / VPN / 机构账号),缺的只是「在真实浏览器里
登一下」——真实浏览器带着他的 SSO 会话,出版社认的正是那个会话。零件其实都在
(`webbridge.open_in_default_browser`、`institution.ezproxy_url`/`libkey_fulltext`),
只是从没接起来。

- `psyclaw/psych/paywall.py`:`resolve_entry` 按 **LibKey → EZProxy → doi.org**
  给出最佳机构入口(越靠前越可能直接出全文);机构层任何异常都不使整条路断掉,
  至少能落到 doi.org。
- `browser_handoff` 打开该入口并**预先建好** `outputs/pdfs/`(用户另存时目录已在);
  引导文案给出逐步下一步(登录 → 另存到哪 → 存好后告诉我)。
- **不绕过付费墙**:用的是用户自己的权限;psyclaw 全程不碰账号密码,
  登录在浏览器里由用户自己完成。工具标 `side_effect=True`(会弹浏览器,先问)。
- `lit_download` 撞墙时改为**指路**并列出待取 DOI,不再只说「跳过 N 篇」;
  `capability_map` 同步写明「付费墙不是终点…别回『无法获取』」。

`tests/test_paywall_handoff.py` +10,其中一条专门守着
**引导文案不许提不存在的工具**——本功能第一版文案里就写了并不存在的 `lit_import`
(与本项目一贯反对的"编造能力"同类),该测试比对真实工具表,杜绝复发。

全量 pytest → 2192 passed;gates ✓;eval 28/28。

## v0.19.0(2026-07-20)

> 主题:**agent 模式转正**(默认开 + 流式输出)+ 修「近三年却拿回 1980 年文献」。

### 修复(feat-188):年份筛选被静默丢掉
用户实测:问「有没有近三年的」,模型写 `--year-from 2021 --year-to 2024`,
返回的却是 1980、1982 年的经典文献。三层问题叠在一起:

1. **模型不知道今天几号**:系统提示从未注入当前日期,它拿训练截止年(2024)
   当「现在」,于是"最新研究"实际停在两年前。→ 新增 `_today_note()`,
   每轮注入真实日期并明写「「近三年」= X–Y,绝不用训练截止年份当今年」。
2. **`year_from` 传了也没用**:`lit_search` 工具只读 query/sources/limit,
   年份参数**静默丢弃**。用户看到的现象就是「这些研究都太老了」,并会合理地
   以为该领域没有新研究。→ 工具接受 `year_from`/`year_to` 并在结果侧统一兜一刀
   (各源对年份支持不一,只靠 API 参数不保证约束真生效);区间内无命中时明确说
   「放宽年份或换检索式,**不要据此断定该领域没有新研究**」。
3. **工具不认识的参数静默忽略**:与 v0.18.1 的「不认识的源静默跳过」同一类
   通病。→ 桥接层比对工具声明的参数表,把被忽略的参数明确报出
   「该约束未生效」。

### 变更:agent 模式默认开(破坏性,故升次版本号)
此前 `agent_mode = False` 硬编码、无配置项,导致 **83 个工具默认够不着**;
副作用工具(下载/入库/导出)更是完全无法调用,模型只能反过来让用户
「切换到 agent 模式」——典型死胡同。现默认开启,`config agent_mode=false`
或 `/agent off` 可关。

### 新增:agent 模式流式输出
此前 agent 模式把整段回复 `"".join` 完才显示,用户全程干等——而流本来就是逐块
消费的,只是被静默拼掉了。现加 `on_chunk`:

- `ToolBlockFilter` 边流边隐藏 ```tool 协议块(工具调用的 JSON 属协议噪声,
  不该喷给用户),并处理 **chunk 从围栏中间断开**的情况(``` / ```to 都可能被切开,
  故留尾巴不急着放行);未闭合的截断块整段丢弃。
- 顺序:`⚙` 进度行打印前先收掉当前 StreamBlock——StreamBlock 关闭要做光标上移覆盖,
  与穿插的 print 混在一起会把画面搞花。
- 已流式显示过就不再整块重印(否则答案出现两遍);provider 不支持流式时退回整块渲染,
  保证答案一定被显示。

`tests/test_agent_streaming.py` +9、`tests/test_recency_and_agent_default.py` +8。
全量 pytest → 2182 passed;gates ✓;eval 28/28。

## v0.18.1(2026-07-20)

> 主题:**修复"工具够不着"死胡同**——模型明明被教着调 lit_search,却无法真正调到。

### 修复(feat-187):命令块 ↔ 对话工具桥接
用户实测(deepseek)完整复现了此前那次「参数解析问题」:

```
```psyclaw
lit_search --query "..." --max 20 --source pubmed
```
→ invalid choice: 'lit_search'
→ 模型结论:「PsyClaw 当前配置中缺少直接对接外部学术数据库的联网检索工具」
```

**根因是架构错配**:`capability_map` 每轮注入、教模型「直接调 lit_search 工具」,
但那句只在 **agent 模式**(```tool JSON 协议)成立;**默认 chat 模式只执行
```psyclaw 命令块**。提示词在教模型做一件它在当前模式下做不到的事,于是它拼出
「工具名 + CLI flag」的四不像,两套约定都不匹配,谁也没执行。

与其规定模型只能用哪套语法(混用不可避免),不如**让两套都通**:

- `run_tool_from_cmdline`:命令块首 token 是**注册工具名**时派发到工具,
  `--key value` / `--key=value` / 裸位置参数(并进 query)统一解析;
  `--max/--n/--topic/--source` 等常见同义参数名归一到工具真实参数。
- **不抢 CLI 子命令**:名字是真子命令(export/gates/check…)一律走原 argparse 路径
  ——否则 `export a.md --docx b.docx` 会被当副作用工具拒执行,破坏
  capability_map 里「命令块跑 psyclaw export --docx」这条既有工作流。
- **副作用工具在命令块路径不放行**:该路径没有审批环节,写盘/写用户文库必须走
  agent 模式的 approve,这里如实告知而非静默执行。
- 工具异常**如实回传**(静默失败会让模型误判成「没有这个能力」)。
- `capability_map` 同步改口:两种写法都给出,不再只说 agent 模式才成立的那句。

### 修复:不认识的检索源静默返回 0 条
同一次事故的第二层:模型写 `--source pubmed`,而 `search()` 用 `if s in fn`
**静默跳过**不认识的源 → 0 条结果。「全不认识」与「这领域真没论文」输出完全一样,
模型据此再次断定「没有检索能力」。而 pubmed 其实有对应——EuropePMC 就索引 PubMed。

- 新增 `_SOURCE_ALIASES`(pubmed/medline/pmc→europepmc、s2→semanticscholar…);
- 认不出的源在 `per_source["_note"]` 里**明确报出**并列出可用源;
- 一个可用源都不剩时**退回默认源**,不让调用方空手而归。

实测:用户那条一字未改的命令现在直接返回 3 条带 DOI 的真实论文。

`tests/test_cmdblock_tool_bridge.py` +9、`tests/test_source_aliases.py` +5。
全量 pytest → 2165 passed;gates ✓;eval 28/28。

> 附注:这次事故里**反杜撰规则完美生效**——检索失败后模型如实报告失败原因、
> 明确拒绝编造条目、只提供不含书目的领域概况。v0.17.1/v0.17.2 那两层修复经受住了
> 真实环境检验;本次修的是它下面那层「工具够不着」。

## v0.18.0(2026-07-20)

> 主题:**砍掉半吊子内容库**。破坏性变更(命令移除),故升次版本号。

### 移除(feat-186)
用户实测撞上「做倦怠研究搜 MBI → 未收录」后拍板删除。这类覆盖不是帮忙而是
帮倒忙:让人误以为库里查过了。与既有的「统计外移」「方法学背书库已删」同一原则
——**宁可不内置,也不做半吊子内容库**。

- **内置量表库**(7 条:dass-42/21、phq-9、gad-7、tipi、rses、pss-10)及其中文常模
  → 移出发行包;`norms` 命令一并移除(它的全部数据就是这 7 条的常模,量表没了即成孤儿)。
- **实验设计目录**(12 类设计卡)+ `design` 命令 → 移除。真实研究问题输进去
  只会得到「未收录」;设计知识交给对话本身。
- **`preregister` 命令** + `preregister.py` → 移除(OSF/AsPredicted 模板模型本就会写)。

### 保留(重要,别误读为"能力缩水")
- **计分机器全留**:`score` / `scale` 仍在——反向计分、分量表求和、缺失处理、
  信度、伦理提示,由用户在 `.psyclaw/scales/*.yaml` 定义**自己的**量表驱动
  (`list_scales` 本就是「内置 + 用户自定义、用户覆盖内置」),覆盖面从此无上限。
  这正是删内置定义却不删能力的理由:MBI 你自己写一份,机器照跑。
- **`DESIGN.prereg` 质量检查保留**:「确证性研究须预注册或明确标注探索性」是学术
  诚信红线,`CLAUDE.md` 明写质量检查只增不删。删的是生成模板的命令,不是判据。
- `parse_clarification` 从 preregister.py **归位到 clarify.py**(它解析的本就是
  clarify 自己的卡片,`SLOTS`/`CARD_NAME` 都在那儿),`scaffold` 依赖不受影响。

### 测试
原先拿内置量表当夹具的 66 个测试(计分/伦理/信度/常模机器)**一条没删**——
数据移到 `tests/fixtures/`,`tests/conftest.py` 用 autouse fixture 重定向文件指针,
被测的仍是真实实现。校验数据本身质量的 `TestCnNormsData` 则删除:常模已不是发行
产物,再校验一份测试夹具没有意义。新增 `tests/test_no_thin_content_libs.py`(6 项)
锁住该决定,并守住「机器还在」「用户自定义量表仍驱动一切」「prereg 质量检查未被顺手删掉」。

全量 pytest → 2151 passed;gates ✓;eval 28/28;compile ✓。

## v0.17.3(2026-07-20)

> 主题:**Zotero 连带管理 + 沙箱白名单补漏**。

### 新增:Zotero 三件套进对话(feat-183)
`zotero_client.py` 一直有 110 行可用的 Web API v3 客户端,但:
`add_by_doi` 是**空壳**(只返回「请你自己去 Zotero 点一下」),
`search_library`/`add_by_doi` 的外部调用点为 **0**,toolloop 里**一个 zotero 工具都没有**
——能力在代码里,对话里够不着。现补齐:

- **`add_by_doi` 真正实现写入**:Crossref 取元数据 → 拼 Zotero `journalArticle`
  条目 → `POST items`。三条安全约束:已在库**不重复添加**(Zotero 允许重复条目,
  重复写会污染用户文库);Crossref 查不到元数据**拒绝写入**(不给文库塞空条目);
  查重本身失败时**也不写**(否则网络抖动就产生重复条目)。
- **三个对话工具**:`zotero_search`(先在自己库里找,别重复下载)、
  `zotero_fulltext`(付费墙文献的合法全文来源:用户本就有访问权)、
  `zotero_add`(写用户私人文库 → `side_effect=True` 走审批;搜索只读不打扰)。
- 未配置凭据时给**配置指引**(去哪拿 API key 和 library ID),而非裸报错。

### 修复:沙箱网络白名单漏域
`DEFAULT_POLICY.net.allow_domains` 缺 `api.semanticscholar.org` 与 `api.zotero.org`
——沙箱一旦开启,Semantic Scholar 检索与 Zotero 全部**静默失效**,且极难归因。
补齐并加测试锁定「白名单 ⊇ 实际访问的域」。

> 说明:psyclaw **本来就默认联网**(沙箱默认 `enabled: False`,lit_search 直连
> OpenAlex/Crossref/EuropePMC)。此前"感觉没联网"是模型未调工具、直接转向编造
> 造成的假象,根因已在 v0.17.1/v0.17.2 修复。

因触发 `capability_map` 700 字符预算,按守卫要求压缩既有表述而非调大预算。

## v0.17.2(2026-07-20)

> 主题:**引用存在性查证**——把"别编造"从规则升级成机器可验的判据。

### 新增:`cite <稿件> --verify` 联网查证(feat-182)
v0.17.1 在**规则层**禁止了凭记忆列文献,但规则是模型可以违反的。本版补**验证层**:
逐条参考文献拿去 Crossref 的 `query.bibliographic` 端点查证,证明它在现实中确实存在。
设计参考 [academic-research-skills](https://github.com/Imbad0202/academic-research-skills)
的 `lookup_verified` 三态,取其精确性优先原则:

- `verified` —— 索引命中**且作者姓氏+年份都对得上**(只对标题会把"同题不同文"
  判成存在;只对作者年份会把同作者同年的另一篇判成存在,故两个条件都要);
  年份留 ±1 容差(在线优先 vs 见刊年常差一年);
- `not_found` —— 索引可达、查了、无匹配 → **疑似杜撰,硬判据,退出码 1**;
- `unresolvable` —— 网络/索引不可达,或该文献类型本就不被收录(中文专著、
  内部报告)→ **只提示不拦截**。把"查了没有"和"没法查"混同会让整套核查失去
  公信力:要么放过杜撰,要么把没被收录的中文文献误判成编造。

为什么离线核查不够(实测):一条格式规整、卷期页码俱全、文内与文末完全自洽的
虚构 JAP 条目,通过了既有的语料溯源与一致性核查(报告显示"✓ 文内引用均见于
参考文献表"),只有联网查证把它揪出来。

超出单次上限的条目如实计入 `skipped` 并显式提示"勿视作已通过"——静默截断会让
"全部通过"名不副实。`tests/test_cite_verify.py` +14 项守住三态语义与边界。

## v0.17.1(2026-07-20)

> 主题:**文献零杜撰 + 修复「装出来是残的」**。两个都是 v0.17.0 及之前所有发行版
> 都有的严重问题,强烈建议升级。另附本地分发包与国内安装快捷方式。

### 修复(最严重):系统提示词曾把「文献编造」合法化
- **现象**:文献检索调用失败后,模型输出「命令行因参数解析问题未能正确执行……
  我切换为手动列举——基于记忆回顾近年发表在 JAP/PP/AMJ… 的 10 篇核心文献,
  均标注 ⚠ 未核实」,整段书目全系编造。
- **根因不在模型,在规则**:`context.py` 系统提示原文写
  「④引用反杜撰——凭记忆的文献条目一律标『⚠ 未核实』,哪怕确信存在」——
  等于**贴个标签就放行编造**,模型是严格照规则执行的。
  `agents/writer.md` 有同款后门(「凭记忆的引用一律标未核实」)。
  更早的 feat-093 对抗评估其实抓到过同一失败,但当时的修法(标注)太弱,于是复发。
- **改成零杜撰**:书目条目(标题/作者/年份/期刊/DOI)**只能来自真实检索返回**;
  「标注未核实」明确写为**不是豁免**;检索失败时唯一正确动作是
  **如实报失败+原因+下一步,然后停**,禁止「切换为手动列举/基于记忆回顾」话术;
  凭记忆只能谈领域概况,不得落成条目。写作 agent 比照统计数值的既有范式,
  改为占位「(待检索补引:…)」+ 文末待补引清单,由 lit_search 检索后回填。
- `tests/test_no_fabricated_citations.py`(4 项)守住该契约,
  `test_context.py` 的旧弱断言同步升级——防再次退回「贴标签即可」。

### 修复(严重):数据文件不进 wheel
- **31 个数据文件不随包分发**:`pyproject.toml` 只配了 `packages.find`、没配
  `package-data`,导致 `uv tool install` / pip 装出来的 psyclaw **没有任何 skill、
  gates 无判据**(`gates/PSYCLAW.md`、`rules.yaml`、6 个 agent 提示词、
  `methods.json`/`scales.yaml` 等心理学数据、全部 10 个 skill 统统缺失)。
  源码直跑一切正常,故一直未被发现。补 `[tool.setuptools.package-data]` 递归 glob;
  `skills/nature-review` 这类连字符目录不是合法包名、`packages.find` 收不到,只能靠 glob。
  验证:干净 venv 装 wheel → `psyclaw gates` 判据齐、`list_skills` 出 10 个。
- `tests/test_package_data.py`:静态校验每个非 `.py` 数据文件都被 package-data glob 覆盖,
  新增未覆盖扩展名立刻红(源码测试绿但 wheel 残的盲区就此堵上)。

### 界面
- **开屏瘦身**:wordmark 已喊过品牌,下面不再叠「重复品牌名 + 中英同义反复 +
  功能清单 + 口号」四层;`mode` 行去掉英文同义句。hero 两行 → 一行。
- `tests/test_startup_hero.py` 反向断言这些冗余不得回潮。

### 分发
- 一键安装脚本默认 tag 从 v0.15.0 同步到当前版本,并加
  `tests/test_installer_version.py` 断言「脚本默认 tag == `__version__`」,
  防再次落后(v0.17.0 发布时它还钉在 v0.15.0)。

## v0.17.0(2026-07-20)

> 主题:**对话即能力——所有 CLI 命令自动工具化 + 文献检索/下载升级 + Codex 风界面 +
> 自更新**。用户以对话形式工作,能力全部做成模型可直接调的工具;文献从"跟知网反爬对抗"
> 转向"可靠公开 API + 引用滚雪球 + 机构权限下载"。feat-174~181,测试 2083→2132 绿。

### 对话即能力(feat-179/180)
- **所有 CLI 命令自动工具化**(feat-180):从 argparse 自省,把每个子命令(排除交互/系统类)
  自动包成对话工具——check/export/method/cite/review/preregister/design/assume… 全成工具,
  写盘类需批准、只读自动执行;**新增命令自动覆盖**,不用逐个手写。你在对话里说"把这稿导成
  Word""投稿前查规范",模型直接做,不再甩命令。
- **文献对话工具**(feat-179):lit_search(多源检索)/ lit_snowball(引用滚雪球)/ lit_download
  (下载 OA+机构权限全文),手工优化的对话体验;系统提示引导"直接调工具、别甩 CLI"。

### 文献检索 / 下载升级(feat-177/178)
- **更好的文献查找**(feat-177):加 Crossref(中文核心期刊 DOI 覆盖)+ Semantic Scholar
  (摘要/TL;DR/被引数)+ **引用滚雪球**(种子 DOI 沿引用网络扩展,综述正道)——替代脆弱的
  网页桥;默认源加 crossref。
- **全文下载打通机构权限**(feat-178):不只 OA,LibKey 全文直链 / 机构 IP 授权也真下载;
  EZProxy 需会话的给浏览器链接;付费墙如实跳过(不绕过)。lit --download 覆盖所有命中。

### 界面 / 分发(feat-174/175/176)
- **Codex 风 REPL**(feat-176):极简 `›` 提示符 + prompt_toolkit 底部固定状态行
  (模型 · 模式 · 目录)。
- **启动界面 hero 风格**(feat-174):ANSI Shadow 巨型 wordmark + eyebrow + teal accent,
  呼应 landing page;窄终端降级。
- **psyclaw update 自更新**(feat-175):装了之后一条命令同步到最新,形态自适应
  (source/uv-tool/pip)+ 国内镜像自动。

### 审稿 skill(feat-181)
- **嵌入 nature-review 审稿 skill**:mumdark/nature-review-studio(1287 篇 Nature 审稿报告
  蒸馏)提炼版——12 关注类别 / 6 审稿人映射 / 21 回复策略 / 8 行动状态,review+respond 流程,
  loader 自动发现、对话可调;通用 `skill install <github-url>` 装全量(git 浅克隆,镜像感知,
  **强制 https + -- 哨兵挡 argv flag 注入**)。

## v0.16.0(2026-07-18)

> 主题:**lit 自动驱动机构库桥接(知网)+ 交互基础设施内置(prompt_toolkit)+ 一键安装 +
> 已知交互 bug 清零**。lit 从"只打公开 API"升级为"公开 API + 自动驱动用户真实浏览器进
> 知网补检合并";prompt_toolkit 提为核心依赖,中文输入与命令下拉从根上好使。feat-166~170,
> 测试 2045→2072 绿。

### lit 自动机构库桥接(feat-168/169/171/172/173)
- **多机构库 + 首次一键装**(feat-172/173):中文机构库集扩为**知网 / 万方 / 维普**三库,
  `lit --db 知网,万方` 指定或按查询语言自动选(中文→三库,英文机构库需交互检索暂不自动);
  **首次没装 WebBridge 时直接问「现在安装吗?[Y/n]」并一键装**(下载二进制→起守护→开扩展页;
  非交互绝不阻塞,问过一次不再打扰)。登录态由用户真实浏览器提供,psyclaw 不碰账号。
- **默认 auto + 一步开启**(feat-171):默认(无需 --bridge)可用即自动进机构库;不可用则据
  缺哪一步给确切命令(install/start/status)。
- **lit 自动调 WebBridge**(feat-169):公开 API(OpenAlex/EuropePMC)检不到知网/万方的
  中文文献。新增 `litbridge`——psyclaw 自己驱动 Kimi WebBridge(复用用户已登录的真实
  浏览器):navigate 到知网检索 → evaluate 注入 JS 抽取题录 → 归一成 lit schema → 与
  公开 API 结果按(doi|题名)去重合并,并入展示/缓存/PRISMA 计数。**默认(auto)可用即自动
  进知网(无需 --bridge);不可用则给一步开启指引(据缺哪一步:psyclaw webbridge
  install/start/status)**。`lit --bridge` 强制、`--no-bridge` 关闭。全 fail-safe,仓内零浏览器逻辑
  (经 webbridge.call 外移)。**注:知网 DOM 选择器为 best-effort,集中在 _DB_PROFILES,
  失配时降级提示人工/lit --import,不中断 lit。**
- **主动指路 + 诚实提示**(feat-168):桥不可用时主动提示机构库检索路径;prompt_toolkit
  引导改醒目 + 据安装方式给正确装法。

### 交互体验根治(feat-167/170)
- **prompt_toolkit 提为核心依赖**(feat-170,用户拍板):装 psyclaw 即自带,REPL 实时命令
  下拉(↑↓ 选择)+ 中文宽字符输入根治;缺失降级 readline 路径保留。CLAUDE.md 铁律相应
  更新(交互基础设施可内置,统计库仍一律外移)。
- **内置 skill 不再对模型隐藏**(feat-167):capability_map 只列命令、从不告诉 chat 模型有
  sample-size/confound-control/pingouin 等结构化 skill;skills_catalog 每轮注入内置 skill
  目录,模型主动路由。
- **中文输入光标乱码修复**(feat-167):自研 raw reader 的 _visible_len 中文按 1 列算致光标
  错位、重画覆盖成「公yclaw ❯」;改用东亚宽度感知(中日韩 2 列),与输出框同口径。

### 分发:一键安装(feat-166)
- **镜像感知一键安装脚本**:`curl -fsSL .../install.sh | sh`(macOS/Linux)/
  `irm .../install.ps1 | iex`(Windows)。探测 GitHub 可达性,不通切 gitclone.com +
  aliyun PyPI 镜像,uv 装(自带管理 Python)。安全加固:不经第三方代理拉 Python 二进制、
  第三方代码镜像用途显式披露、官方 uv 安装器标注可信来源。

### 修复(发行自检,feat-165)
- 参考文献题名以 ?/! 结尾的双标点(APA7 不补);method 纯 ASCII 别名子串误匹配
  (power 命中 empower → 改词边界)。

## v0.15.0(2026-07-18)

> 主题:**三命令重定位(cite/scale/method)统计全外移 + 对话体验缺陷两轮清零 +
> 开箱即用(MCP 惰性化/AJS 期刊包/new 建项)**。核心是把 cite/scale/method 从"静态
> 知识词典"改造成"编排 + 格式化 + skill 路由"——凡统计一律外移到成熟库/MCP,
> psyclaw 只生成可复现脚本、不内联算。feat-138~165 全部落地,测试 1853→2045 绿。

### 三命令重定位(feat-161~165,用户拍板定义)
- **cite = 引用文章 + 引文核查**:
  - `cite --make <json>`(feat-164):文献元数据 → 规范 APA7 参考文献 + 文内引用
    (1/2/3+ 作者 et al./页码 en dash/>20 作者省略),纯字符串无网络无统计;
  - `cite <稿件>`(feat-162):引文核查(反杜撰),并删除方法学背书静态库
    evidence.json(不全/会过时/与"可核实"矛盾)——文献支撑改走真实检索 `lit`。
- **scale = 量表分析(虚伪作答检查 + 信效度)**(feat-161):`score` 加虚伪作答体检
  (longstring/漏答率/直入式,纯计数零统计,跑原始应答不被反向计分掩盖)+
  `score --reliability` 生成委托 pingouin 的 Cronbach α 脚本;α/ω/CFA/马氏距离外移。
- **method = 方法学 skill 路由**(feat-163):从方法词典改成路由到结构化 skill——
  `method 样本量` → sample-size(功效分析,委托 statsmodels 解 N + 敏感性)、
  `method 无关变量控制` → confound-control(区分真混淆/中介/对撞,纯设计);
  未命中退回 methods.json 词条(定义型保留)。
- **发行自检修复**(feat-165):参考文献题名以 ?/! 结尾的双标点、method 纯 ASCII
  别名子串误匹配(power 命中 empower)两处缺陷修复。

### 对话体验缺陷清零(feat-143~153,两轮真实会话复盘)
- **能力自知与反重造**(feat-144/150/152):系统提示注入 psyclaw 能力地图并禁止
  手搓轮子;检测 save 的脚本手搓 python-docx/裸 matplotlib/手画概念图 → 落盘后
  软提示纠偏(改用 export/apply_style/graphviz)。
- **主动执行与诚实**(feat-145/148/153):长脚本边跑边流式显示(消灭空屏);第一人称
  「我来读/我来跑」+ 一次只问一个问题;命令联想随实际 input backend 说实话。
- **输出观感**(feat-143/146/147/149/157/158):行内 Markdown 强调解析进 Word、
  斜杠命令联想 + 打错给建议、256 色语义配色、空回复不渲染空框、输出框圆角闭合、
  启动横幅对齐修复。
- **跑脚本环境**(feat-151/154):注入 PYTHONPATH 让生成脚本可 import psyclaw;
  解释器按平台检测本机可用(win python→py→python3,posix 反向)而非硬编码。

### 开箱即用与项目组织(feat-138~142/155/156/159/160)
- **MCP 惰性化**(feat-138):`/agent on` 不再逐服务器冷启子进程 list_tools
  (npx 系拖到分钟级);按缓存/registry tools 键惰性登记,首调才起进程。
- **AJS 期刊技能包**(feat-139):`journal install <刊名>` 与 `start --journal` 从
  AJS mono-repo 稀疏检出目标期刊包(缩写/中文名/近似候选),装完 check/export 默认带刊。
- **协助水平与注释**(feat-140/141/142):产物归位软约定;`assist novice|standard|
  expert`;`annotate <file> [--review]` 按协助水平定注释密度 + 三面审查。
- **new 建项**(feat-159/160):`psyclaw new <名>` 以文件夹组织新建分析(状态隔离)+
  引导 README(研究流程心智模型 + 代表性命令流)。
- **token 计量与省量**(feat-155/156):CJK 感知 token 估算 + 每轮显示 + 详细页;
  系统提示静态前缀重排为缓存友好,同效果省 token。

## v0.14.0(2026-07-14)

> 主题:**三轮对抗评估缺陷清零 + 文献查找全链(检索计划→浏览器桥→PDF 落盘)**。
> 用埋雷研究包对 chat/run/check 三入口做了三轮对抗评估(31→52→100 分),
> 立案的 13 项缺陷全部修复并活体复测;文献侧从"检索"补齐为"计划→机构库
> 桥接→回灌→矩阵→PDF 规范落盘"的完整闭环。

### 修复(三轮对抗评估,feat-090~102)
- **交互层**(feat-090/091):LLM 生成期 ESC 可中断(EscapeWatch cbreak 监听 +
  stream_interruptible 线程消费,等首 token 也能取消)、裸 quit/exit 认作退出;
  审批模式(auto/default)首屏常显。
- **chat 铁律硬约束**(feat-092/093/098):统计外移(「手写个 Welch t」被拒并给
  外移路径)、引用反杜撰(凭记忆条目一律标「⚠ 未核实」,哪怕确信存在)、
  「边缘显著」话术双向根除(检查层升阻断 + 生成层禁令,自己不用也不建议)。
- **meta/analysis 流水线**(feat-094/095/100):行清洗单一真源(负 se/倒置 CI
  换算前拒绝),生成脚本内嵌同口径清洗——对脏表不再崩溃且剔除逐行呈报;
  写作步换 writer 角色(稿件不再写成执行独白);analysis 结局语义选 DV
  (不再拿基线 pre_score 当因变量),重复被试/缺失码/微型组三警示进画像步。
- **质量检查升级**(feat-096/097/099):效应量+CI 缺失升阻断级;诚信启发式层
  (因果表述×非实验设计[含纵向观察]、亚组 HARKing、事后剔除邻近窗口、
  p≥.05 谎报显著、|d|<0.2 夸大、低 α 洗白、选择性报告);cite-check 零语料
  一致性(文内引用 ↔ 参考文献表双向比对,不在文献表=硬判据)。
- **工具调用力学**(feat-101/102):```shell 块多行命令(引号/续行/heredoc)
  不再逐行拆碎审批执行;@小 CSV(≤4KB)全量注入,大 CSV 显式截断告知。

### 新增:文献查找全链(feat-103/104/107/108/109)
- **`lit --plan` 检索计划包**:中英布尔检索式(LLM 定制/模板兜底)+ 公开 API
  路线 + 机构库(知网/万方/WoS)浏览器桥接五步提示词(内嵌「读当前页不猜测/
  未显示标注/长输出写文件」纪律)+ 纳入/排除标准检索前声明 sidecar。
- **`lit --import` / `lit --matrix`**:桥接结果表(MD 表/CSV)导入语料(去重+
  PRISMA 留痕)→ 文献矩阵骨架(「待核查/全文未获取」约定),键与 cite-check
  语料同源,综述引用可溯源到矩阵行。
- **浏览器双引擎**:Kimi WebBridge 接入(`psyclaw webbridge install|status|start`,
  官方同源安装+守护进程+装技能+默认浏览器识别[macOS LaunchServices,Arc 半兼容
  诚实告警]+扩展商店页自动打开,agent 循环并入 9 个 web__* 真实浏览器工具);
  浏览器 MCP 备选(registry browser 条目,chrome-devtools-mcp,Chromium 自动
  适配 + --browserUrl 附连模式)。登录永远由用户人工完成。
- **`lit --download` / `--fulltext` 真下载**(feat-109):OA PDF 候选链依次尝试,
  %PDF 魔数校验(落地页绝不冒充 .pdf),<一作姓>_<年份>_<标题>.pdf 规范命名
  落 outputs/pdfs/,成败逐条如实呈报;裸 DOI 经 OpenAlex 补题录命名。

### 评估资产
- evalcase/(第一轮埋雷研究包)、evalcase2/(第二轮换雷型)、evalcase3/
  (第三轮多轮交互+工具调用力学 RUBRIC)随库存档,供回归复用。
- 三轮评分:31/100 → 52/100 → 100/100(修复后终测,均对磁盘与独立真值核验)。


## v0.13.0(2026-07-13)

> 主题:**交互心智模型收敛(chat / run / auto)+ v0.12 全面评审修复**。
> 公开入口统一为三个动词;随后对 v0.12 做了一轮 max 强度 code-review
> (10 查找角度 → 逐项对抗验证 → 15 项确认缺陷),本版全部修复清零。

### 修复(v0.12 code-review,feat-079~088)
- **真结果守卫结构化**(feat-079):`MCPClient.call_tool_status` 返回 {ok,text},
  守卫拒 传输失败/骨架哨兵(`SKELETON_MARK` 单一来源)/`{"error"}` 载荷/NaN·inf
  数值——MCP 报错串不再冒充统计结果进稿件;`extract_meta_rows` 行过滤,坏单元
  剔除呈报,k<3 不算 Egger。数值实测与 v0.12 基线逐位一致。
- **POSIX 方向键**(feat-080):`_get_key` 改 fd 级 `os.read`——↑↓ 在 macOS/Linux
  不再被缓冲吞字节误判成 ESC 取消整题;TCSADRAIN 保 type-ahead、UTF-8 多字节读满、
  EOF 不再 100% CPU 忙等;单选空格=选定;新增 pty 真键盘测试(此前零覆盖)。
- **批准范围加固**(feat-081):`python -c`/`bash -c`/`uv run`/sudo/env 前缀等
  「圈不住行为」的形态一律不泛化;Windows `.exe` 剥后缀恢复 `git.exe status ≠ push`;
  复合命令不截断防前缀碰撞。
- **期刊名拼错不静默**(feat-082):`--journal` 不识别时 sidecar 记痕、CLI 告警
  +exit 1——required 期刊的 replication 质量检查不再被无声解除。
- **教训系统三修**(feat-083/087/088):confirm 继承再现次数(强度不归 1);
  落卡批量化+按实际数如实报(REPL/CLI 语义收敛);toolloop 教训每轮全量重放,
  长任务不再被上下文修剪失忆重踩。
- **eval 输出健壮**(feat-084):GBK 管道 emoji 降级不崩、报告先落盘、`--json`
  stdout 纯净、重复 `--case` 去重。
- **选择器 CJK 宽度**(feat-085):按显示宽度截断/折行(中文每字符 2 列),
  中文选项不再物理换行破坏原地重画;`ui._ANSI_RE` 扩到全部 CSI。
- **图片渲染路径**(feat-086):@图片 直渲已知路径(括号/盘符文件名不再误报
  「终端不支持」);强制协议不越 TTY,不往管道/日志灌 base64。

### 改进
- **运行行为统一**(feat-078):`run` 公开收敛到 literature/analysis/meta/qualitative 四条稳定
  workflow,默认连续执行;新增 `--confirm-each`、`--exploratory`、`--resume`。每步写原子检查点,
  恢复时校验流程定义、目标、输入和产物。`prepare` 成为研究准备公开命令。`auto` 验收失败改记
  “需要处理”,本轮避免空转、下次可重试;迭代上限按单次运行计算。旧参数和旧入口继续兼容。
- **用户术语统一**(feat-077):用户界面、CLI 帮助、研究准备清单、内置研究指令与当前文档
  不再使用生硬的直译词。研究开始前统一称“前置检查”，产出规范校验统一称“质量检查”，
  原有 17 项澄清内容统一称“研究准备项”。`gates` 命令、规则 ID 和内部字段保持兼容。
- **交互心智模型收敛**(feat-076):公开入口统一为 `chat / run / auto`。缺省 `psyclaw`
  进入 Chat;`run analysis|meta|literature|qualitative|research|task` 路由到既有 workflow/
  pipeline/loop;`auto` 复用自主回路。旧 `agent/loop/*-loop/auto-loop/research/repl` 保持
  兼容,退出默认帮助与主文档。REPL 同步提供 `/run`、`/auto`、`/approval ask|auto`、
  `/access open|safe`,旧 `/agent /research-loop /yolo /safemode` 仍可调用。
- README、教程、命令地图、架构文档、启动横幅、状态建议、文件分析提示和内置研究 skill
  已统一到三入口模型;新增共享路由 `psyclaw/modes.py`,不复制现有执行逻辑或放松质量检查。

## v0.12.0(2026-07-11)

> 主题:**自学习进 agent 模式 + 数据→结果→稿件闭环补完 + 可评测(eval harness)**。
> 把 v0.11 的错误自学习/图片渲染从 REPL 扩到 agent(toolloop),补上 v0.10 遗留的
> 「真结果回填稿件」,再给整个编排层配一套确定性离线评测;期间根据用户实测反馈
> 修了 4 个交互问题。

### 新增
- **eval harness**(feat-073):`psyclaw eval` 确定性离线评测——6 用例 28 检查覆盖
  分析/元分析编排、文献初筛诚实降级、门禁 fail-closed、错误自学习、toolloop 纪律;
  不调 LLM、不联网、不依赖统计库,秒级复跑;`--case`/`--json`,报告落
  `.psyclaw/eval_report.json`,有失败退出码 1。用例崩溃记失败 check,绝不静默。
- **replication-package 声明**(feat-074):`provenance --journal <期刊>` 遇
  `data_availability=required`(Psych Science/JPSP/Psych Bulletin)时强制生成
  replication-package 声明(脚本 sha256+数据指纹+环境清单,文本可直接放进稿件
  数据可得性节);新门禁 `REPRO.replication_package` 拦「要求却未声明」,
  非强制期刊/旧 sidecar 放行(门禁只增不删)。
- **错误自学习 + 图片渲染进 agent 模式**(feat-065):toolloop 失败工具结果当轮
  蒸馏环境教训回灌止损(只看 ok=False,防把读到的日志当本机事实),随结果返回
  `lessons` 由 REPL/CLI 落卡;`render_images_in_text` 共用,agent 出图也内联显示。
- **教训卡正向加固**(feat-066):同一环境教训再现 → active 卡强度+1(记
  `reinforced_ts`)、pending 卡 hits+1;注入按强度降序,CLI 显示再现次数。
- **@图片 引用内联渲染**(feat-069):`@路径` 是图片时终端直接显示,上下文只注入
  元信息;修掉此前把二进制乱码灌进上下文的问题。
- **pystat 元分析闭环**(feat-072):pystat MCP 新增 `pystat_meta`(DL 随机效应:
  合并效应+95%CI+I²/τ²/Q+Egger);meta 流程 best-effort 直跑落
  `outputs/meta_result.txt`;写作步把 pystat **真跑结果**注入上下文(结果节只引用
  真实数值,效应量+CI 必报);`_real_result` 守卫——「统计库未安装」的脚本骨架
  不算真结果,不制造『看着像跑过了』的假象。[stats] 数值实测:statsmodels/pingouin
  真装真跑,生成脚本与 MCP 工具输出数值一致。

### 改进 / 修复(均来自用户实测反馈)
- **确认提示自解释**(feat-067):`[Y/n/a=…]` 改
  `[回车=同意 / n=拒绝 / a=同意且本会话此类不再问]`,行为不变。
- **选择器改原地内联**(feat-068):弃 prompt_toolkit 全屏蓝色对话框(Windows 上
  突兀),Claude Code 式 `_pick_inline`:↑↓/数字/空格/回车/Esc/打字自由作答,
  ANSI 原地重画不清屏不进备用屏。
- **「全部同意」按命令前缀限定**(feat-070):对 `git status` 说 a 不再放行所有
  shell 命令——`cmd_approval_scope` 按程序/子命令归类(`git status ≠ git push`,
  复合命令不泛化);危险命令红线不变(永远逐条问)。
- **选择器看得见方案详情**(feat-071):按终端宽度截断 + 高亮项下方 2 行详情区
  给全文;系统约定选项文字自包含、方案细节先写正文。

## v0.11.0(2026-07-09)

> 主题:**REPL 交互体验大修 + 错误自学习闭环 + 图片内联渲染**。
> 起于用户一次真实的 MNE/ERP 分析实测——把「反复问 y、输入被吞、卡住等『继续』、
> 每轮重踩环境坑、图只能看路径」这些卡点逐个治本。

### 新增
- **`/dump` 导出对话**(feat-055):`/dump [路径]` 导出当前对话为 Markdown;`/dump --full`
  连同平时不展示的隐藏上下文(system 提示 / 滚动决策备忘 / 每轮持续注入的约定片段)一并导出。
  纯渲染在 `psyclaw/transcript.py`,拒写受保护的 `data/raw`。
- **`/yolo` 审批模式**(feat-056):开启后命令 / 文件覆盖 / 工具副作用**自动放行**,只有命中
  红线的危险命令(`rm -rf`、`push --force`、`DROP TABLE`…)仍问人——「只在必要时请求人介入」。
  `data/raw` 与密钥文件始终硬拒。`config approval=yolo` 设默认。
- **确认支持「全部同意」**(feat-064):非危险副作用的确认改为三态 `[Y/n/a]`——选 `a` 则
  **本会话该类**(执行 shell / 覆盖文件 / 工具副作用)不再逐条问,「确认一次、同类就统一」;
  比 `/yolo` 更细粒度。危险操作永远逐条问、不给「全部」(红线不放松)。
- **错误自学习**(feat-058):命令失败经 `distill_env_lessons` 蒸馏出可复用的**环境教训**
  (命令不存在 / 模块未装 / API 改名),记入本会话记忆**每轮注入止损**,并落 `memory` 待确认卡
  (跨会话,经 `/memory confirm` 生效)——不再每轮重踩 `python`→`python3`、缺 mne、`erpcore` 改名。
- **环境教训卡自动失效**(feat-059):环境恢复了(装上库/命令有了)就自动归档过时的负卡,别反向
  误导模型。`memory.archive_lesson` 落实「被推翻则归档」;启动秒验证命令类(`shutil.which`),
  `/memory verify` 全量再验证(含 module/attr 真跑 import);只在**确证已恢复**时失效(防误删)。
- **终端内联渲染图片**(feat-061):`/img <路径>` 手动、命令出图**自动**内联显示(分析脚本 print
  出的图直接出现在对话里)。纯 stdlib(终端解码,只 base64 字节):iTerm2 / kitty 协议,按环境探测
  iTerm2 / WezTerm / VSCode / Warp / kitty;`config image_protocol` 可强制。

### 改进 / 修复
- **自动跟进不再中途卡死**(feat-057):流式路径的命令/读取跟进改由 **no-progress 检测**停机
  (连续重复相同请求即判原地打转),低深度上限(原 3 步)降级为高位安全兜底(100,`config` 可调)。
  多步分析(下载→装依赖→跑→报错→修→重跑)一口气跑完,不再停下等人说「继续」。
  no-progress 只在**自主回合**(YOLO 自动跑 / 自动读)计数——用户在逐条确认(打 y)本身就是
  在推进,不会被误判成「原地打转」而掐断(feat-063)。
- **确认框不再与命令回显串行**(feat-056):`_ask_yn` 经 `ui_input.safe_prompt` 用 `\001\002` 包裹
  彩色码,修 readline 把 ANSI 算进光标宽度导致回显错位;超长命令单独打一行、提示只留一句短话。
- **选择器非编号输入不再被吞掉**(feat-060):单选提示「编号」时用户打了 `y` 之类会被静默丢弃、
  变死胡同;现在非编号的输入当作对该问题的**自由作答**转发给模型继续,只有回车才算跳过。

## v0.10.0(2026-07-07)

> 主题:**数据→结果端到端闭环**——analysis 流程直接经 pystat MCP 出结果。

### 新增
- **analysis 分析步接 pystat MCP**(feat-053):`psyclaw analysis <data.csv>` 的分析步此前
  只生成 `outputs/analysis.py` 让用户手动跑;现在在生成脚本后**自动经 pystat MCP 直接运行**
  推荐的分析,把结果写到 `outputs/analysis_result.txt`。`pystat_bridge` 把 `recommend_analysis`
  的检验类型 + 角色列纯映射到 pystat 工具(t 检验/方差/回归/相关/描述),经 MCP 客户端执行:
  装了 `[stats]` 则回带**效应量 + 95% CI** 的真结果,未装则回 pystat 的降级脚本——无论哪种都多
  一个具体产物。全程 fail-safe:pystat 不可用/异常绝不阻断流程(生成的脚本仍在)。
  至此「数据 → 画像 → 推荐分析 → pystat 出结果」端到端闭环:v0.5 让 agent 能调 MCP、v0.8 建了
  pystat 后端、本版把 workflow 也接上。

## v0.9.0(2026-07-07)

> 主题:**一键配置基础环境**。

### 新增
- **`psyclaw setup --env`**(feat-051):一条命令诊断并配好跑 psyclaw 所缺的基础环境——
  检查 ① 配置文件是否已建 ② LLM provider 是否配了 API key(否则只能走 mock 占位)
  ③ `stats` 组(pingouin/pandas/scipy:pystat 真算、跑生成的统计脚本)④ `full` 组
  (prompt_toolkit/rich:REPL 实时联想)。每项给 ✓/✗ + 确切修法 + 能否自动装;
  加 `--online` 则一键 pip 装可自动修的缺失组(stats/full),不能自动的(API key)列为待手动。
  装失败如实报告、不阻断。

## v0.8.0(2026-07-07)

> 主题:**闭环「统计外移到 MCP」**——agent 现在能直接调用统计后端。

### 新增
- **pystat MCP 服务器**(feat-049):`psyclaw/mcp/servers/pystat_server.py`,委托
  pingouin/pandas 的常规统计后端(描述统计、t 检验、相关、单因素方差、多元回归、选检验指引)。
  照既有 MCP 惯例:统计库在则真跑并返回带**效应量 + 95% CI**的结果(符合门禁),不在则返回
  可直接运行的脚本骨架(不假装算结果)。本体顶层零统计 import——统计只在工具被调时惰性发生。
- registry 早已声明 `pystat` 却一直缺 server 文件与 `command`,导致 v0.5 的 agent-MCP 接入
  (feat-040)浮不出它;本版补齐后,`agent`/REPL 的工具集自动多出 6 个 `mcp__pystat__*` 工具——
  **agent 可在多步推理里把 t 检验/方差/回归直接委托给 pystat**,「统计外移到 MCP」自此闭环。

## v0.7.0(2026-07-07)

> 主题:**REPL 交互体验**——修方向键/历史/光标(用户报告的 `^[[A` 问题)。

### 修复
- **REPL 方向键/历史/光标**(feat-047):此前在未装 `prompt_toolkit` 的环境(如 `uv tool`
  默认装的解释器)里,REPL 按方向键会漏出 `^[[A`、没有命令历史、光标不能左右移动——根因是
  非 prompt_toolkit 的 TTY 落到了自研逐键 raw reader。现改为优先走 stdlib **readline** 后端:
  ↑↓ 翻历史、←→ 移光标、Ctrl-A/E/K 等键位、以及 `/` 命令 Tab 补全全部可用;readline 缺失
  (Windows 等)再退回原 raw reader。装了 `psyclaw[full]` 的仍走 prompt_toolkit(实时联想下拉)。

## v0.6.0(2026-07-07)

> 主题:**多轮对话 + 工具调用稳**。审计工具循环、实测复现真实故障点后逐个加固。

### 工具调用健壮性(多轮不出问题)
- **参数规范化**(feat-043):模型把 args 写成 `list` 或双重编码 JSON 字符串
  (`"args":"{...}"`)时,此前内置工具 `a.get()` 崩且被**误标成功**——现统一规范化
  (JSON 对象字符串自动解析、非对象报错引导模型重发),`name` 须非空字符串,工具异常如实标失败。
- **无进展检测**(feat-044):模型反复用相同参数调同一工具、或返回空回复,不再空转到迭代
  上限——有限追问后 `stopped=no_progress` 收敛,不静默、不卡死。
- **消息序列不变量**(feat-045):每次调 provider 前规整消息(去空 content、合并连续同角色、
  首条必为 user),防多轮回灌拼出非法序列触发 Anthropic/OpenAI 的 400。
- **多轮集成测试**:一段贯穿正常调用→畸形 args 自纠→截断续写→未知工具→重发→答案的真实
  序列,断言全程工具不崩、失败如实上报、provider 只收到合法消息。

## v0.5.0(2026-07-07)

> 主题:**编排纵深——agent 真正会用 MCP** + provider 健壮性 + agent 可观测。
> (含此前未单独发版的 v0.4 工件:feat-036/037/038。)

### 编排纵深:agent 接入 MCP(统计外移从"目录"兑现成"可调用")
- **MCP stdio 客户端**(feat-039):`psyclaw/mcp/client.py`——JSON-RPC over stdio,
  惰性起子进程 + initialize 握手 + 超时 fail-safe;进程异常/坏 JSON/服务器报错优雅降级不抛。
- **agent 循环接入 MCP 工具**(feat-040):`agent`/REPL 的工具集自动并入**已启用+健康**的 MCP
  服务器工具(`mcp__<server>__<tool>` 前缀、fail-closed 批准、客户端进程级复用、连接失败不拖垮)。
  例:装了 MNE 的机器上 agent 可直接调 `mne_info`/`erp_components` 等做 EEG/ERP 分析。
  `PSYCLAW_MCP_TOOLS=0` 可整体关闭。

### 长会话可靠性
- **compact_history LLM 蒸馏**(feat-041):超预算压缩时,有 key 的 provider 会把被移出上下文的
  早期轮次蒸馏成**结构化决策备忘**(比规则截断保真);无 key/异常/离线 → fail-safe 回落规则蒸馏。

### provider 健壮性 + agent 可观测(v0.4 工件)
- **provider 网络重试**(feat-036):429/5xx/网络异常首字节前指数退避重试(≤3 次);HTTP 错误读
  响应 body 显性化;流开始后不重试(防重复消费)。
- **agent 运行痕迹**(feat-037):每次 agent 运行落 `.psyclaw/agent_runs.jsonl`,
  `psyclaw agent --history [n]` 回看最近 n 次。

### 其他
- 版本号 0.3.0 →(跳过未发版的 0.4)→ **0.5.0**(pyproject + `__version__`)。
- 全量测试 1242 passed。

## v0.3.0(2026-07-07)

> 主题:**agent 执行面安全加固 + 长会话可靠性**(「对话长期维持、不中途停」)。

### 长会话可靠性
- **截断防护**(feat-030):provider 输出被 max_tokens 截断时,未闭合的 ```tool 块不再被
  误判为最终答案——检测截断并请求模型重发完整块(连续超限才停,`stopped=truncated` 不静默);
  providers 捕获 `stop_reason`/`finish_reason`(归一化);`PSYCLAW_MAX_TOKENS` 环境变量可配
  (默认 8192);`agent --max-iters` 默认 6→24。
- **上下文滚动修剪**(feat-033):toolloop 循环内旧轮次工具结果压缩为「工具名+输出首行」摘要
  (最近 3 轮保完整),长任务不再撑爆上下文;调用方历史与 assistant 回复不碰。

### 安全加固(外部安全审查 HIGH/MEDIUM 修复)
- **shell 执行 fail-closed**(feat-031):REPL 命令块里的 shell 命令**每条**须人工确认才执行,
  危险模式正则降级为确认提示里的 ⚠ 标签(拒绝清单不是安全边界);psyclaw 进程内子命令保持自动。
- **save_file 路径允许清单**(feat-032):agent 的 save_file 工具只能写项目根内;拒 `../` 逃逸、
  项目外绝对路径、软链接目标、凭据类路径(`.env`/`id_rsa`/`*.pem`/`.ssh`/`.aws` …)。

### 其他
- `normalize_type` 补 22 个中文研究类型别名(『元分析』『文献综述』『质性研究』…)——中文入口
  的技能推荐路由不再落空(feat-034)。
- 版本号统一:`pyproject.toml` 与 `__version__` 对齐 0.3.0(v0.2 发布轮 pyproject 漏改)。
- 修 2 例陈旧 MCP 测试断言(mplus/stata 改 detect: 门控后未同步)。
- 全量测试 1212 passed。

## v0.2.0(2026-07-03)

> 主题:**机制可以复杂,命令要简单**。默认三条路:`status` → `auto-loop` → `check`。

### 命令简单化
- `--help` 只列常用命令(全部命令**照常可用**,`psyclaw commands` 看完整分类,epilog 指路)。
- `psyclaw guide` 重写为决策树;新增手把手教程 `docs/TUTORIAL.md`。
- **`psyclaw status`**:一屏态势(目标/澄清/回路/等人决策直接打印/下一步建议)。
- **`psyclaw check`**:投稿前一键质检(JARS + 引用保真(+期刊风格)+ 复现溯源 + KG 溯源)。

### 用户自定义
- **命令别名**:`~/.psyclaw/aliases.yaml`(全局)/ `<项目>/.psyclaw/aliases.yaml`(项目),
  一行一条 `qc: check --journal xinlixuebao` → `psyclaw qc 稿件.md`。内置命令优先,不可劫持。
- **插件系统**:`.psyclaw/plugins/*.py` 暴露 `register(api)`——注册 agent 工具 / REPL 命令 /
  system 片段;坏插件隔离加载。`psyclaw plugins` / REPL `/plugins`。
- **用户 MCP 注册表**:`.psyclaw/mcp.yaml`(项目/全局)并入目录。
- skills / MCP / plugins 列表统一标注 **内置 / 用户·项目 / 用户·全局**。

### 内置 skill 可同步更新
- `psyclaw skills --sync [name|all]`:带 `upstream.json` 的内置 skill(ctx2skill / opid …)
  从上游仓库同步到 `<skill>/upstream/`,适配层 SKILL.md 保持薄壳。

### 研究编排与学术诚信(0.1 → 0.2 期间累积)
- **auto-loop** 自主科研回路(发现→派发→独立验收→记状态→决定;感知阶段列相关技能包)。
- **cite-check** 引用保真(孤儿引用=疑似杜撰)· **provenance** 复现溯源 · **期刊画像**(`journal`,
  cite-check/provenance `--journal` 定制)· **kg** 带引用知识图谱 · **search** 来源路由检索。
- 门禁可**用户显式跳过**(`--skip-gates`:留痕 `notes/gate_skips.md`,产出标探索性;默认 fail-closed 不变)。

### 交互与感知
- REPL:**键盘选择器**(模型给选项自动弹,方向键/编号)· **文件读取 open/safe**(默认模型可
  ```read 自动读;`/safemode` 切安全模式须 `@` 引用;`data/raw` 恒拒)· **天然保存**(说"存到 X"
  即落盘)· 会话名进提示符 · **agent 模式**(模型自主多步调工具,副作用需批准)。
- **本地项目感知**:有界目录树每轮注入(`data/raw` 只报数不列名);PDF 正文抽取(pypdf 优先,
  stdlib 兜底,乱码不入上下文)。
- **会话持久化**:SQLite+FTS5,`resume` / `session` / REPL `/sessions /rename /search`。

### 生态
- 发现并按研究类型推荐第三方技能包(AcademicForge / AJS,`skills --for <type>`)。

## v0.1.0(2026-06)

- 重定位为纯研究编排 harness:统计整体外移(删 42 手写统计模块),零统计库依赖。
- research 流水线 · 审稿模拟 · clarify 澄清 · 预注册 · 知识目录 + 量表计分 · lit + export ·
  三层记忆 · 学术门禁 gates · REPL · Workflow 引擎(四类研究流程)。
