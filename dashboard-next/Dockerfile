# Separate, optional dashboard runtime. Python/Telegram/Bale remain untouched.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
COPY scripts/patch-next-themes.mjs ./scripts/patch-next-themes.mjs
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# CDN assetPrefix is embedded at build time; no CDN is the default.
ARG NEXT_ADMIN_CDN_URL
ENV NEXT_ADMIN_CDN_URL=$NEXT_ADMIN_CDN_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run typecheck && npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
