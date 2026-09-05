# ---------- STAGE 1: DEPENDENCIES ----------
FROM node:22-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; \
    else npm install; fi

# ---------- STAGE 2: BUILD ----------
FROM node:22-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Non-secret build defaults make the immutable viewer contract testable locally.
# Railway can override these ARG values from service variables.
ARG DASHBOARD_MODE=viewer
ARG INTERNAL_API_URL=http://localhost:8000
ARG INTERNAL_DASHBOARD_BFF_URL=http://localhost:8080
ENV DASHBOARD_MODE=$DASHBOARD_MODE
ENV INTERNAL_API_URL=$INTERNAL_API_URL
ENV INTERNAL_DASHBOARD_BFF_URL=$INTERNAL_DASHBOARD_BFF_URL
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_OUTPUT_STANDALONE=true

RUN npm run build:strict

# ---------- STAGE 3: RUNTIME ----------
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV DASHBOARD_MODE=viewer
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
