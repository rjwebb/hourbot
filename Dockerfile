FROM python:3.12-slim

# No compiled deps, so no build tools needed. Bytecode caches only bloat the
# image; unbuffered output makes logs show up in `docker logs` immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The slim image ships without /usr/share/zoneinfo; the tzdata wheel gives
# zoneinfo a database to fall back to so TIMEZONE keeps working.
COPY requirements.txt .
RUN pip install -r requirements.txt tzdata

COPY bot.py hours.py .

# The bot only talks outbound to Discord; it doesn't need root for anything.
RUN useradd --system --no-create-home hourbot
USER hourbot

CMD ["python", "bot.py"]
