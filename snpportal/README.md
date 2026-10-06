# salmo-snpportal

Django app for salmobase.org: upload a SNP list, see it annotated with AQUA-FAANG functional maps in a sortable table, download all columns as TSV.
All annotation logic lives in the sibling repo [salmo-snpscore](../salmo-snpscore); this app only handles upload, display and export.

## Run locally

```bash
pip install -r requirements.txt                       # also installs ../salmo-snpscore (editable)
(cd ../salmo-snpscore && snpscore fetch && snpscore build --out release/dev)
python manage.py runserver                            # http://127.0.0.1:8000/snp/
python manage.py test snpportal
```

`sandbox/` is a minimal Django project for development only. Its `templates/salmobase/base.html` stands in for salmobase's real base template.

## Merging into salmobase

1. Copy `snpportal/` into `salmobase/salmobase/`.
2. `settings.py`: add `"snpportal"` to `INSTALLED_APPS` and `SNPSCORE_RELEASE = getenv("SNPSCORE_RELEASE")`.
   Optionally set `SNPPORTAL_RESULTS_DIR` (default: a `snpportal` folder in the system temp dir).
3. `urls.py`: `path('snp/', include('snpportal.urls'))`.
4. `requirements.txt`: add `duckdb` and `snpscore @ git+<salmo-snpscore repo URL>`.
5. Put a release under `/datafiles` (e.g. `/datafiles/snpscore/v0.1`) and set `SNPSCORE_RELEASE` in docker-compose.

salmobase's Docker image uses Python 3.8, which limits DuckDB to 1.2.2 and Django to 4.2. Both are tested and work.
