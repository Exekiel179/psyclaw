FROM node:22-alpine

WORKDIR /app

COPY server.mjs .

ENV PORT=3000
ENV LANGFUSE_HOST=https://cloud.langfuse.com

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/').catch(() => process.exit(1))"

CMD ["node", "server.mjs"]
