/**
 * PostgreSQL 数据库客户端
 */

import pg from "pg";
import type { GatewayConfig } from "../config.js";

const { Pool } = pg;

export async function createDbPool(config: GatewayConfig): Promise<pg.Pool> {
  const pool = new Pool({
    connectionString: config.database.url,
    max: 20,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 5000,
  });

  // 测试连接
  try {
    const client = await pool.connect();
    client.release();
  } catch (error) {
    throw new Error(`Failed to connect to database: ${error instanceof Error ? error.message : "Unknown error"}`);
  }

  return pool;
}
