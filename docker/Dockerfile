FROM python:3.12-slim
RUN pip install --no-cache-dir numpy scipy pandas
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/workspace
WORKDIR /workspace
CMD ["sleep", "infinity"]
