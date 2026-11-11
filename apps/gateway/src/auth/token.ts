/**
 * JWT token 生成与验证
 */

import { SignJWT, jwtVerify, type JWTPayload } from "jose";

export interface TokenPayload extends JWTPayload {
  userId: string;
  type: "access" | "refresh";
}

export interface TokenService {
  generate(userId: string, expiresIn?: string): Promise<string>;
  verify(token: string): Promise<TokenPayload>;
}

export class JwtTokenService implements TokenService {
  private readonly secret: Uint8Array;
  private readonly issuer = "psyclaw-gateway";
  private readonly audience = "psyclaw-client";

  constructor(secret: string) {
    this.secret = new TextEncoder().encode(secret);
  }

  async generate(userId: string, expiresIn = "30d"): Promise<string> {
    const token = await new SignJWT({ userId, type: "access" })
      .setProtectedHeader({ alg: "HS256" })
      .setIssuedAt()
      .setIssuer(this.issuer)
      .setAudience(this.audience)
      .setExpirationTime(expiresIn)
      .sign(this.secret);

    return token;
  }

  async verify(token: string): Promise<TokenPayload> {
    try {
      const { payload } = await jwtVerify(token, this.secret, {
        issuer: this.issuer,
        audience: this.audience,
      });

      if (!payload.userId || typeof payload.userId !== "string") {
        throw new Error("Invalid token: missing userId");
      }

      return payload as TokenPayload;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Token verification failed";
      throw new Error(`Invalid token: ${message}`);
    }
  }
}
