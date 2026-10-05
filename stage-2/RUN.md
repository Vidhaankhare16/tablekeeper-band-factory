# Tablekeeper — stage 1

Build and start (no manual setup, no network needed at run time):

```
docker build -t tablekeeper . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper
```

Then `curl http://localhost:8080/health`. The image is `python:3.12-slim` plus the standard library only.

Unit tests (host, Python 3.11+): `python3 -m unittest discover -s tests`
