# The portal as a container for salmobase (AGENTS.md plan 4): a tagged salmo-snp version, served by gunicorn under
# /snp/ (static files too), behind salmobase's Apache. Two volumes: salmobase's datafiles folder, read only (the
# published releases, the genomes, the AQUA-FAANG tracks and the models' files are read where they are), and the
# portal's own data folder (results, the secret key). On the salmobase server it runs from
# deploy/compose.salmobase.yml, on salmobase's Docker network (docs/SALMOBASE.md, which also has the block for
# salmobase's Apache file). By hand, from the repository root, checked out at a tag or a commit of main:
#   docker build -f snpportal/deploy/Dockerfile -t salmo-snp:<version> .
# Run it (the data folder belongs to uid 1000, the container's user, which must also be able to read datafiles):
#   docker run -d --name salmo-snp --restart unless-stopped -p 127.0.0.1:8090:8000 \
#     -v <the server's datafiles folder>:/datafiles:ro -v <the portal's data folder>:/data \
#     -e DJANGO_ALLOWED_HOSTS=salmobase.org salmo-snp:<version>
# One release in a folder of its own instead (as before 2026-11-25): -v <release>:/release -e SNPSCORE_RELEASE=/release
# -v <genomes>:/genome:ro -e SNPSCORE_GENOME_DIR=/genome.
# Behind a proxy that re-signs TLS, give pip its certificate: --secret id=ca,src=<bundle.crt>.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=snpsite.settings DJANGO_DEBUG=0 \
    DJANGO_STATIC_ROOT=/app/static DJANGO_STATIC_URL=/snp/static/ SNPPORTAL_SERVE_STATIC=1 \
    SNPSCORE_SALMOBASE=/datafiles SNPPORTAL_DATA=/data
COPY snpscore /src/snpscore
COPY snpportal /src/snpportal
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir /src/snpscore "/src/snpportal[chrombpnet]" gunicorn \
    && install -m 755 /src/snpportal/deploy/server.sh /usr/local/bin/salmo-snp-server \
    && rm -rf /src \
    && DJANGO_SECRET_KEY=build python -m django collectstatic --noinput -v 0 \
    && useradd --uid 1000 --create-home snp && mkdir -p /data /datafiles && chown snp /data
USER snp
EXPOSE 8000
HEALTHCHECK --interval=1m --timeout=10s --start-period=3m \
  CMD python -c "import os, urllib.request; host = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0]; \
urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/snp/health/', headers={'Host': host, 'X-Forwarded-Proto': 'https'}), timeout=8)"
CMD ["salmo-snp-server"]
