FROM node:24-slim AS dashboard
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend ./frontend
RUN npm run build
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home bot && mkdir /app/data && chown bot:bot /app/data
COPY --chown=bot:bot . .
COPY --from=dashboard --chown=bot:bot /build/frontend/out ./frontend/out
USER bot
CMD ["python", "main.py"]
