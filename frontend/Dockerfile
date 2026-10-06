# check=skip=SecretsUsedInArgOrEnv
# Build the static frontend and serve it with nginx (proxying /api and /files to the backend).
# VITE_CESIUM_ION_TOKEN is a public, browser-side Cesium ion token: Vite embeds every VITE_* value in the
# client bundle, so it is not a secret (restrict it by URL in the Cesium ion dashboard instead).
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Build args are visible as environment variables to RUN in this stage, which is all Vite needs.
ARG VITE_CESIUM_ION_TOKEN=""
RUN npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
