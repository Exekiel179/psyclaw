#!/bin/sh
# PsyClaw 一键安装(macOS / Linux)——镜像感知,国内可用。
#
#   curl -fsSL https://exekiel179.github.io/psyclaw/install.sh | sh
#
# 环境变量(都可选):
#   PSYCLAW_VERSION=v0.20.0   指定版本 tag(默认最新发行)
#   PSYCLAW_EXTRAS=[stats]    附带 extra(如本机跑统计:[stats];补全体验:[full])
#   PSYCLAW_CN=1              强制走国内镜像(默认:探测 GitHub 通不通自动决定)
#   PSYCLAW_CN=0              强制走官方源
set -eu

REPO="Exekiel179/psyclaw"
TAG="${PSYCLAW_VERSION:-v0.20.0}"
EXTRAS="${PSYCLAW_EXTRAS:-}"
CN="${PSYCLAW_CN:-auto}"

say()  { printf '\033[36m▸\033[0m %s\n' "$1"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# ── 1. 决定用官方源还是国内镜像 ───────────────────────────────────────
gh_reachable() { curl -fsS -m 5 -o /dev/null "https://github.com" 2>/dev/null; }
case "$CN" in
  auto) if gh_reachable; then USE_MIRROR=0; else USE_MIRROR=1; fi ;;
  1|true|yes) USE_MIRROR=1 ;;
  *) USE_MIRROR=0 ;;
esac

if [ "$USE_MIRROR" = "1" ]; then
  printf '\033[33m▸ GitHub 不可达,改用第三方镜像 gitclone.com(非官方,代码完整性不保证);\n'
  printf '  Python 依赖走 aliyun PyPI。不放心可 Ctrl-C,改用官方源手动装(见 README)。\033[0m\n'
  GIT_URL="https://gitclone.com/github.com/${REPO}.git"
  PIP_INDEX="https://mirrors.aliyun.com/pypi/simple/"
  # 注:不自动把 uv 的 Python 下载改道任何第三方代理——interpreter 二进制经不可信
  # 代理执行是供应链风险。uv 从官方拉不到时,见末尾提示自行装 Python 3.11+。
else
  GIT_URL="https://github.com/${REPO}.git"
  PIP_INDEX="https://pypi.org/simple"
fi
export UV_DEFAULT_INDEX="$PIP_INDEX"

# ── 2. 确保 uv 可用(单二进制,自带管理 Python)────────────────────────
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then ok "已检测到 uv"; return 0; fi
  say "安装 uv ..."
  # 官方 uv 安装器(Astral 自有域名 https,与 rustup/Homebrew 同一信任模型)
  if curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh >/dev/null 2>&1; then :;
  else
    # 官方脚本不通 → 退回 pip 从镜像装 uv
    (pip install -i "$PIP_INDEX" -q uv || pip3 install -i "$PIP_INDEX" -q uv) \
      || die "uv 安装失败:请先手动装 uv(https://docs.astral.sh/uv/)或 pipx"
  fi
  # 把常见安装位置补进 PATH,供本次会话用
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv 装完但不在 PATH:请重开终端后重试"
  ok "uv 就绪"
}
ensure_uv

# ── 3. 安装 psyclaw(官方失败自动回退镜像)────────────────────────────
build_spec() {
  _url="$1"
  if [ -n "$EXTRAS" ]; then printf 'psyclaw%s @ git+%s@%s' "$EXTRAS" "$_url" "$TAG";
  else printf 'git+%s@%s' "$_url" "$TAG"; fi
}

# --python '>=3.11':优先复用本机已装的 3.11+,避免在国内强制从 GitHub 拉 Python
PYREQ=">=3.11"
say "安装 psyclaw ${TAG} ${EXTRAS:+(extras: $EXTRAS)} ..."
if uv tool install --python "$PYREQ" --force "$(build_spec "$GIT_URL")"; then
  :
elif [ "$USE_MIRROR" = "0" ]; then
  printf '\033[33m▸ 官方源失败,改用第三方镜像 gitclone.com(非官方,请自行评估信任)...\033[0m\n'
  export UV_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple/"
  uv tool install --python "$PYREQ" --force \
    "$(build_spec "https://gitclone.com/github.com/${REPO}.git")" \
    || die "安装失败。若因缺 Python:先自行装 Python 3.11+(brew/apt/官网),再重试;或手动 uv tool install \"git+${GIT_URL}@${TAG}\""
else
  die "安装失败。若因缺 Python:先自行装 Python 3.11+(brew/apt/官网),再重试;或手动 uv tool install \"git+${GIT_URL}@${TAG}\""
fi

# ── 4. 收尾 ───────────────────────────────────────────────────────────
ok "PsyClaw ${TAG} 安装完成"
printf '\n下一步:\n'
printf '  psyclaw config        # 配 LLM provider / API key\n'
printf '  psyclaw new 我的研究   # 建一个按文件夹组织的分析,cd 进去开聊\n'
printf '  psyclaw --help\n'
if ! command -v psyclaw >/dev/null 2>&1; then
  printf '\n\033[33m提示:psyclaw 不在当前 PATH。请把 uv 的工具目录加进 PATH:\033[0m\n'
  printf '  uv tool update-shell   # 或重开终端\n'
fi
