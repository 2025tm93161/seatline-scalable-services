FROM python:3.12-slim
ARG SERVICE
WORKDIR /app
COPY services/${SERVICE}/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY common common
COPY services/${SERVICE} services/${SERVICE}
COPY frontend frontend
ENV SERVICE=${SERVICE} HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
RUN useradd --create-home appuser
USER appuser
CMD ["sh", "-c", "exec uvicorn services.${SERVICE}.main:app --host ${HOST} --port ${PORT}"]