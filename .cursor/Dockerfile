FROM node:22-bookworm-slim

# psyclaw's engines field requires Node >=22.19.0. The node:22 image tracks the
# latest 22.x release, which satisfies this. git and curl are needed for source
# checkout and the Pi runtime's managed-tool downloads; corepack activates the
# pnpm version pinned by package.json's packageManager field.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && corepack enable

USER node
