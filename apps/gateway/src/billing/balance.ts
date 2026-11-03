/**
 * 余额管理：查询、扣费、充值
 */

import type { Pool } from "pg";

export interface BalanceInfo {
  balance: number; // CNY 分
  hasActiveSubscription: boolean;
  subscription?: {
    planId: string;
    quotaUsed: number;
    quotaTotal: number;
    expireAt: Date;
  };
}

export interface BalanceService {
  getBalance(userId: string): Promise<BalanceInfo>;
  deduct(userId: string, amount: number, usageLogId: string): Promise<void>;
  credit(userId: string, amount: number, orderId: string, description: string): Promise<void>;
}

export class PgBalanceService implements BalanceService {
  constructor(private readonly db: Pool) {}

  async getBalance(userId: string): Promise<BalanceInfo> {
    // 查询用户余额
    const userResult = await this.db.query(
      "SELECT balance FROM users WHERE id = $1",
      [userId],
    );

    if (userResult.rows.length === 0) {
      throw new Error("User not found");
    }

    const balance = userResult.rows[0]!.balance as number;

    // 查询活跃订阅
    const subResult = await this.db.query(
      `SELECT plan_id, quota_used, quota_total, expire_at
       FROM subscriptions
       WHERE user_id = $1 AND status = 'active' AND expire_at > NOW()
       ORDER BY expire_at DESC
       LIMIT 1`,
      [userId],
    );

    if (subResult.rows.length === 0) {
      return { balance, hasActiveSubscription: false };
    }

    const sub = subResult.rows[0]!;
    return {
      balance,
      hasActiveSubscription: true,
      subscription: {
        planId: sub.plan_id as string,
        quotaUsed: sub.quota_used as number,
        quotaTotal: sub.quota_total as number,
        expireAt: sub.expire_at as Date,
      },
    };
  }

  async deduct(userId: string, amount: number, usageLogId: string): Promise<void> {
    const client = await this.db.connect();

    try {
      await client.query("BEGIN");

      // 查询当前余额
      const userResult = await client.query(
        "SELECT balance FROM users WHERE id = $1 FOR UPDATE",
        [userId],
      );

      if (userResult.rows.length === 0) {
        throw new Error("User not found");
      }

      const currentBalance = userResult.rows[0]!.balance as number;

      // 检查余额是否充足（订阅用户优先用额度，这里简化为只扣余额）
      if (currentBalance < amount) {
        throw new Error("Insufficient balance");
      }

      const newBalance = currentBalance - amount;

      // 更新余额
      await client.query(
        "UPDATE users SET balance = $1, updated_at = NOW() WHERE id = $2",
        [newBalance, userId],
      );

      // 记录交易
      await client.query(
        `INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, usage_log_id, description)
         VALUES ($1, 'deduction', $2, $3, $4, $5, $6)`,
        [userId, -amount, currentBalance, newBalance, usageLogId, "API usage deduction"],
      );

      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async credit(userId: string, amount: number, orderId: string, description: string): Promise<void> {
    const client = await this.db.connect();

    try {
      await client.query("BEGIN");

      // 查询当前余额
      const userResult = await client.query(
        "SELECT balance FROM users WHERE id = $1 FOR UPDATE",
        [userId],
      );

      if (userResult.rows.length === 0) {
        throw new Error("User not found");
      }

      const currentBalance = userResult.rows[0]!.balance as number;
      const newBalance = currentBalance + amount;

      // 更新余额
      await client.query(
        "UPDATE users SET balance = $1, updated_at = NOW() WHERE id = $2",
        [newBalance, userId],
      );

      // 记录交易
      await client.query(
        `INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, order_id, description)
         VALUES ($1, 'recharge', $2, $3, $4, $5, $6)`,
        [userId, amount, currentBalance, newBalance, orderId, description],
      );

      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }
}
