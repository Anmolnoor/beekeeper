FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY beehive /app/beehive
COPY tests /app/tests

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

CMD ["python", "-m", "beehive.demo"]
