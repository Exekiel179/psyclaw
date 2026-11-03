/**
 * 微信支付实现（Native 扫码 + 异步通知）
 * 官方文档：https://pay.weixin.qq.com/wiki/doc/apiv3/index.shtml
 */

import { readFile } from "node:fs/promises";
import { createSign, createVerify, randomBytes } from "node:crypto";
import type {
  PaymentProvider,
  TopUpOrderParams,
  SubscriptionOrderParams,
  PaymentOrderResult,
  PaymentNotificationResult,
  PaymentOrderStatus,
} from "./interface.js";

export interface WeChatPayConfig {
  mchId: string; // 商户号
  apiKey: string; // API v3 密钥（用于解密通知）
  certSerial: string; // 商户证书序列号
  privateKeyPath: string; // 商户私钥路径
  notifyUrl: string; // 异步通知 URL
}

/** 生成订单号（32 位以内，仅字母数字下划线） */
function generateOrderId(): string {
  const timestamp = Date.now().toString(36);
  const random = randomBytes(6).toString("hex");
  return `psy_${timestamp}_${random}`;
}

/** 生成 32 位随机字符串（API 要求） */
function generateNonceStr(): string {
  return randomBytes(16).toString("hex");
}

/**
 * 微信支付 API v3 签名（SHA256withRSA）
 * 签名内容格式：
 *   HTTP方法\n
 *   URL路径\n
 *   请求时间戳\n
 *   随机字符串\n
 *   请求体\n
 */
async function signRequest(
  method: string,
  url: string,
  timestamp: number,
  nonce: string,
  body: string,
  privateKeyPem: string,
): Promise<string> {
  const message = `${method}\n${url}\n${timestamp}\n${nonce}\n${body}\n`;
  const sign = createSign("RSA-SHA256");
  sign.update(message, "utf8");
  return sign.sign(privateKeyPem, "base64");
}

/**
 * 验证微信回调签名
 * 签名内容格式：
 *   应答时间戳\n
 *   应答随机串\n
 *   应答报文主体\n
 */
function verifyNotificationSignature(
  timestamp: string,
  nonce: string,
  body: string,
  signature: string,
  platformPublicKey: string,
): boolean {
  const message = `${timestamp}\n${nonce}\n${body}\n`;
  const verify = createVerify("RSA-SHA256");
  verify.update(message, "utf8");
  return verify.verify(platformPublicKey, signature, "base64");
}

/**
 * AES-256-GCM 解密（微信通知内容加密）
 * 使用 API v3 密钥解密
 */
function decryptAesGcm(
  ciphertext: string,
  associatedData: string,
  nonce: string,
  apiKey: string,
): string {
  const { createDecipheriv } = require("node:crypto") as typeof import("node:crypto");
  const decipher = createDecipheriv("aes-256-gcm", Buffer.from(apiKey, "utf8"), Buffer.from(nonce, "utf8"));
  decipher.setAAD(Buffer.from(associatedData, "utf8"));
  decipher.setAuthTag(Buffer.from(ciphertext.slice(-32), "base64"));
  const encrypted = ciphertext.slice(0, -32);
  let decrypted = decipher.update(encrypted, "base64", "utf8");
  decrypted += decipher.final("utf8");
  return decrypted;
}

export class WeChatPayProvider implements PaymentProvider {
  name = "wechat" as const;
  private privateKey?: string;

  constructor(private readonly config: WeChatPayConfig) {}

  private async loadPrivateKey(): Promise<string> {
    if (!this.privateKey) {
      this.privateKey = await readFile(this.config.privateKeyPath, "utf8");
    }
    return this.privateKey;
  }

