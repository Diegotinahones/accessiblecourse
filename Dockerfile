FROM node:20-alpine AS ui
WORKDIR /repo
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM python:3.12-slim AS api
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY server.py ./server.py
COPY --from=ui /repo/dist ./public
CMD ["sh","-c","uvicorn server:app --host 0.0.0.0 --port ${PORT:-10000}"]
