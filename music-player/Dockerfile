FROM node:22-alpine

# yt-dlp für die Sofort-Wiedergabe. "default"-Extras enthalten yt-dlp-ejs;
# als JS-Runtime nimmt das Backend automatisch das Node dieses Images.
RUN apk add --no-cache python3 py3-pip ca-certificates \
 && pip install --no-cache-dir --break-system-packages "yt-dlp[default]"

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY src ./src
COPY public ./public

ENV NODE_ENV=production \
    PORT=3000 \
    DATA_DIR=/app/data

VOLUME /app/data
EXPOSE 3000

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD wget -qO- http://127.0.0.1:3000/manifest.webmanifest >/dev/null || exit 1

CMD ["node", "src/server.js"]
