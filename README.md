# hourbot

Opens a Discord category for a fixed window each day, then closes it again.
Configuration is read from the environment; see `.env.example`.

## Run with Docker

Images are built for amd64 and arm64 on every push to `main` and published
to `ghcr.io/rjwebb/hourbot`. You don't need to clone this repository to run
it; the image carries the config template.

In an empty directory on the host:

```sh
docker run --rm ghcr.io/rjwebb/hourbot cat .env.example > .env
$EDITOR .env   # fill in the token and IDs
```

Then save this as `docker-compose.yml` next to it:

```yaml
services:
  hourbot:
    image: ghcr.io/rjwebb/hourbot:latest
    env_file: .env
    restart: unless-stopped
    read_only: true
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "3"
```

and start it:

```sh
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

If you have cloned the repository, the same commands work with the compose
file it contains; `docker compose up -d --build` builds from source instead
of pulling.

The container restarts automatically after a crash or a host reboot. The
`TIMEZONE` setting works inside the image because the `tzdata` package is
installed alongside the dependencies.

## Run locally

```sh
pip install -r requirements-dev.txt
python bot.py
pytest
```
