FROM python:3.12-slim AS final
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && adduser --system --no-create-home analyzer
USER analyzer
ENTRYPOINT ["analyzer"]
CMD ["once"]
