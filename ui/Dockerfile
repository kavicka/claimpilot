# Review app for the ECS deployment: Next.js standalone server on port 3000.
# Build context is the repo root, because ui/ depends on packages/claimpilot-ui (the design system):
#   docker build -f ui/Dockerfile -t claimpilot-ui .
FROM node:22-bookworm-slim AS build
WORKDIR /app
RUN corepack enable
COPY packages/claimpilot-ui/package.json packages/claimpilot-ui/README.md packages/claimpilot-ui/
COPY packages/claimpilot-ui/src packages/claimpilot-ui/src
COPY packages/claimpilot-ui/tokens packages/claimpilot-ui/tokens
COPY packages/claimpilot-ui/assets packages/claimpilot-ui/assets
COPY ui/package.json ui/pnpm-lock.yaml ui/
WORKDIR /app/ui
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY ui/ ./
ENV NEXT_OUTPUT=standalone NEXT_TELEMETRY_DISABLED=1
RUN pnpm next build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/ui/.next/standalone ./
COPY --from=build --chown=node:node /app/ui/.next/static ./.next/static
COPY --from=build --chown=node:node /app/ui/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
