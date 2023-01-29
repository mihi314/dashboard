FROM python:3.10-slim-bullseye

WORKDIR /app

RUN apt-get update \
 && apt-get install --yes --no-install-recommends --no-install-suggests \
        wget \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN wget --quiet https://raw.githubusercontent.com/python-poetry/poetry/9591e88492508d4dba260952d53266a0032c04c7/get-poetry.py \
 && echo "08336beb0091ab192adef2cedbaa3428dabfc8572e724d2aa7fc4a4922efb20a get-poetry.py" | sha256sum --quiet --check \
 && python get-poetry.py --version 1.1.13 \
 && rm get-poetry.py
ENV PATH="${PATH}:/root/.poetry/bin"

# install python dependencies
COPY poetry.lock pyproject.toml /app/
RUN poetry config virtualenvs.create false \
 && poetry install --no-dev --no-interaction --no-ansi \
 && rm -rf /root/.cache/pypoetry

COPY . .

CMD ["python", "updater/main.py", "--print-jobs"]
