/**
 * One non-blocking look-again after a script passes the label checks.
 * Fitted methods need a constant for which rows they use. @pseudo cannot rest
 * on what this particular data set happens to contain.
 */

const FITTED: { name: string; pattern: RegExp }[] = [
  { name: "PCA", pattern: /\bPCA\s*\(|\bpca\b|principal[ _]component/i },
  { name: "factor analysis", pattern: /FactorAnalys[ei]s|FactorAnalyzer|\befa\b|\bcfa\b|factor[ _]score|factor[ _]analysis/i },
  { name: "SEM / latent-variable model", pattern: /\bsemopy\b|\blavaan\b|\bsem_|_sem\b|\bsem\b|latent[ _]variable|latent_sem|sem_latent/i },
];

const FIT_NAME = /FIT|SAMPLE|ROWS|SUBSET|ESTIMATION/i;
const METHOD_NAME = /PCA|FACTOR|EFA|CFA|SEM|LATENT|COMPONENT|SCOR/i;
const DATA_BOUND = /in (these|this|the) data|in this sample|every (row|one of|participant|respondent|completer)|all \d+|no (missing|participant|respondent|row)|zero missing|none of the \d*|has no missing|have no missing|\b\d+ (rows|participants|respondents|completers)\b|changes nothing|removes? no one|nobody|\bthe (one|two|three|four|five|\d+) (respondents?|participants?|rows?)\b|each duplicated|这份数据|没有缺失|没有人被/i;
const CONST = /^([A-Z][A-Z0-9_]*)\s*(?:=|<-)\s*.*?#\s*(.*)$/;

function labeledLines(source: string): { name: string; label: string }[] {
  const lines = source.split(/\r?\n/);
  const out: { name: string; label: string }[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (line.startsWith(" ") || line.startsWith("\t")) continue;
    const match = CONST.exec(line.trim());
    if (!match) continue;
    let label = match[2] ?? "";
    const next = (lines[index + 1] ?? "").trim();
    if (!label.includes("@") && next.startsWith("# @")) label = next.slice(1).trim();
    out.push({ name: match[1] ?? "", label });
  }
  return out;
}

export function reflectHints(source: string): string[] {
  const hints: string[] = [];
  const constants = labeledLines(source);
  const used = FITTED.filter((method) => method.pattern.test(source)).map((method) => method.name);
  const hasFitConstant = constants.some((constant) => FIT_NAME.test(constant.name) && METHOD_NAME.test(constant.name))
    || /fit(ted)? on|estimation sample|fit sample/i.test(constants.map((constant) => constant.label).join(" "));
  if (used.length > 0 && !hasFitConstant) {
    hints.push(`- The script uses ${used.join(", ")}, which is estimated from data, but no constant states which rows it is fitted on or its settings.`);
  }
  const bound = constants.filter((constant) => constant.label.includes("@pseudo") && DATA_BOUND.test(constant.label)).map((constant) => constant.name);
  if (bound.length > 0) {
    hints.push(`- @pseudo means the options agree for any data. The reasons for ${bound.join(", ")} rest on what this data set happens to contain.`);
  }
  return hints;
}
