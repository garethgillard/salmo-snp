# The portal on the salmobase server: brief (2026-11-25)

This brief is for the chat that deploys the portal on the salmobase server: the chat on Orion over SSH, which also
builds and publishes the data releases ([ORION.md](ORION.md)). Nothing here has been run on the server yet. It was
tried in a cloud session on a mock of the server: its datafiles folder made from the published releases, mounted
read only, and Apache in front of a stand-in for salmobase's own site with the portal beside it. Read
[../AGENTS.md](../AGENTS.md) first: its rules apply here too. Keep this file up to date as the work goes on.

## Who does what (G, 2026-11-25)

"We should prepare to setup the deployment option to salmobase server. Then we can work on feature development in
this chat, and then hand off building and deploying releases to salmobase in the orion ssh chat."

| | Does | Where it is written |
|---|---|---|
| The chat on the code (a cloud session) | Features, by pull request; main is what was tested | AGENTS.md |
| The chat on Orion | Builds the data releases, publishes them on salmobase, and installs and updates the portal on the salmobase server | ORION.md, this file |
| G | Says what a release contains, and when anything is published or deployed | |

Until the portal is live on salmobase the public demo stays on NREC, deployed by GitHub's `deploy` workflow when G
says (AGENTS.md "Deploying the NREC demo").

## How the portal runs there

- **One process**: gunicorn, started by `snpportal/deploy/server.sh`, answering everything under `/snp/` (its
  static files too) behind salmobase's Apache, which needs two proxy lines. It is not part of salmobase's own
  Django; salmobase links to it with a button.
- **The data is read where it is published.** One setting, `SNPSCORE_SALMOBASE`, names the server's datafiles
  folder (what `https://salmobase.org/datafiles/` serves). The portal writes nothing there.

  | What | Where under the datafiles folder |
  |---|---|
  | The releases | `datasets/salmo-snp/releases/<version>/`, with each one's `pool/` |
  | The genomes | The address in each release's manifest: `genomes/AtlanticSalmon/Ssal_v3.1/sequence_Ensembl/` and `genomes/RainbowTrout/USDA_OmykA_1.1/sequence_Ensembl/`, each `.fa.gz` with its `.fai` and `.gzi` |
  | The Locus browser's tracks | `datasets/Aqua-Faang/` (842 files for salmon, 771 for trout) |
  | The ChromBPNet model of the Predict button | `datasets/chrombpnet/AtlanticSalmon/v1/Gill/` |

  A file that is not there is read from its address instead, as on any other machine, so nothing breaks when a
  path differs: the service's first lines say how much it found (below).
- **Its own folder** (`SNPPORTAL_DATA`): `results/` (each kept 24 hours, mode 0700), `secret_key` and `static/`. No
  database.
- **Which releases it shows**: the ones its version names (`snpportal/snpportal/serve.py`, `RELEASE` and
  `RELEASES`), found in the releases folder. A release that is published but not named yet is not shown, so a
  publish changes nothing on the live site; the deploy of a version that names it does.
- **Public pools** are never built on the server: its releases folder is read only. They are built on Orion and
  published with the release. After a change to the tier rules (`snpscore/src/snpscore/weights.yaml`) the pools no
  longer fit, the Overview leaves out its public comparison, and the service says so when it starts: build them
  again on Orion and publish again ("A new data release, or new tier rules", below).
- **What it takes**: Python 3.11 or newer (3.12 is what is tested). Measured on the container in a cloud session:
  100 MB of memory at rest and 1.3 GB at the most while the examples were scored (a job may take 2 GB:
  `SNPPORTAL_DUCKDB_MEMORY`); two threads a job, one job at a time; it answers five seconds after it starts.

## What is known about the server

Seen from outside on 2026-11-25, with ordinary requests to the public site, and from the publishing work:

- **Apache 2.4.68 on Debian** is in front, on salmobase.org and on test.salmobase.org. It answers `/datafiles/` (a
  listing of the folder) and `/static/` itself.
- **salmobase's own pages come from a Django application behind it**, which answers as Django's own server
  (`WSGIServer/0.2 CPython/3.12.16`): the home page, `/jbrowse/`, `/robots.txt`. So Apache already proxies, and a
  Python 3.12 runs wherever that application does (on the server itself or in a container).
- **`/snp/` is free**: both hosts answer 404 there, from salmobase's application.
- salmobase's pages set no cookie on the pages looked at (home, the BLAST form); its admin pages would, under
  Django's usual names. They load Bootstrap 5.1.3, a cookie-consent script and Google's tag manager from other
  sites. Its robots.txt disallows `/admin/` only.
