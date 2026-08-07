# System Skill Packs

PsyClaw 把 Skill 的“文件存在、已安装、已启用”分开管理。

## 三层发行

1. `core` 随 PsyClaw wheel 安装，保证离线研究编排和质量检查，锁定启用。
2. System domain pack 由 [packs.json](../psyclaw/skills/packs.json) 定义，按研究设计、定量分析、文献综述、写作审稿和智能体学习分组。
3. 非 core pack 的远程 `sources` 从受约束的 GitHub HTTPS 仓库稀疏安装到 `~/.psyclaw/skill-packs/<pack>/skills`，只检出该领域声明的 Skill，并按 catalog 的 `ref` 同步更新。

安装 pack 会保留来源并默认启用；停用只改变状态，不删除文件。远程 pack 使用独立 Git 目录、`fetch <ref>` 和 detached checkout 更新，不覆盖其他 pack。

## 启用规则

状态依次按以下优先级解析：

1. 锁定 core
2. 项目单 Skill 显式设置
3. 项目 pack 设置
4. 全局单 Skill 显式设置
5. 全局 pack 设置
6. 来源默认值

只有锁定 core 默认启用。其余系统领域 Skill、项目 Skill，以及 Claude/Codex/plugin/cc-switch 等外部 Skill 默认仅 `available`，需要安装领域包或显式启用后才进入 Agent 的默认检索。所有 Skill 仍保留在 Registry，可用 `include_disabled=true` 审计，停用项不会加载正文。

## Agent 工具

- `skill_pack_list`
- `skill_pack_install`
- `skill_pack_update`
- `skill_pack_enable` / `skill_pack_disable`
- `skill_enable` / `skill_disable`

安装、更新和启停都是副作用工具；目录与状态查询是只读工具。

## CLI

```bash
psyclaw skills --packs
psyclaw skills --pack-install research-design
psyclaw skills --pack-update writing-review
psyclaw skills --pack-disable quantitative --scope project
psyclaw skills --enable my-skill --scope global
```
