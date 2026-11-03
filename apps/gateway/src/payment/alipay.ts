/**
 * 支付宝支付实现（当面付 + 异步通知）
 * 官方文档：https://opendocs.alipay.com/open/270/105898
 */

import { createSign, createVerify } from "node:crypto";
import type {
  PaymentProvider,
  TopUpOrderParams,
  SubscriptionOrderParams,
  PaymentOrderResult,
  PaymentNotificationResult,
  PaymentOrderStatus,
} from "./interface.js";

export interface AlipayConfig {
  appId: string; // 应用 ID
  privateKey: string; // 商户私钥（RSA2）
  publicKey: string; // 支付宝公钥
  notifyUrl: string; // 异步通知 URL
  gateway: string; // 网关地址（国内/沙箱）
}

/** 生成订单号 */
function generateOrderId(): string {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 8);
  return `psy_${timestamp}_${random}`;
}

/**
 * 支付宝签名（RSA2 = SHA256withRSA）
 * 待签名字符串：将请求参数按 key 排序后拼接（key=value&key=value...）
 */
function signParams(params: Record<string, string | number>, privateKey: string): string {
  const sorted = Object.keys(params)
    .filter((key) => key !== "sign" && params[key] !== undefined && params[key] !== "")
    .sort();

  const query = sorted.map((key) => `${key}=${params[key]}`).join("&");
  const sign = createSign("RSA-SHA256");
  sign.update(query, "utf8");
  return sign.sign(privateKey, "base64");
}

/**
 * 验证支付宝回调签名
 */
function verifySignature(params: Record<string, string>, publicKey: string): boolean {
  const signature = params.sign;
  if (!signature) return false;

  const sorted = Object.keys(params)
    .filter((key) => key !== "sign" && key !== "sign_type" && params[key] !== undefined)
    .sort();

  const query = sorted.map((key) => `${key}=${params[key]}`).join("&");
  const verify = createVerify("RSA-SHA256");
  verify.update(query, "utf8");
  return verify.verify(publicKey, signature, "base64");
}

export class AlipayProvider implements PaymentProvider {
  name = "alipay" as const;

  constructor(private readonly config: AlipayConfig) {}

  async createTopUpOrder(params: TopUpOrderParams): Promise<PaymentOrderResult> {
    const orderId = generateOrderId();
    const expireAt = new Date(Date.now() + 15 * 60 * 1000); // 15 分钟有效

    // 当面付（扫码）参数
    const bizContent = {
      out_trade_no: orderId,
      total_amount: (params.amount / 100).toFixed(2), // 转换为元
      subject: `PsyClaw 充值 ¥${(params.amount / 100).toFixed(2)}`,
      timeout_express: "15m",
    };

    const requestParams: Record<string, string> = {
      app_id: this.config.appId,
      method: "alipay.trade.precreate", // 当面付（扫码）
      format: "JSON",
      charset: "utf-8",
      sign_type: "RSA2",
      timestamp: new Date().toISOString().replace("T", " ").slice(0, 19),
      version: "1.0",
      notify_url: this.config.notifyUrl,
      biz_content: JSON.stringify(bizContent),
    };

    // 签名
    const signature = signParams(requestParams, this.config.privateKey);
    requestParams.sign = signature;

    // 构造请求 URL
    const query = new URLSearchParams(requestParams as never).toString();
    const url = `${this.config.gateway}?${query}`;

    // 调用支付宝 API
    const response = await fetch(url, { method: "POST" });

    if (!response.ok) {
      throw new Error(`支付宝当面付下单失败: ${response.status}`);
    }

    const data = await response.json() as {
      alipay_trade_precreate_response: {
        code: string;
        msg: string;
        qr_code?: string;
      };
    };

    const result = data.alipay_trade_precreate_response;
    if (result.code !== "10000") {
      throw new Error(`支付宝下单失败: ${result.msg}`);
    }

    return {
      orderId,
      qrCodeUrl: result.qr_code, // 二维码内容（URL 或 Base64）
      expireAt,
    };
  }

  async createSubscription(_params: SubscriptionOrderParams): Promise<PaymentOrderResult> {
    // 订阅功能需要使用周期扣款（alipay.trade.pay.agreement）
    throw new Error("支付宝订阅功能尚未实现");
  }

  async handleNotification(rawBody: string, _signature: string): Promise<PaymentNotificationResult> {
    // 解析表单参数（支付宝回调是 application/x-www-form-urlencoded）
    const params = Object.fromEntries(new URLSearchParams(rawBody));

    // 验证签名
    const isValid = verifySignature(params, this.config.publicKey);
    if (!isValid) {
      throw new Error("支付宝回调签名验证失败");
    }

    // 检查通知类型和状态
    const { trade_status, out_trade_no, trade_no } = params;

    if (trade_status === "TRADE_SUCCESS" || trade_status === "TRADE_FINISHED") {
      return {
        orderId: out_trade_no,
        status: "success",
        transactionId: trade_no,
      };
    }

    if (trade_status === "TRADE_CLOSED") {
      return { orderId: out_trade_no, status: "failed" };
    }

    return { status: "pending" };
  }

  async queryOrderStatus(orderId: string): Promise<PaymentOrderStatus> {
    const requestParams: Record<string, string> = {
      app_id: this.config.appId,
      method: "alipay.trade.query",
      format: "JSON",
      charset: "utf-8",
      sign_type: "RSA2",
      timestamp: new Date().toISOString().replace("T", " ").slice(0, 19),
      version: "1.0",
      biz_content: JSON.stringify({ out_trade_no: orderId }),
    };

    const signature = signParams(requestParams, this.config.privateKey);
    requestParams.sign = signature;

    const query = new URLSearchParams(requestParams as never).toString();
    const url = `${this.config.gateway}?${query}`;

    const response = await fetch(url, { method: "POST" });

    if (!response.ok) {
      throw new Error(`支付宝查询订单失败: ${response.status}`);
    }

    const data = await response.json() as {
      alipay_trade_query_response: {
        code: string;
        msg: string;
        trade_status?: string;
        send_pay_date?: string;
        trade_no?: string;
      };
    };

    const result = data.alipay_trade_query_response;
    if (result.code !== "10000") {
      throw new Error(`支付宝查询失败: ${result.msg}`);
    }

    let status: PaymentOrderStatus["status"] = "unpaid";
    if (result.trade_status === "TRADE_SUCCESS" || result.trade_status === "TRADE_FINISHED") {
      status = "paid";
    } else if (result.trade_status === "TRADE_CLOSED") {
      status = "expired";
    }

    return {
      status,
      paidAt: result.send_pay_date ? new Date(result.send_pay_date) : undefined,
      transactionId: result.trade_no,
    };
  }
}