  async createTopUpOrder(params: TopUpOrderParams): Promise<PaymentOrderResult> {
    const orderId = generateOrderId();
    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = generateNonceStr();
    const expireAt = new Date(Date.now() + 15 * 60 * 1000); // 15 分钟有效期

    const requestBody = JSON.stringify({
      mchid: this.config.mchId,
      out_trade_no: orderId,
      appid: "wx_placeholder", // 需要替换为实际 AppID
      description: `PsyClaw 充值 ¥${(params.amount / 100).toFixed(2)}`,
      notify_url: this.config.notifyUrl,
      amount: {
        total: params.amount,
        currency: "CNY",
      },
      time_expire: expireAt.toISOString(),
    });

    const url = "/v3/pay/transactions/native";
    const privateKey = await this.loadPrivateKey();
    const signature = await signRequest("POST", url, timestamp, nonce, requestBody, privateKey);

    // 构造 Authorization 头
    const authorization = `WECHATPAY2-SHA256-RSA2048 mchid="${this.config.mchId}",nonce_str="${nonce}",signature="${signature}",timestamp="${timestamp}",serial_no="${this.config.certSerial}"`;

    // 调用微信支付 API（此处为示意，实际需要 https 客户端）
    const response = await fetch(`https://api.mch.weixin.qq.com${url}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: authorization,
      },
      body: requestBody,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`微信支付 Native 下单失败: ${response.status} ${errorText}`);
    }

    const data = await response.json() as { code_url: string };

    return {
      orderId,
      qrCodeUrl: data.code_url, // weixin://wxpay/bizpayurl?pr=xxx
      expireAt,
    };
  }

  async createSubscription(_params: SubscriptionOrderParams): Promise<PaymentOrderResult> {
    // 订阅功能需要使用委托代扣（需单独签约）
    throw new Error("微信支付订阅功能尚未实现");
  }

  async handleNotification(rawBody: string, signature: string): Promise<PaymentNotificationResult> {
    // 从请求头解析签名相关字段（实际从 HTTP 头读取）
    // Wechatpay-Timestamp, Wechatpay-Nonce, Wechatpay-Signature, Wechatpay-Serial
    const timestampMatch = /timestamp="(\d+)"/.exec(signature);
    const nonceMatch = /nonce_str="([^"]+)"/.exec(signature);
    const signatureMatch = /signature="([^"]+)"/.exec(signature);

    if (!timestampMatch || !nonceMatch || !signatureMatch) {
      throw new Error("微信回调签名格式错误");
    }

    const timestamp = timestampMatch[1]!;
    const nonce = nonceMatch[1]!;
    const sig = signatureMatch[1]!;

    // 验证签名（需要微信平台公钥，此处简化为占位符）
    const platformPublicKey = "placeholder-wechat-platform-public-key";
    const isValid = verifyNotificationSignature(timestamp, nonce, rawBody, sig, platformPublicKey);

    if (!isValid) {
      throw new Error("微信回调签名验证失败");
    }

    // 解析通知内容
    const data = JSON.parse(rawBody) as {
      event_type: string;
      resource: {
        ciphertext: string;
        associated_data: string;
        nonce: string;
      };
    };

    if (data.event_type !== "TRANSACTION.SUCCESS") {
      return { status: "pending" };
    }

    // 解密通知内容
    const decrypted = decryptAesGcm(
      data.resource.ciphertext,
      data.resource.associated_data,
      data.resource.nonce,
      this.config.apiKey,
    );

    const payment = JSON.parse(decrypted) as {
      out_trade_no: string;
      transaction_id: string;
      trade_state: string;
    };

    if (payment.trade_state === "SUCCESS") {
      return {
        orderId: payment.out_trade_no,
        status: "success",
        transactionId: payment.transaction_id,
      };
    }

    return { status: "pending" };
  }

  async queryOrderStatus(orderId: string): Promise<PaymentOrderStatus> {
    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = generateNonceStr();
    const url = `/v3/pay/transactions/out-trade-no/${orderId}?mchid=${this.config.mchId}`;
    const privateKey = await this.loadPrivateKey();
    const signature = await signRequest("GET", url, timestamp, nonce, "", privateKey);

    const authorization = `WECHATPAY2-SHA256-RSA2048 mchid="${this.config.mchId}",nonce_str="${nonce}",signature="${signature}",timestamp="${timestamp}",serial_no="${this.config.certSerial}"`;

    const response = await fetch(`https://api.mch.weixin.qq.com${url}`, {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: authorization,
      },
    });

    if (!response.ok) {
      throw new Error(`微信支付查询订单失败: ${response.status}`);
    }

    const data = await response.json() as {
      trade_state: string;
      success_time?: string;
      transaction_id?: string;
    };

    let status: PaymentOrderStatus["status"] = "unpaid";
    if (data.trade_state === "SUCCESS") status = "paid";
    else if (data.trade_state === "CLOSED" || data.trade_state === "REVOKED") status = "expired";
    else if (data.trade_state === "REFUND") status = "refunded";

    return {
      status,
      paidAt: data.success_time ? new Date(data.success_time) : undefined,
      transactionId: data.transaction_id,
    };
  }
}
