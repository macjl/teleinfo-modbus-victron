FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY teleinfo_modbus_victron ./teleinfo_modbus_victron
RUN pip install --no-cache-dir '.[metrics]' && useradd --uid 10001 --no-create-home bridge
USER 10001:10001
EXPOSE 1502
ENTRYPOINT ["teleinfo-modbus"]
CMD ["--config", "/app/config.yaml"]
