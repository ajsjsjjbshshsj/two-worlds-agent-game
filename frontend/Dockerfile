# Stage 1: Build Vue SPA & PWA artifacts
FROM node:22-alpine AS builder
WORKDIR /app

# Allow passing the public API base URL at build time
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_DEMO_MODE=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_DEMO_MODE=${VITE_DEMO_MODE}

# Install locked dependencies first
COPY package.json package-lock.json ./
RUN npm ci

# Copy frontend source and build production bundle
COPY . ./
RUN npm run build

# Stage 2: Serve static bundle with lightweight Nginx
FROM nginx:1.27-alpine AS runner

ARG VITE_DEMO_MODE=false

# Copy both configs; only the explicit local Demo build selects the API proxy.
COPY nginx.conf /tmp/nginx.conf
COPY nginx.demo.conf /tmp/nginx.demo.conf
COPY --from=builder /app/dist /usr/share/nginx/html
RUN if [ "$VITE_DEMO_MODE" = "true" ]; then \
      cp /tmp/nginx.demo.conf /etc/nginx/conf.d/default.conf; \
    else \
      cp /tmp/nginx.conf /etc/nginx/conf.d/default.conf; \
    fi && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /var/log/nginx /usr/share/nginx/html /etc/nginx/conf.d

USER nginx

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
