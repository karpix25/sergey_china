# Build stage
FROM node:20-alpine as build-stage

WORKDIR /app

# Accept build arguments for environment variables
ARG VITE_API_URL
ARG VITE_INTERNAL_API_KEY

# Set them as environment variables for the build process
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_INTERNAL_API_KEY=$VITE_INTERNAL_API_KEY

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Production stage
FROM nginx:stable-alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build-stage /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
