# Review app for the ECS deployment: Next.js standalone server on port 3000.
# Build context is the repo root; the design system (@crm-ui/react) comes from the crm-ui repository
# as a second build context, placed where ui/'s link:../../crm-ui/packages/ui points:
#   docker build -f ui/Dockerfile --build-context crm-ui=../crm-ui -t claimpilot-ui .
FROM node:22-bookworm-slim AS build
WORKDIR /crm-ui/packages/ui
RUN corepack enable
COPY --from=crm-ui packages/ui/package.json packages/ui/pnpm-lock.yaml packages/ui/README.md ./
# A linked package keeps its own node_modules (Next type-checks its source against them).
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY --from=crm-ui packages/ui/src src
COPY --from=crm-ui packages/ui/tokens tokens
COPY --from=crm-ui packages/ui/assets assets
WORKDIR /app/ui
COPY ui/package.json ui/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY ui/ ./
ENV NEXT_OUTPUT=standalone NEXT_TELEMETRY_DISABLED=1
RUN pnpm next build

FROM node:22-bookworm-slim
WORKDIR /srv
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
# The trace root is / (it must hold both /app/ui and /crm-ui), so the server sits at app/ui/.
COPY --from=build --chown=node:node /app/ui/.next/standalone ./
COPY --from=build --chown=node:node /app/ui/.next/static ./app/ui/.next/static
COPY --from=build --chown=node:node /app/ui/public ./app/ui/public
USER node
EXPOSE 3000
CMD ["node", "app/ui/server.js"]