- From Orion, `ssh salmobase` is the live server (web-05.orion.nmbu.no) and `ssh test.salmobase` the test server;
  the user's `datafiles/` there is the served folder, with the releases in `datasets/salmo-snp/releases/`.

Not known, and not visible from outside: how that Django application is started and by whom, whether the server has
Docker, how much memory it has, where Apache's virtual host file is and who may edit it. The survey below answers
the first three; the table at the end collects all of it.

## Beside salmobase's own site

The portal is a second application on the same host name. What keeps the two apart, each point tried behind Apache
with a stand-in for salmobase's application (a Django site with a form of its own):

- **Addresses**: everything of the portal is under `/snp/`: its pages, its forms and its static files
  (`/snp/static/`). It answers nothing else, and salmobase's `/static/` and `/datafiles/` are not touched.
- **Cookies**: the portal's have names of their own (`snpportal_csrftoken`, `snpportal_*`, `snp_species`) and the
  path `/snp/` (`SNPPORTAL_COOKIE_PATH`, which server.sh sets), so salmobase's pages never receive them, and the
  portal neither reads nor replaces Django's usual `csrftoken` of salmobase's forms. Tried with one browser on both
  sites: each site's form was accepted with the other's cookies present, and the stand-in received only its own.
- **Headers**: its pages may be framed by its own pages only, browsers are told not to guess content types, and a
  result's page is never stored by caches or listed by search engines.
- **No request to other sites**: Bootstrap and htmx come with the package. salmobase's cookie-consent script and
  tag manager are not on the portal's pages.
- **Its own process**: a port on 127.0.0.1, its own Python environment or container, its own data folder. It shares
  no database, no code and no session with salmobase's application. While it is stopped or being updated the site
  answers as before, and `/snp/` answers 503 from Apache.
- **What it may use**: one list is scored at a time (others wait, at most ten), with two threads and 2 GB at the
  most; an upload is at most 300 MB and is deleted once scored; results go after 24 hours. To be sure that it
  cannot starve the site, give it a ceiling: `--memory 4g --cpus 2` for the container, `MemoryMax=4G` and
  `CPUQuota=200%` in the service file (both are in the commands below).

Navigation between salmobase's pages and the portal (a menu entry there, a way back here) is left for later (G,
2026-11-25): until then the portal is an address, `https://salmobase.org/snp/`.

## Step 0: look at the server

`snpportal/deploy/survey.sh` only reads; it creates, changes and starts nothing. From the clone on Orion:

```bash
ssh test.salmobase 'bash -s' < snpportal/deploy/survey.sh
ssh salmobase 'bash -s' < snpportal/deploy/survey.sh
```

What its answers decide. Write them into the table at the end of this file.

