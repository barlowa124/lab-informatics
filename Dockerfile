# lab-informatics: LIMS registry, lablink capture API, dbt analytics.
# Single image shared by the compose services; each service picks its
# entrypoint via `command`.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY lab_instrument_gateway ./lab_instrument_gateway
COPY labStackDev ./labStackDev
COPY analytics ./analytics
COPY README.md LICENSE ./

RUN pip install --no-cache-dir -e ./lab_instrument_gateway \
 && pip install --no-cache-dir dbt-duckdb pandas scipy pytest httpx

EXPOSE 8000 8080

CMD ["python", "-m", "lablink.demo"]
