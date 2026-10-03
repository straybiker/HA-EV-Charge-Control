# Linux image for the Home Assistant tests, which do not run on Windows.
# Build and run it with scripts/test-ha.ps1.
FROM python:3.14-slim
WORKDIR /src
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
CMD ["pytest", "-q", "-p", "no:cacheprovider"]
