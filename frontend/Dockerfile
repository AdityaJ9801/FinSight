# FinSight web app: build the React bundle, then serve it with nginx.
# nginx also forwards /api/* to the backend (API_URL, default http://api:5000), so the
# browser talks to one origin and no CORS or build-time API URL is needed.
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Leave VITE_API_BASE unset for the nginx setup (the app calls /api on its own origin);
# set it only when the backend lives on another domain.
ARG VITE_API_BASE
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM nginx:1.27-alpine
# The official image renders /etc/nginx/templates/*.template with envsubst at start-up.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
ENV API_URL=http://api:5000 \
    PORT=8080
EXPOSE 8080
