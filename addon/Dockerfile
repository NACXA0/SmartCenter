ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20

# —— 工作台（Vite）——
FROM node:22-alpine AS webui
WORKDIR /src/web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-fund --no-audit
COPY web/ ./
RUN npm run build

# —— Add-on runtime ——
FROM ${BUILD_FROM}
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=webui /src/app/webui ./app/webui
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
