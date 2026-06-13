"""本地 embedding — 语义召回的向量后端(分层降级,全本地无 API)。

- **主路径(选装)**:model2vec 静态嵌入 —— 纯 numpy 推理、无 torch,
  默认多语言模型 potion-multilingual-128M(首次使用自动下载到本地缓存,
  之后离线可用)。`psyclaw setup --groups embed` 安装;
  模型可用 PSYCLAW_EMBED_MODEL 或 config `embed_model` 换成任意
  model2vec 模型名/本地路径。
- **兜底(内置零依赖)**:HashEmbedder —— 中文 n-gram + 英文 token
  特征哈希向量,中英混排可用;质量低于真模型,但永远可用、完全确定。

每个后端自带 default_threshold:哈希向量的余弦天然偏低,
阈值随后端走,不假装同一把尺(语义门槛的"80%"只对真模型成立)。
"""

from __future__ import annotations

import hashlib
import math
import os
import re

_EN_TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{2,}")
_CJK_RE = re.compile(r"[一-鿿]+")


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# 兜底:特征哈希向量(stdlib,确定性)
# ---------------------------------------------------------------------------

class HashEmbedder:
    """字符 n-gram 特征哈希。dim 固定,md5 哈希定位+定符号,L2 归一。"""

    name = "hash-ngram-256"
    dim = 256
    default_threshold = 0.5

    @staticmethod
    def _features(text: str) -> list[str]:
        low = (text or "").lower()
        feats = _EN_TOKEN_RE.findall(low)
        for seq in _CJK_RE.findall(low):
            feats.extend(seq)                                   # unigram
            feats.extend(seq[i:i + 2] for i in range(len(seq) - 1))  # bigram
        return feats

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for f in self._features(text):
                h = int(hashlib.md5(f.encode("utf-8")).hexdigest(), 16)
                sign = 1.0 if (h >> 16) & 1 else -1.0
                vec[h % self.dim] += sign
            norm = math.sqrt(sum(x * x for x in vec))
            out.append([x / norm for x in vec] if norm else vec)
        return out


# ---------------------------------------------------------------------------
# 主路径:model2vec 静态嵌入(选装)
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "minishlab/potion-multilingual-128M"

# 推理只需这 3 个文件(整库 30 个文件里的 ONNX 副本等都不需要)
MODEL_FILES = ("model.safetensors", "tokenizer.json", "config.json")
_ENDPOINTS = ("https://hf-mirror.com", "https://huggingface.co")


def local_model_dir(model_name: str = DEFAULT_MODEL):
    from pathlib import Path
    return Path.home() / ".psyclaw" / "models" / model_name.split("/")[-1]


def _configured_model() -> str:
    name = os.environ.get("PSYCLAW_EMBED_MODEL")
    if name:
        return name
    try:
        from psyclaw import config as cfg
        name = cfg.load_config().get("embed_model")
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    # 本地权重目录齐全 → 直接用(不走 huggingface_hub,离线可用)
    loc = local_model_dir(DEFAULT_MODEL)
    if all((loc / f).exists() for f in MODEL_FILES):
        return str(loc)
    return DEFAULT_MODEL


# ---------------------------------------------------------------------------
# 权重直拉(stdlib urllib,Range 断点续传,镜像→官方双端点)
# 国内网络下 huggingface_hub 的元数据校验常失败,这里绕开它。
# ---------------------------------------------------------------------------

def _fetch(url: str, target, progress=None) -> None:
    import urllib.error
    import urllib.request
    part = target.parent / (target.name + ".part")
    pos = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "psyclaw"})
    if pos:
        req.add_header("Range", f"bytes={pos}-")
    try:
        ctx = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416 and pos:   # 本地字节 ≥ 远端大小 → 已下完,直接收尾
            part.replace(target)
            return
        raise
    with ctx as resp:
        if resp.status == 200 and pos:        # 服务器不认 Range → 从头下
            pos = 0
        total = pos + int(resp.headers.get("Content-Length") or 0)
        with part.open("ab" if pos else "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                pos += len(chunk)
                if progress and pos % (50 << 20) < (1 << 20):
                    progress(f"  {target.name}: {pos / 1e6:.0f}/{total / 1e6:.0f} MB")
    part.replace(target)


def _expected_shas(model_name: str) -> dict:
    """从 HF tree API 取各文件的官方 SHA256(LFS oid)。失败返回 {}(跳过校验)。"""
    import json
    import urllib.request
    for ep in _ENDPOINTS:
        try:
            url = f"{ep}/api/models/{model_name}/tree/main"
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "psyclaw"}),
                    timeout=30) as resp:
                tree = json.loads(resp.read())
            return {e["path"]: e["lfs"]["oid"] for e in tree if e.get("lfs")}
        except Exception:  # noqa: BLE001
            continue
    return {}


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _head_size(url: str) -> int:
    import urllib.request
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "psyclaw"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return int(resp.headers.get("Content-Length") or 0)


