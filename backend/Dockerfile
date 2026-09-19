FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY requirements.lock ./
RUN pip install \
    --isolated \
    --no-cache-dir \
    --disable-pip-version-check \
    --only-binary=:all: \
    --index-url https://mirrors.aliyun.com/pypi/simple/ \
    --require-hashes \
    -r requirements.lock

COPY app ./app
COPY judge_cases ./judge_cases
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY pyproject.toml ./pyproject.toml

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]