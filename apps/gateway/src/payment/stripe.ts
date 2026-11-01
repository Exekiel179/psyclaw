/**
 * Stripe 支付实现（stub，次要选项）
 */

import type {
  PaymentProvider,
  TopUpOrderParams,
  SubscriptionOrderParams,
  PaymentOrderResult,
  PaymentNotificationResult,
  PaymentOrderStatus,
} from "./interface.js";

export interface StripeConfig {
  secretKey: string;
  webhookSecret: string;
}

export class StripePaymentProvider implements PaymentProvider {
  name = "stripe" as const;

  constructor(private readonly _config: StripeConfig) {}

  async createTopUpOrder(_params: TopUpOrderParams): Promise<PaymentOrderResult> {
    throw new Error("Stripe 充值功能尚未实现（次要优先级）");
  }

  async createSubscription(_params: SubscriptionOrderParams): Promise<PaymentOrderResult> {
    throw new Error("Stripe 订阅功能尚未实现（次要优先级）");
  }

  async handleNotification(_rawBody: string, _signature: string): Promise<PaymentNotificationResult> {
    throw new Error("Stripe webhook 处理尚未实现（次要优先级）");
  }

  async queryOrderStatus(_orderId: string): Promise<PaymentOrderStatus> {
    throw new Error("Stripe 订单查询尚未实现（次要优先级）");
  }
}
