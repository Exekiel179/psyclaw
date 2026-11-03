/**
 * 认证中间件：验证 Authorization header 中的 JWT token
 */

import type { FastifyRequest, FastifyReply } from "fastify";
import type { TokenService } from "./token.js";

export interface AuthenticatedRequest extends FastifyRequest {
  userId: string;
}

export function createAuthMiddleware(tokenService: TokenService) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
    const authHeader = request.headers.authorization;

    if (!authHeader) {
      reply.code(401).send({
        error: {
          message: "Missing Authorization header",
          type: "authentication_error",
          code: "missing_auth",
        },
      });
      return;
    }

    const match = /^Bearer\s+(.+)$/i.exec(authHeader);
    if (!match) {
      reply.code(401).send({
        error: {
          message: "Invalid Authorization header format. Expected: Bearer <token>",
          type: "authentication_error",
          code: "invalid_auth_format",
        },
      });
      return;
    }

    const token = match[1]!;

    try {
      const payload = await tokenService.verify(token);
      (request as AuthenticatedRequest).userId = payload.userId;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Token verification failed";
      reply.code(401).send({
        error: {
          message,
          type: "authentication_error",
          code: "invalid_token",
        },
      });
    }
  };
}