def _fetch_parallel(url: str, target, size: int, workers: int = 8,
                    progress=None) -> None:
    """多连接分段下载:绕过 per-connection 限速。

    每段独立 .segN 文件(各自断点续传),全部到齐后流式拼接。
    任一段失败自动重试 3 次;仍失败则整体抛错(已下段保留,重跑续传)。
    """
    import shutil
    import threading
    import urllib.request

    seg_size = -(-size // workers)
    ranges = [(i, i * seg_size, min((i + 1) * seg_size, size) - 1)
              for i in range(workers)]
    errors: list[Exception] = []

    window = 12 << 20      # 每连接只取 12MB 就重连:限速常按连接计,
    #                        新连接前若干 MB 是全速突发,重连反复吃突发带宽

    def work(idx: int, start: int, end: int) -> None:
        seg = target.parent / f"{target.name}.seg{idx}"
        want = end - start + 1
        fails = 0
        while fails < 5:
            pos = seg.stat().st_size if seg.exists() else 0
            if pos >= want:
                return
            win_end = min(start + pos + window - 1, end)
            req = urllib.request.Request(url, headers={
                "User-Agent": "psyclaw",
                "Range": f"bytes={start + pos}-{win_end}"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp, \
                        seg.open("ab") as f:
                    while True:
                        chunk = resp.read(1 << 18)
                        if not chunk:
                            break
                        f.write(chunk)
                fails = 0
            except Exception as exc:  # noqa: BLE001
                fails += 1
                last = exc
        errors.append(last)

    threads = [threading.Thread(target=work, args=r, daemon=True)
               for r in ranges]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise RuntimeError(f"{len(errors)}/{workers} 段下载失败") from errors[0]
    segs = [target.parent / f"{target.name}.seg{i}" for i in range(workers)]
    if any(s.stat().st_size != (r[2] - r[1] + 1) for s, r in zip(segs, ranges)):
        raise RuntimeError("分段大小不符,保留已下段供重试")
    part = target.parent / (target.name + ".part")
    with part.open("wb") as out:
        for s in segs:
            with s.open("rb") as f:
                shutil.copyfileobj(f, out, 1 << 22)
    part.replace(target)
    for s in segs:
        s.unlink()
    if progress:
        progress(f"  {target.name}: {size / 1e6:.0f} MB 完成({workers} 连接)")


def download_default_model(model_name: str = DEFAULT_MODEL,
                           progress=print) -> "object":
    """直拉推理所需的 3 个文件到 ~/.psyclaw/models/<模型名>。

    已存在且校验通过的文件跳过;中断后重跑自动断点续传(.part 文件);
    LFS 大文件下载后做 SHA256 校验(官方 oid),不符**删除并报错**,
    绝不把坏权重转正。返回本地模型目录。
    """
    dest = local_model_dir(model_name)
    dest.mkdir(parents=True, exist_ok=True)
    shas = _expected_shas(model_name)

    def _verified(path, fname) -> bool:
        want = shas.get(fname)
        return (want is None) or _sha256(path) == want

    for fname in MODEL_FILES:
        target = dest / fname
        if target.exists() and target.stat().st_size > 0:
            if _verified(target, fname):
                if progress:
                    progress(f"  {fname}: 已存在且校验通过,跳过")
                continue
            target.unlink()                      # 坏文件重下
            if progress:
                progress(f"  {fname}: 校验失败,删除重下")
        last_err: Exception | None = None
        for ep in _ENDPOINTS:
            url = f"{ep}/{model_name}/resolve/main/{fname}"
            try:
                if progress:
                    progress(f"  下载 {fname} ← {ep}")
                size = _head_size(url)
                if size > (50 << 20):           # 大文件走多连接分段
                    _fetch_parallel(url, target, size, progress=progress)
                else:
                    _fetch(url, target, progress)
                if not _verified(target, fname):
                    target.unlink()
                    raise RuntimeError(f"{fname} SHA256 校验失败(已删除)")
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        if last_err is not None:
            raise RuntimeError(f"下载 {fname} 失败(双端点均不可用)") from last_err
    if progress:
        progress(f"✓ 模型就绪(已校验):{dest}")
    return dest


class Model2VecEmbedder:
    """model2vec 静态模型(无 torch);首次加载下载权重,之后离线。"""

    default_threshold = 0.8

    def __init__(self, model_name: str | None = None) -> None:
        from model2vec import StaticModel
        self.model_name = model_name or _configured_model()
        self._model = StaticModel.from_pretrained(self.model_name)
        self.dim = int(self._model.dim)
        self.name = f"model2vec:{self.model_name}"

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, show_progress_bar=False)
        out = []
        for v in vecs:
            v = [float(x) for x in v]
            norm = math.sqrt(sum(x * x for x in v))
            out.append([x / norm for x in v] if norm else v)
        return out


# ---------------------------------------------------------------------------
# 后端选择(装了真模型自动升级,没装透明降级)
# ---------------------------------------------------------------------------

_CACHED = None


def get_embedder(prefer: str | None = None):
    """prefer='hash' 强制兜底;默认 model2vec 可用则用,否则哈希。

    环境变量 PSYCLAW_EMBED_BACKEND=hash 可全局强制兜底
    (离线 CI/不想加载模型时用)。
    """
    global _CACHED
    if prefer == "hash" or os.environ.get("PSYCLAW_EMBED_BACKEND") == "hash":
        return HashEmbedder()
    if _CACHED is not None:
        return _CACHED
    try:
        _CACHED = Model2VecEmbedder()
    except Exception:  # noqa: BLE001  # 未安装/下载失败 → 零依赖兜底
        _CACHED = HashEmbedder()
    return _CACHED


if __name__ == "__main__":  # python -m psyclaw.embed → 直拉默认模型权重
    download_default_model()
