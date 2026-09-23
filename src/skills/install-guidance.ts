/**
 * Shared install instructions for model-driven recommended Skill installs.
 */

export interface RecommendedSkillInstallGuidanceOptions {
  name: string;
  id: string;
  sourceRef: string;
  target: string;
  scopeLabel: string;
  installHint?: string;
  collection?: boolean;
}

/** Skills that must never pull demo figure trees during install. */
const SKIP_DEMO_FIGURE_SKILLS = new Set([
  "academic-figure-skill",
]);

/**
 * Build the install task body used by `/skill` and Panel.
 * Keep checks minimal: land files, confirm SKILL.md, stop.
 */
export function buildRecommendedSkillInstallTask(options: RecommendedSkillInstallGuidanceOptions): string {
  if (SKIP_DEMO_FIGURE_SKILLS.has(options.id)) {
    return buildAcademicFigureInstallTask(options);
  }
  return buildDefaultInstallTask(options);
}

/** Short path for Academic Figure Skill — the Windows install that burned minutes on demos/QA. */
function buildAcademicFigureInstallTask(options: RecommendedSkillInstallGuidanceOptions): string {
  return [
    `安装 Academic Figure Skill（${options.id}）。`,
    `来源：${options.sourceRef}`,
    `目标（唯一）：${options.target}（${options.scopeLabel}）`,
    "",
    "只做这四步，做完即停：",
    "1) 用 codeload 下源码包（`https://codeload.github.com/TingxiYu/academic-figure-skill/tar.gz/main`）；github.com 不通就走 PSYCLAW 镜像。不要 git clone，不要反复探测。",
    "2) 只拷贝：SKILL.md、references/、scripts/、LICENSE*。整棵 `assets/` 一律跳过（示例图约 80MB+，安装不需要）。",
    "3) 临时目录用 Windows `%TEMP%` / PowerShell `$env:TEMP` 绝对路径；禁止 Bash `/tmp` 交给 Windows Python。拷完断言目标文件数 > 0。",
    "4) 完成判据：目标下有可读 SKILL.md。不要跑 check_dimensions.py / check_*.py / e2e / eval，不要写 install-notes，不要二次自检。",
    "",
    "完成后提醒 /reload。已默认启用。",
  ].join("\n");
}

function buildDefaultInstallTask(options: RecommendedSkillInstallGuidanceOptions): string {
  const hint = options.installHint?.trim();
  return [
    `安装推荐 Skill：${options.name} (${options.id})。`,
    `来源：${options.sourceRef}`,
    ...(hint ? [`入口提示：${hint}`] : []),
    `目标（唯一）：${options.target}（${options.scopeLabel}）`,
    "用户已授权。直接下载并落盘；不要再要权限；不要动 data/raw、.git。",
    "优先 codeload 源码包；不通再镜像。Windows 临时目录用 %TEMP% 绝对路径，禁止 /tmp 混用；拷完文件数必须 > 0。",
    "跳过演示大图与 >1MiB 媒体。安装阶段不要跑上游 check_*/e2e/eval。",
    options.collection
      ? "套件：子目录含 SKILL.md 即可；保留相对结构；无 .git/符号链接/凭据文件。"
      : "叶子：目标直接含有效 SKILL.md；无 .git/符号链接/凭据文件。",
    "只装本推荐项相关子树。完成后 /reload（已默认启用）。",
  ].join("\n");
}

const DEMO_DIR_MARKERS = [
  "assets/figures",
  "assets/figures4papers",
  "assets/gallery",
  "gallery",
  "demos",
] as const;

const LARGE_MEDIA_RE = /\.(png|jpe?g|gif|webp|bmp|tiff?|mp4|mov|webm)$/i;
const LARGE_MEDIA_BYTES = 1 * 1024 * 1024;

/**
 * Whether a path under a Skill tree is a skippable demo/media asset.
 * `relativePath` uses `/` separators from the skill root.
 */
export function shouldSkipSkillInstallAsset(relativePath: string, fileName: string, sizeBytes: number): boolean {
  const norm = relativePath.replaceAll("\\", "/").replace(/^\/+/, "").toLocaleLowerCase();
  if (DEMO_DIR_MARKERS.some((marker) => norm === marker || norm.startsWith(`${marker}/`))) return true;
  if (LARGE_MEDIA_RE.test(fileName) && sizeBytes > LARGE_MEDIA_BYTES) return true;
  return false;
}
