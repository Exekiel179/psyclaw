# feat-139:start 按目标期刊装载 AJS 技能包 — 设计

## 目标

`psyclaw start` 澄清出**目标期刊**后,从 Awesome Journal Skills(AJS)mono-repo
自动取出对应期刊的技能包装进项目,兑现"零基础勾一下就全程按目标期刊来"。

- 覆盖范围:**任意 AJS 收录刊**(psyclaw 变成按刊名驱动的通用 AJS 安装器,不限自身 5 个心理画像)。
- 安装位置:**项目级为主**(`.claude/skills/`)+ `--global` 可选(`~/.claude/skills/`)。
- 定位不变:psyclaw 只**编排/消费**外部技能包,**不重造**任何期刊内容包(与"统计外移"同源哲学)。

## 事实基线(已核查 AJS 仓库)

- 仓库 = 单一 mono-repo `github.com/brycewang-stanford/awesome-journal-skills`,顶层含 `.claude-plugin/`(它本身是个 Claude Code 插件市场)。
- 每个期刊 = 一个顶层目录,命名不统一:`AAAI-Skills` / `China-Economic-Quarterly-Skills` / 中文刊用拼音 `Caijing-Yanjiu`。
- 每个 `[刊]-Skills` 包**内部**是完整插件结构:`.claude-plugin/` + `skills/<子技能>/SKILL.md`(12–18 个)+ `assets/` `resources/` `README`。
  → 真正的 SKILL.md 在 `<包>/skills/<技能>/SKILL.md`(**三层深**);psyclaw loader 现只 glob 到两层。

## 安装机制:git 稀疏检出(方案 A,已定)

`git clone --filter=blob:none --no-checkout --depth 1 <repo>` → `git sparse-checkout set <包目录>` → `git checkout`。
只下目标包的 blob,不拉整个 repo;纯 git、可断点、可走镜像。需 git≥2.25(现代 macOS 满足)。
(否决:B GitHub API 逐文件——未认证限速 60/时,脆;C 全量浅克隆——要下 200+ 包全部,浪费。)

国内网络回退:官方 github.com 不通 → 走 GitHub 镜像(gitclone.com / ghproxy 系)重试。

## 组件

### 新模块 `psyclaw/ajs.py`(四职责,各自可单测)

- `list_packs()`:拉 AJS 顶层目录清单(GitHub git/trees API,小 JSON),本进程缓存;无网返回空+错误。
- `resolve_pack(journal_name, packs) -> {"match": str|None, "candidates": [...]}` **纯函数**:
  归一化匹配(去 `-Skills`/连字符/大小写;英文缩写别名表;中文刊借 AJS README 的"显示名→目录"映射)。
  唯一命中→ match;多个/零命中→ candidates 供选择。**不引随机、可确定性单测**。
- `install_pack(pack_dir, dest, use_mirror=None) -> {"ok", "path", "note", "mirror"}`:git 稀疏检出,
  镜像感知,**fail-safe**(失败给手动 git 命令,不抛)。
- 错误出路(均不中断 start):无网 / 无 git / 克隆失败 / 名字歧义 各有明确提示。

### 改 `psyclaw/mirror.py`

- `github_reachable()`:探测 github.com(复用官方探测缓存模式)。
- `github_clone_url(url) -> str`:不可达时重写为镜像 URL,可达则原样。

### 改 `psyclaw/skills/loader.py`

- `list_skills` 增一条 glob `*/skills/*/SKILL.md`——认 AJS 包布局。**仅加一行 glob,不改既有两条**(行为不回归)。

### 改 `psyclaw/cli.py`

- `cmd_start`:在 intent→skills→sandbox 之后加"目标期刊"一步——问刊名 → `resolve_pack` → 确认(展示包名/来源)→ `install_pack`;非交互 `start --journal <名> [--global]`。回车/空=跳过。
- 新子命令 `psyclaw journal install <刊名> [--global]`:start 复用它,也可单独调用。既有 `psyclaw journal <id>`(看画像)保留。
- 装完把 `target_journal` 写进项目 `.psyclaw/config.yaml`,让 `check`/`export` 默认带该刊规范(默认可被 `--journal` 覆盖)。
- `_SETUP_MODULES` 的 journal 条文案更新(指向 `journal install`)。

## 数据流

```
start → 用户报刊名
  → ajs.list_packs()(拉 AJS 目录清单,可缓存)
  → ajs.resolve_pack(刊名, packs)
      ├─ 唯一命中 → 确认 → install_pack(git 稀疏检出 → .claude/skills/<包>/)
      │                        └─ 官方不通则 mirror.github_clone_url 重试
      ├─ 多候选 → 列出让用户选 → install_pack
      └─ 零命中 → 提示可用近似候选;非 AJS 但 psyclaw 有画像 → 走既有画像(不装包)
  → 记 target_journal 进 .psyclaw/config.yaml
  → loader 下次 list_skills 经 */skills/*/SKILL.md 认出新装的子技能
```

## 错误处理

| 场景 | 处理 |
|---|---|
| 无网络 / API 拉清单失败 | 无法解析→提示"报准确包目录名或跳过";psyclaw 画像仍驱动 check/export |
| 无 git | 打印手动 `git sparse-checkout` 命令;start 继续 |
| 克隆失败 | 官方→镜像重试;仍失败→给手动命令,不崩 |
| 刊名歧义(多候选) | 交互:列候选选择;非交互:报错列候选 |
| 刊名零命中 | 列最接近候选;若 psyclaw 自有画像则回退画像 |

## 测试(纯函数优先,无网可测)

- `resolve_pack`:唯一命中 / 缩写别名(AER→American-Economic-Review-Skills)/ 中文(经济研究→拼音目录)/ 歧义多候选 / 零命中。
- `mirror.github_clone_url`:可达原样 / 不可达重写镜像(`PSYCLAW_FORCE_MIRROR`)。
- `loader`:放一个 `<包>/skills/<技能>/SKILL.md` 结构,`list_skills` 能认出。
- `install_pack`:mock subprocess——成功路径 / 无 git / 克隆非零退出的 fail-safe(不抛)。
- `cmd_start --journal <名> --no-sandbox` 非交互:mock install_pack,验证写 target_journal + 行为不回归。

## 边界(YAGNI)

- 不重造任何期刊内容包;不接 Claude Code `/plugin`(psyclaw 自装自认)。
- 不做包更新/版本管理/卸载(本轮只管"装上";更新以后再立项)。
- 不改既有 loader 两条 glob、不动 check/export 的 `--journal` 语义(只加默认来源)。
