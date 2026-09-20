# hourbot

Opens a Discord category for a fixed window each day, then closes it again.
Configuration is read from the environment; see `.env.example`.

## Run with Docker

Images are built for amd64 and arm64 on every push to `main` and published
to `ghcr.io/rjwebb/hourbot`. On the host:

```sh
cp .env.example .env   # fill in the token and IDs
docker compose pull
docker compose up -d
docker compose logs -f
```

Update to the latest image:

```sh
docker compose pull && docker compose up -d
```

Stop:

```sh
docker compose down
```

To build from source instead of pulling, run `docker compose up -d --build`.

The container restarts automatically after a crash or a host reboot. The
`TIMEZONE` setting works inside the image because the `tzdata` package is
installed alongside the dependencies.

## Run locally

```sh
pip install -r requirements-dev.txt
python bot.py
pytest
```
