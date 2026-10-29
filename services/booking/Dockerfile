FROM python:3.12-slim
WORKDIR /app
COPY services/booking/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY common common
COPY services/booking services/booking
COPY frontend frontend
ENV HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1 FRONTEND_DIR=/app/frontend
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "services.booking.main:app", "--host", "0.0.0.0", "--port", "8000"]
