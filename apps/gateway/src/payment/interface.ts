/**
 * 支付接口抽象层，支持微信支付、支付宝、Stripe 等多种支付方式
 */

export type PaymentMethod = "wechat" | "alipay" | "stripe";

export interface TopUpOrderParams {
  userId: string;
  amount: number; // CNY 分
  paymentMethod: PaymentMethod;
}

export interface SubscriptionOrderParams {
  userId: string;
  planId: string; // "monthly" | "yearly"
  paymentMethod: PaymentMethod;
}

export interface PaymentOrderResult {
  orderId: string;
  qrCodeUrl?: string; // Native 支付二维码内容（weixin://wxpay/... or https://...）
  h5Url?: string; // H5 跳转链接（移动端浏览器）
  expireAt: Date;
}

export interface PaymentNotificationResult {
  orderId?: string;
  subscriptionId?: string;
  status: "success" | "failed" | "pending";
  transactionId?: string; // 第三方支付平台交易号
}

export interface PaymentOrderStatus {
  status: "unpaid" | "paid" | "expired" | "refunded";
  paidAt?: Date;
  transactionId?: string;
}

/**
 * 支付提供商接口
 * - 微信支付：Native（扫码）、H5（移动浏览器）
 * - 支付宝：当面付（扫码）、手机网站支付（H5）
 * - Stripe：stub（暂不实现）
 */
export interface PaymentProvider {
  name: PaymentMethod;

  /**
   * 创建充值订单
   * @returns 订单 ID 和支付凭证（二维码 URL 或 H5 跳转链接）
   */
  createTopUpOrder(params: TopUpOrderParams): Promise<PaymentOrderResult>;

  /**
   * 创建订阅订单（周期性扣款）
   * @returns 订阅 ID 和首次支付凭证
   */
  createSubscription(params: SubscriptionOrderParams): Promise<PaymentOrderResult>;

  /**
   * 处理异步支付通知（webhook 回调）
   * @param rawBody 原始请求体（用于签名验证）
   * @param signature 签名字符串（从请求头读取）
   * @returns 支付结果（成功/失败/待确认）
   */
  handleNotification(rawBody: string, signature: string): Promise<PaymentNotificationResult>;

  /**
   * 查询订单状态（用于主动轮询）
   * @param orderId 订单 ID
   * @returns 订单当前状态
   */
  queryOrderStatus(orderId: string): Promise<PaymentOrderStatus>;
}
