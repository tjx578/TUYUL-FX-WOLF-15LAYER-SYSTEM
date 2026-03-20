# Prometheus Target Discovery for Railway

## How it works

Prometheus uses file-based service discovery (`file_sd_configs`) to find scrape targets.
Each `*.json` file in this directory defines targets for one service.

## Local (Docker Compose)

The default files point to Docker Compose service names. No changes needed.

## Railway Deployment

On Railway, each service gets an internal hostname like `<service>.railway.internal`.
To configure Prometheus for Railway:

1. Mount this directory into the Prometheus container at `/etc/prometheus/targets/`
2. Override the target files with Railway internal hostnames:

```json
// wolf-api.json (Railway)
[{"targets": ["wolf-api.railway.internal:8000"], "labels": {"service": "api", "env": "railway"}}]
```

```json
// wolf-allocation.json (Railway)
[{"targets": ["wolf-allocation.railway.internal:9102"], "labels": {"service": "allocation", "env": "railway"}}]
```

```json
// wolf-execution.json (Railway)
[{"targets": ["wolf-execution.railway.internal:9103"], "labels": {"service": "execution", "env": "railway"}}]
```

1. Alternatively, use Railway's shared variables to template the target JSON at deploy time
   in your `start_*.sh` scripts.

## File format (Prometheus file_sd)

```json
[
  {
    "targets": ["<host>:<port>"],
    "labels": {
      "service": "<service-name>",
      "env": "<environment>"
    }
  }
]
```
