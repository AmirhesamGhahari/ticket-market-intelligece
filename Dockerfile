FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY configs/ configs/
COPY alembic/ alembic/
COPY alembic.ini alembic.ini

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["run-pipeline"]
