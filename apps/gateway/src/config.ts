/** 网关环境变量配置 */

export interface GatewayConfig {
  port: number;
  nodeEnv: string;
  database: {
    url: string;
  };
  redis: {
    url: string;
  };
  upstream: {
    deepseek: {
      apiKey: string;
      baseUrl: string;
    };
    anthropic: {
      apiKey: string;
      baseUrl: string;
    };
  };
  payment: {
    wechat: {
      mchId: string;
      apiKey: string;
      certSerial: string;
      privateKeyPath: string;
      notifyUrl: string;
    };
    alipay: {
      appId: string;
      privateKey: string;
      publicKey: string;
      notifyUrl: string;
      gateway: string;
    };
    stripe?: {
      secretKey: string;
      webhookSecret: string;
    };
  };
  jwt: {
    secret: string;
    expiresIn: string;
  };
  gateway: {
    baseUrl: string;
    chinaNode?: string;
  };
  logLevel: string;
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function optionalEnv(name: string): string | undefined {
  return process.env[name] || undefined;
}

export function loadConfig(): GatewayConfig {
  return {
    port: Number(process.env.PORT || "3000"),
    nodeEnv: process.env.NODE_ENV || "development",
    database: {
      url: requireEnv("DATABASE_URL"),
    },
    redis: {
      url: requireEnv("REDIS_URL"),
    },
    upstream: {
      deepseek: {
        apiKey: requireEnv("UPSTREAM_DEEPSEEK_API_KEY"),
        baseUrl: process.env.UPSTREAM_DEEPSEEK_BASE_URL || "https://api.deepseek.com",
      },
      anthropic: {
        apiKey: requireEnv("UPSTREAM_ANTHROPIC_API_KEY"),
        baseUrl: process.env.UPSTREAM_ANTHROPIC_BASE_URL || "https://api.anthropic.com",
      },
    },
    payment: {
      wechat: {
        mchId: requireEnv("WECHAT_PAY_MCH_ID"),
        apiKey: requireEnv("WECHAT_PAY_API_KEY"),
        certSerial: requireEnv("WECHAT_PAY_CERT_SERIAL"),
        privateKeyPath: requireEnv("WECHAT_PAY_PRIVATE_KEY_PATH"),
        notifyUrl: requireEnv("WECHAT_PAY_NOTIFY_URL"),
      },
      alipay: {
        appId: requireEnv("ALIPAY_APP_ID"),
        privateKey: requireEnv("ALIPAY_PRIVATE_KEY"),
        publicKey: requireEnv("ALIPAY_PUBLIC_KEY"),
        notifyUrl: requireEnv("ALIPAY_NOTIFY_URL"),
        gateway: process.env.ALIPAY_GATEWAY || "https://openapi.alipay.com/gateway.do",
      },
      stripe: optionalEnv("STRIPE_SECRET_KEY")
        ? {
          secretKey: requireEnv("STRIPE_SECRET_KEY"),
          webhookSecret: requireEnv("STRIPE_WEBHOOK_SECRET"),
        }
        : undefined,
    },
    jwt: {
      secret: requireEnv("JWT_SECRET"),
      expiresIn: process.env.JWT_EXPIRES_IN || "30d",
    },
    gateway: {
      baseUrl: requireEnv("GATEWAY_BASE_URL"),
      chinaNode: optionalEnv("GATEWAY_CHINA_NODE"),
    },
    logLevel: process.env.LOG_LEVEL || "info",
  };
}
