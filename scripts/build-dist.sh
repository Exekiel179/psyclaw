#!/bin/sh
# 构建本地分发包(wheel + sdist + 全离线整包)。
#
#   sh scripts/build-dist.sh
#
# 产出 dist/:
#   psyclaw-<ver>-py3-none-any.whl    标准 wheel(装时仍需联网拉 prompt_toolkit)
#   psyclaw-<ver>.tar.gz              源码分发
#   psyclaw-offline-<ver>.tar.gz      全离线整包:psyclaw + 依赖 wheel + 装机脚本
#                                     (拷到无网机器解压即装,国内不用碰 pypi)
#
# psyclaw 只有一个第三方依赖(prompt_toolkit),所以离线整包很小、很可靠。
set -eu

cd "$(dirname "$0")/.."
VER=$(python3 -c "import re,pathlib;print(re.search(r'__version__ = \"([^\"]+)\"',pathlib.Path('psyclaw/__init__.py').read_text()).group(1))")
say() { printf '\033[36m▸\033[0m %s\n' "$1"; }
ok()  { printf '\033[32m✓\033[0m %s\n' "$1"; }

command -v uv >/dev/null 2>&1 || { echo "需要 uv:https://docs.astral.sh/uv/" >&2; exit 1; }

# ── 1. wheel + sdist ──────────────────────────────────────────────────
say "构建 psyclaw $VER ..."
uv build --out-dir dist >/dev/null
WHL="psyclaw-$VER-py3-none-any.whl"
[ -f "dist/$WHL" ] || { echo "wheel 没生成:dist/$WHL" >&2; exit 1; }

# ── 2. 校验数据文件真的进包了(历史事故:skill/gates 判据全漏,装出来是残的)──
N=$(unzip -l "dist/$WHL" | grep -cE '\.(md|json|yaml)$' || true)
[ "$N" -ge 25 ] || { echo "✗ wheel 内数据文件只有 $N 个,package-data 配置坏了" >&2; exit 1; }
ok "wheel 就绪($N 个数据文件已打入)"

# ── 3. 全离线整包 ─────────────────────────────────────────────────────
say "打离线整包(含依赖 wheel)..."
STAGE="dist/psyclaw-offline-$VER"
rm -rf "$STAGE"                       # 只删本脚本自己上一轮的产物目录
mkdir -p "$STAGE/wheels"
cp "dist/$WHL" "$STAGE/wheels/"
# 把依赖也下成 wheel。注:uv 没有 `pip download` 子命令、其 venv 也不带 pip,
# 所以借 `uv run --with pip` 把 pip 拉进来用。国内默认走阿里云镜像。
INDEX="${PSYCLAW_PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"
uv run --python 3.12 --with pip python -m pip download -q --only-binary=:all: \
  -i "$INDEX" -d "$STAGE/wheels" "prompt_toolkit>=3.0" >/dev/null 2>&1 \
  || python3 -m pip download -q --only-binary=:all: -i "$INDEX" \
       -d "$STAGE/wheels" "prompt_toolkit>=3.0" >/dev/null 2>&1 \
  || { echo "✗ 依赖预下载失败,整包不是真离线——中止" >&2; rm -rf "$STAGE"; exit 1; }

# 真离线的硬校验:wheels/ 里必须同时有 psyclaw 和 prompt_toolkit,否则名不副实
[ -n "$(ls "$STAGE/wheels" | grep -i prompt_toolkit || true)" ] \
  || { echo "✗ wheels/ 里没有 prompt_toolkit,不是真离线包" >&2; rm -rf "$STAGE"; exit 1; }

cat > "$STAGE/install.sh" <<'EOS'
#!/bin/sh
# 离线装 psyclaw:不碰任何网络源,只用同目录 wheels/。
set -eu
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null \
  || { echo "需要 Python 3.11+(用 PYTHON=/path/to/python3.12 指定)" >&2; exit 1; }
"$PY" -m pip install --no-index --find-links wheels psyclaw
echo "✓ 装好了。跑:psyclaw   (若提示找不到命令:$PY -m psyclaw)"
EOS
chmod +x "$STAGE/install.sh"
printf 'psyclaw %s 离线整包\n\n解压后:sh install.sh\n无网环境可用;需本机已有 Python 3.11+。\n' \
  "$VER" > "$STAGE/README.txt"

tar -czf "dist/psyclaw-offline-$VER.tar.gz" -C dist "psyclaw-offline-$VER"
rm -rf "$STAGE"
ok "离线整包:dist/psyclaw-offline-$VER.tar.gz"

printf '\n'
ls -lh dist/ | grep -E "\.whl|\.tar\.gz"