| Question | If yes | If no |
|---|---|---|
| Docker or Podman, usable by this user? | Way A, the container | Way B |
| Python 3.11 or newer (or `uv`, or conda)? | Way B is possible | Way A only; or ask for a Python |
| May this user keep a service running (`Linger=yes`, or the way salmobase's own services are kept)? | A user service | Ask the server's administrator for a system service with the same lines |
| Where is the datafiles folder, and can the service's user read it? | That path is `SNPSCORE_SALMOBASE` | Stop: the design needs it |
| Who edits Apache's configuration? | They add the two lines below, once | Stop and tell G |
| Does the server reach GitHub and PyPI (and Docker Hub for way A)? | Install there | Build the image, or a folder of wheels, on Orion and copy it over |

Start on the test server (`test.salmobase`), with `DJANGO_ALLOWED_HOSTS=test.salmobase.org`; repeat on the live
one when G says.

## Way A: a container

On the server, in a clone of the repository at the commit to deploy (a tag later):

```bash
git clone https://github.com/garethgillard/salmo-snp.git ~/salmo-snp/code   # once
cd ~/salmo-snp/code && git fetch -q origin main && git checkout -q --detach <commit>
docker build -f snpportal/deploy/Dockerfile -t salmo-snp:<commit> .
mkdir -p ~/salmo-snp/data && sudo chown 1000 ~/salmo-snp/data                # the container's user; once
docker rm -f salmo-snp 2> /dev/null
docker run -d --name salmo-snp --restart unless-stopped -p 127.0.0.1:8090:8000 --memory 4g --cpus 2 \
  -v <the datafiles folder>:/datafiles:ro -v ~/salmo-snp/data:/data \
  -e DJANGO_ALLOWED_HOSTS=salmobase.org salmo-snp:<commit>
docker logs salmo-snp 2>&1 | head
```

Tried in a cloud session on the mock: the image (571 MB) builds, the container runs as its own user with the
datafiles folder mounted read only, and the smoke test passes on it (all five salmon examples and the three trout
ones).

## Way B: a virtual environment and a user service

```bash
git clone https://github.com/garethgillard/salmo-snp.git ~/salmo-snp/code   # once
cd ~/salmo-snp/code && git fetch -q origin main && git checkout -q --detach <commit>
python3.12 -m venv ~/salmo-snp/venv                                          # once
~/salmo-snp/venv/bin/pip install --upgrade ./snpscore "./snpportal[chrombpnet]" gunicorn
mkdir -p ~/salmo-snp/data ~/.config/systemd/user
```

`~/.config/systemd/user/salmo-snp.service` (once):

```ini
[Unit]
Description=salmo-snp portal (https://salmobase.org/snp/)

[Service]
Environment=PATH=%h/salmo-snp/venv/bin:/usr/bin:/bin
Environment=SNPSCORE_SALMOBASE=<the datafiles folder>
Environment=SNPPORTAL_DATA=%h/salmo-snp/data
Environment=SNPPORTAL_BIND=127.0.0.1:8090
Environment=DJANGO_ALLOWED_HOSTS=salmobase.org
ExecStart=/bin/sh %h/salmo-snp/code/snpportal/deploy/server.sh
Restart=on-failure
MemoryMax=4G
CPUQuota=200%

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload && systemctl --user enable --now salmo-snp
journalctl --user -u salmo-snp -n 20 --no-pager
```

The same script was tried this way in a cloud session on the mock (started by hand, as there is no systemd there).
The unit file itself has not been tried. A user service applies `MemoryMax` and `CPUQuota` only where the system
lets users set them; where it does not, they are ignored without an error, and the portal's own limits still hold
(`systemctl --user show salmo-snp -p MemoryMax -p CPUQuotaPerSecUSec` says what is in force).

## What the service says when it starts

```
release 2026-11-25 (Atlantic salmon): genome on the disk; 842 of 842 track files on the disk; public pool fits
release trout-2026-11-25 (Rainbow trout): genome on the disk; 771 of 771 track files on the disk; public pool fits
System check identified no issues (0 silenced).
```

Fewer track files than all, or `genome read from its address`: a path under the datafiles folder is not where the
table above says. The portal still works, reading those from `https://salmobase.org`, more slowly, if the server
reaches its own public name. `no release at ...`: the version names a release that is not in the releases folder
(not published, or the folder is not the one set). `PUBLIC POOL MISSING OR BUILT FOR OTHER WEIGHTS`: see below.

## Apache, once (whoever may edit its configuration)

In the virtual host of salmobase.org (on Debian a file in `/etc/apache2/sites-available/`; the survey lists the
enabled ones and their proxy lines):

```apache
<Location /snp/>
    ProxyPass        http://127.0.0.1:8090/snp/ timeout=300
    ProxyPassReverse http://127.0.0.1:8090/snp/
    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    LimitRequestBody 314572800
</Location>
```

```bash
sudo a2enmod proxy proxy_http headers      # the first two are on already, as Apache proxies salmobase's own pages
sudo apache2ctl configtest && sudo systemctl reload apache2
curl -s https://test.salmobase.org/snp/health/
```

- Everything in the block applies to `/snp/` alone, so salmobase's own proxy rule is not changed.
- Tried on Apache 2.4.71 in front of a stand-in for salmobase's application that took every other address: the
  block wins wherever it stands in the file. Written as plain `ProxyPass /snp/ ...` lines instead, it must stand
  above the rule that sends everything else to salmobase's application, or that application answers `/snp/` (404).
- `timeout=300` and `LimitRequestBody` are for uploads: lists of up to 300 MB, scored for up to five minutes before
  the page answers. `X-Forwarded-Proto` tells the portal that the visitor came by https, so that it marks its
  cookies for https only (its forms were accepted without the line too, in the trial).
- Through that Apache the smoke test passed for both species, a file was uploaded and scored, and the stand-in's
  own form kept working. With the portal not running, `/snp/` answered 503 and the stand-in's pages 200.

## Check a deploy

`tools/smoke.sh` asks the health page, then scores every example of the Score page for each species through the job
queue, opens each result and deletes it. On the server, before Apache knows the portal, and through Apache after:

```bash
bash ~/salmo-snp/code/tools/smoke.sh http://127.0.0.1:8090 salmobase.org
bash tools/smoke.sh https://salmobase.org                                    # from anywhere
```

```
health: ok; release 2026-11-25 (Ssal_v3.1); species {'atlantic_salmon': '2026-11-25', 'rainbow_trout': 'trout-2026-11-25'}; genome local; public pool fits; tracks {'salmobase.org': True, 'read from the disk': '842 of 842'}; predict {'models': ['chrombpnet_gill'], 'packages': True}
atlantic_salmon known_loci: scored in 17 s
...
smoke: ok
```

It ends with `smoke: ok` or says which example failed, and exits accordingly. `EXAMPLES=known_loci` scores only
that one. The health page alone: `/snp/health/?tracks=1`.

## Working from Orion

- Every command on the server is `ssh salmobase '<command>'` (or `ssh test.salmobase`) from a login node. A login
  node cuts a long connection (an rsync after about ten minutes), so start anything long detached and read its log:
  `ssh salmobase 'cd ~/salmo-snp/code && nohup docker build -f snpportal/deploy/Dockerfile -t salmo-snp:<commit> . > ~/salmo-snp/build.log 2>&1 &'`,
  then `ssh salmobase 'tail -3 ~/salmo-snp/build.log'`.
- **If the server does not reach GitHub or PyPI** (the survey's last lines): send Orion's clone instead of cloning
  there, `rsync -a --delete --exclude .git ~/git/salmo-snp/ salmobase:salmo-snp/code/` (the copy is then at the
  commit Orion's clone is at, and the `git` lines above are skipped; `--delete` here touches that copy of the code
  alone), and for way B build the packages on Orion with the Python version the server has and send them:

  ```bash
  pip wheel -w ~/salmo-snp-wheels ./snpscore "./snpportal[chrombpnet]" gunicorn
  rsync -a ~/salmo-snp-wheels/ salmobase:salmo-snp/wheels/
  ssh salmobase '~/salmo-snp/venv/bin/pip install --no-index --find-links ~/salmo-snp/wheels --upgrade snpscore "salmo-snp[chrombpnet]" gunicorn'
  ```

  Not tried. For way A the image can be built where Docker is and sent with `docker save | ssh salmobase docker load`.
- **If the server has no Python 3.11 or newer and no Docker**: `uv` installs one without administrator rights
  (`curl -LsSf https://astral.sh/uv/install.sh | sh`, then `uv python install 3.12` and `uv venv --python 3.12
  ~/salmo-snp/venv`), if the server reaches GitHub. Not tried there. If the survey shows Orion's project storage
  mounted on the server, tell G before using an environment from it: the server would then depend on that mount.
- **Logs**: `docker logs salmo-snp` or `journalctl --user -u salmo-snp`. They hold event names, a job's reference,
  counts and timings, never a SNP or a file name. Nothing else needs looking after: results delete themselves, and
  `free_gb` on the health page is the room left in the data folder.

## Update to a new version

Only when G says. Pull main on Orion first and read what changed in this file.

- Way A: the `git checkout`, `docker build`, `docker rm -f` and `docker run` lines above, with the new commit.
- Way B: the `git checkout` and `pip install` lines above, then `systemctl --user restart salmo-snp`.

Then the smoke test. To go back: the same with the commit before (way A: `docker run` the image of the commit
before, which is still there). Results and the secret key are in the data folder and survive both.

## A new data release, or new tier rules

1. Build and publish the release from Orion (ORION.md, steps 1 to 5). The live portal does not change.
2. The chat on the code names the release in `serve.py` (a pull request, which G merges).
3. Update the portal to that commit (above). Its first lines name the new releases.

After a change to weights.yaml the pools published with the releases no longer fit. On Orion, with the clone at the
commit that is going to be deployed (a job, not a login node; half a minute a release):

```bash
snpscore pool --release release/<version> --if-stale --memory 16GB --threads 8
snpscore pool --release release/trout-<version> --if-stale --memory 16GB --threads 8
MODE=dry bash prep/orion_publish.sh <version> trout-<version>     # sends the two pool folders only; then MODE=run
```

Then restart the portal, which reads a pool when it starts.

## What is not known yet

Fill this in from the survey, and tell G what it means for the way to install.

| | test.salmobase | salmobase |
|---|---|---|
| Operating system (Debian, by Apache's answer), cores, memory | | |
| The datafiles folder's path, and whether both servers serve the same one | | |
| The user the portal runs as, and the room in its home | | |
| Docker or Podman, usable by that user | | |
| Python 3.11 or newer outside salmobase's own environment | | |
| A service this user may keep running (`Linger`) | | |
| How salmobase's own application is started (it must not be disturbed) | | |
| Apache's virtual host file, and who may edit it | | |
| The port (8090 unless taken) | | |
| Reaches GitHub, PyPI, Docker Hub | | |

For G: who edits Apache's configuration on the two servers (the one step that needs an administrator); whether the
portal should carry salmobase's cookie-consent and tag-manager scripts (it carries none); the menu entry on
salmobase and the way back, later; and DECISIONS #67 and #68 (whether the portal should take the newest published
release by itself, and how the build chat hands back). Also open: a tagged version for each deploy instead of a
commit of main, and when the NREC demo is switched off.
