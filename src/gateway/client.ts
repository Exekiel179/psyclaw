/**
 * PsyClaw 官方网关客户端：余额查询、登录状态检查
 */

export interface GatewayBalanceResponse {
  balance: number; // CNY 分
  balanceCny: string; // 格式化为 "¥123.45"
  subscription?: {
    planId: string;
    status: "active" | "expired";
    expireAt: string;
    quota?: {
      used: number;
      total: number;
      unit: "tokens";
    };
  };
}

export interface GatewayClient {
  /** 查询余额和订阅状态（需要有效 token） */
  getBalance(token: string): Promise<GatewayBalanceResponse>;

  /** 验证 token 是否有效 */
  verifyToken(token: string): Promise<boolean>;
}

function formatCny(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`;
}

export class HttpGatewayClient implements GatewayClient {
  constructor(private readonly baseUrl: string) {}

  async getBalance(token: string): Promise<GatewayBalanceResponse> {
    const response = await fetch(`${this.baseUrl}/account/balance`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error("Token 无效或已过期，请重新登录");
      }
      throw new Error(`查询余额失败: ${response.status} ${response.statusText}`);
    }

    const data = await response.json() as {
      balance: number;
      subscription?: {
        plan_id: string;
        status: string;
        expire_at: string;
        quota?: { used: number; total: number; unit: string };
      };
    };

    return {
      balance: data.balance,
      balanceCny: formatCny(data.balance),
      subscription: data.subscription
        ? {
          planId: data.subscription.plan_id,
          status: data.subscription.status as "active" | "expired",
          expireAt: data.subscription.expire_at,
          quota: data.subscription.quota
            ? {
              used: data.subscription.quota.used,
              total: data.subscription.quota.total,
              unit: "tokens" as const,
            }
            : undefined,
        }
        : undefined,
    };
  }

  async verifyToken(token: string): Promise<boolean> {
    try {
      await this.getBalance(token);
      return true;
    } catch {
      return false;
    }
  }
}

/** 创建网关客户端实例，baseUrl 可从环境变量或配置覆盖（支持国内节点切换） */
export function createGatewayClient(baseUrl?: string): GatewayClient {
  const url = baseUrl ?? process.env.PSYCLAW_GATEWAY_URL ?? "https://api.psyclaw.ai/v1";
  return new HttpGatewayClient(url);
}
