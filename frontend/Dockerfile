# Build stage
FROM node:20-alpine as build-stage

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
# Set VITE_API_URL if needed during build, or handle it via environment
RUN npm run build

# Production stage
FROM nginx:stable-alpine as production-stage

COPY --from=build-stage /app/dist /usr/share/nginx/html

# Copy custom nginx config if we had one, but default is usually fine for simple SPA
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
