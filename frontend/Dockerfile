FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Upstream for /api and health proxying. Compose keeps the default; Container Apps passes http://<api-app-name>.
ARG BACKEND_UPSTREAM=http://backend:8000
RUN sed "s|http://backend:8000|$BACKEND_UPSTREAM|g" nginx.conf > nginx.rendered.conf

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /app/nginx.rendered.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
