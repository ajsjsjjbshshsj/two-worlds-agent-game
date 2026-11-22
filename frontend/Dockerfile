# Stage 1: Build Vue SPA & PWA artifacts
FROM node:22-alpine AS builder
WORKDIR /app

# Allow passing the public API base URL at build time
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# Install locked dependencies first
COPY package.json package-lock.json ./
RUN npm ci

# Copy frontend source and build production bundle
COPY . ./
RUN npm run build

# Stage 2: Serve static bundle with lightweight Nginx
FROM nginx:1.27-alpine AS runner

# Copy customized Nginx server block
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy production static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Security: Configure non-root permissions for the standard nginx user
RUN touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /var/log/nginx /usr/share/nginx/html /etc/nginx/conf.d

USER nginx

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
