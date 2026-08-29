FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system researchguard && adduser --system --ingroup researchguard researchguard

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install '.[openai]'

USER researchguard
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"

CMD ["uvicorn", "researchguard.api:app", "--host", "0.0.0.0", "--port", "8000"]
