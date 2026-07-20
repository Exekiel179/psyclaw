# PsyClaw

> 心理学研究编排 Agent CLI —— 文献、统计分析、论文写作润色,用日常语言完成。
> 装好之后不需要记命令:说你要做什么,它去做。

📘 **[使用白皮书(PDF)](docs/PsyClaw使用白皮书_v0.21.0.pdf)** —— 完整用法、对话示例、常见问题,建议先读这份。

---

## 安装

需要 Python ≥ 3.11(用 uv 安装时无需自己准备,它会自动处理)。

**macOS / Linux:**

```bash
curl -fsSL https://exekiel179.github.io/psyclaw/install.sh | sh
```

**Windows(PowerShell):**

```powershell
irm https://exekiel179.github.io/psyclaw/install.ps1 | iex
```

脚本自动探测 GitHub 是否可达,**国内不通时切 gitclone.com + 阿里云镜像**。
可选环境变量:`PSYCLAW_CN=1` 强制国内镜像、`PSYCLAW_EXTRAS=[stats]` 顺带装统计栈。

<details><summary>手动安装 / 离线分发包</summary>

```bash
# uv(推荐)
uv tool install --python 3.12 "git+https://github.com/Exekiel179/psyclaw.git@v0.21.0"

# 国内:换镜像地址 + 国内 PyPI 索引
UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ \
uv tool install --python 3.12 "git+https://gitclone.com/github.com/Exekiel179/psyclaw.git@v0.21.0"

# pip
pip install "git+https://github.com/Exekiel179/psyclaw.git@v0.21.0"
```

**完全无网的机器**:在有网机器上跑 `sh scripts/build-dist.sh`,把生成的
`dist/psyclaw-offline-*.tar.gz` 拷过去,解压后执行 `install.sh` 即可(依赖全部打包在内)。
</details>

---

## 上手

```bash
psyclaw setup          # 首次:配模型服务与密钥(配一次,所有项目通用)
psyclaw new 我的研究     # 建一个独立研究目录
cd 我的研究 && psyclaw   # 进去开始对话
```

进去之后就是打字说话:

```
帮我找工作倦怠与离职意向近三年的研究,15 篇左右
把上面这几篇下载下来
帮我做个中介分析,自变量工作满意度,中介变量倦怠,因变量离职意向
根据分析结果帮我写方法部分
帮我按 APA 规范检查一下,然后导出成心理学报格式的 Word
```

写文件、下载、改动你的文库前都会先问你一句。四个常用入口:

| 入口 | 用途 |
|---|---|
| `psyclaw` | 直接进入对话 |
| `psyclaw new <名称>` | 新建研究(独立目录,目标与进度隔离) |
| `psyclaw resume` | 续接上次会话 |
| `psyclaw status` | 查看进度:目标、待办、最近产出、下一步建议 |

---

## 它能做什么

**文献** — 多源检索(OpenAlex / Crossref / EuropePMC)+ 引用滚雪球;
OA 直接下载,付费墙走你自己的机构权限(LibKey / EZProxy / 浏览器扩展三级降级);
Zotero 文库联动;**交稿前逐条查证参考文献是否真实存在**。

**统计分析** — 不在本体内计算,而是生成可复现脚本委托 scipy / pingouin / statsmodels 运行,
脚本留在 `scripts/` 供他人复现。效应量 + 95% CI 必报,不使用「边缘显著」话术,
确证性与探索性严格区分。也可通过 MCP 接入你原有的 SPSS / Stata / Mplus / R。

**写作润色** — 统计数值只用真实跑出的结果,缺失处占位不编造;JARS 清单检查;
Nature 级审稿模拟(1287 篇审稿报告蒸馏);一键导出 APA7 / 心理学报 / 心理科学版式 Word。

**四类研究流程** — `analysis` / `meta` / `literature` / `qualitative`,
自动串联「设计 → 执行 → 产出 → 评审」,每步留可复现记录。

---

## 三条不可妥协的底线

1. **不编造文献** —— 检索失败就如实说失败,绝不用记忆凑书目;交稿前可逐条查证存在性。
2. **不编造数据** —— 脚本没真跑过,不给带具体数值的「示例结果」。
3. **不碰你的原始数据** —— `data/` 目录只读,永不写入。

---

## 文档

| 文档 | 内容 |
|---|---|
| [使用白皮书(PDF)](docs/PsyClaw使用白皮书_v0.21.0.pdf) | **推荐先读**:完整用法与对话示例 |
| [TUTORIAL.md](docs/TUTORIAL.md) | 分步教程 |
| [COMMANDS.md](docs/COMMANDS.md) | 命令地图(`psyclaw commands` 可随时查看) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构说明(参与开发时看) |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更 |

---

## 参与开发

```bash
git clone https://github.com/Exekiel179/psyclaw.git && cd psyclaw
uv run --python 3.12 --with pytest python -m pytest -q     # 全量测试
python -m psyclaw gates                                     # 质量规则自检
```

开发脚手架(自主循环、计划与状态文件)统一在 [`dev/`](dev/) 目录下,
使用者无需关心。约定见 [CLAUDE.md](CLAUDE.md)。

---

## 血统

claude-code(REPL / 命令 / Tool 抽象)· codex(exec / 审批)· OpenClaw(provider)·
AutoResearchClaw(pipeline / skills / MCP)· learn-harness-engineering(harness 工程实践)。

MIT License
