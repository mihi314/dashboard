FROM python:3.10-slim-bullseye

WORKDIR /app

RUN pip install poetry==1.4.2

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY poetry.lock pyproject.toml /app/
RUN poetry install --without dev --no-root \
 && rm -rf /root/.cache/pypoetry

COPY . .

CMD ["poetry", "run", "python", "updater/main.py", "--print-jobs"]
