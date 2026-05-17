FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY beekeeper /app/beekeeper
COPY beekeeper_api /app/beekeeper_api
COPY queen_api /app/queen_api
COPY tests /app/tests
COPY scripts /app/scripts

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

CMD ["python", "-m", "beekeeper.demo"]
