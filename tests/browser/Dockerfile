# Optional browser-QA image. The live test lab never starts external bots.
FROM mcr.microsoft.com/playwright:v1.56.1-noble

WORKDIR /work
COPY tests/browser/package.json ./
RUN npm install --no-audit --no-fund

COPY tests/browser/ ./
ENV CI=1
CMD ["npx", "playwright", "test", "--reporter=list"]
