# Local / ops scrape — same scrape.mjs as the API, on a fast machine or CI.
# Build:  docker build -t rinse-portal-scrape .
# Run:    ./docker-scrape.sh
# (Requires .env + rinse-auth.json in this directory; see run-local-portal-csv.sh.)

FROM node:22-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci \
  && npx playwright install --with-deps chromium

COPY scrape.mjs save-session.mjs ./

ENV RINSE_CSV_LAYOUT=portal

CMD ["node", "scrape.mjs"]
