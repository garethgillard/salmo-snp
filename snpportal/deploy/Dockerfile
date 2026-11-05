# The portal as a container for salmobase (AGENTS.md plan 4): a tagged salmo-snp version, served by gunicorn under
# /snp/ (static files too), behind salmobase's Apache; the release, the genome and the results are volumes. README
# "salmobase container" has the Apache lines. Build it from the repository root, checked out at a tag:
#   docker build -f snpportal/deploy/Dockerfile -t salmo-snp:v0.1.0 .
# Run it (the data folders belong to uid 1000, the container's user):
#   docker run -d --name salmo-snp --restart unless-stopped -p 127.0.0.1:8090:8000 \
#     -v /srv/salmo-snp/release:/release -v /srv/salmo-snp/genome:/genome:ro -v /srv/salmo-snp/data:/data \
#     -e DJANGO_ALLOWED_HOSTS=salmobase.org salmo-snp:v0.1.0
# Behind a proxy that re-signs TLS, give pip its certificate: --secret id=ca,src=<bundle.crt>.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=snpsite.settings DJANGO_DEBUG=0 \
    DJANGO_STATIC_ROOT=/app/static DJANGO_STATIC_URL=/snp/static/ SNPPORTAL_SERVE_STATIC=1 \
    SNPSCORE_RELEASE=/release SNPSCORE_GENOME_DIR=/genome SNPPORTAL_RESULTS_DIR=/data/results
COPY snpscore /src/snpscore
COPY snpportal /src/snpportal
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir /src/snpscore /src/snpportal gunicorn \
    && install -m 755 /src/snpportal/deploy/container.sh /usr/local/bin/salmo-snp-container \
    && rm -rf /src \
    && DJANGO_SECRET_KEY=build python -m django collectstatic --noinput -v 0 \
    && useradd --uid 1000 --create-home snp && mkdir -p /data /release /genome && chown snp /data
USER snp
EXPOSE 8000
HEALTHCHECK --interval=1m --timeout=10s --start-period=3m \
  CMD python -c "import os, urllib.request; host = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0]; \
urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/snp/health/', headers={'Host': host, 'X-Forwarded-Proto': 'https'}), timeout=8)"
CMD ["salmo-snp-container"]
