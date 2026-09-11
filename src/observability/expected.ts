/**
 * User-setup and usage outcomes that should stay in the product UI and
 * must not be reported as production exceptions.
 */

export class ExpectedUserError extends Error {
  readonly expected = true as const;

  constructor(message: string) {
    super(message);
    this.name = "ExpectedUserError";
  }
}

const MISSING_API_KEY_MESSAGE = /^未找到 [A-Z][A-Z0-9_]{0,127}；请输入 API Key 后再继续/;
const MISSING_PROVIDER_CREDENTIAL_MESSAGE = /^未找到 .+ 的可用凭据；请重新运行 \/provider/;

export function isExpectedUserErrorMessage(message: string): boolean {
  const text = message.trim();
  if (!text) return false;
  if (text.startsWith("Usage:")) return true;
  if (text.startsWith("无法识别选项 ")) return true;
  if (MISSING_API_KEY_MESSAGE.test(text)) return true;
  if (MISSING_PROVIDER_CREDENTIAL_MESSAGE.test(text)) return true;
  return false;
}

export function isExpectedUserError(error: unknown): boolean {
  if (error instanceof ExpectedUserError) return true;
  if (error && typeof error === "object" && "expected" in error && (error as { expected?: unknown }).expected === true) {
    return true;
  }
  const message = error instanceof Error ? error.message : String(error);
  return isExpectedUserErrorMessage(message);
}
