FROM node:22-alpine AS build
WORKDIR /app
COPY apps/web/package.json ./
# Release gate: resolve/audit dependencies and commit a lockfile, then switch to npm ci.
RUN npm install --no-audit --no-fund
COPY apps/web ./
ENV NEXT_TELEMETRY_DISABLED=1 API_INTERNAL_URL=http://api:8000
RUN npm run build
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 API_INTERNAL_URL=http://api:8000
COPY --from=build --chown=node:node /app ./
USER node
EXPOSE 3000
CMD ["npm", "start"]
