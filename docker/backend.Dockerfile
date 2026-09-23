FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --system saup && useradd --system --gid saup --home-dir /app saup
COPY pyproject.toml ./
COPY packages ./packages
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir . && chown -R saup:saup /app
USER saup
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
