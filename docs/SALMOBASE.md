# The portal on the salmobase server: brief (2026-11-25)

This brief is for the chat that deploys the portal on the salmobase server: the chat on Orion over SSH, which also
builds and publishes the data releases ([ORION.md](ORION.md)). Nothing here has been run on the server yet. It was
tried in a cloud session on a mock of the server: salmobase's own Apache file from its repository, a stand-in for
its Django, and the server's datafiles folder made from the published releases and mounted read only. Read
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

## How salmobase itself runs

From its repository, https://gitlab.com/elixir-nmbu/salmobase (public; read at commit 9b1f40e of 2026-10-28), and
from what the live site answers:

- **A Docker Compose project with three services**: `app` (Apache, Django's own server and cron in one container,
  from `python:3.12-bookworm`; port 80 published), `db` (PostgreSQL 17) and `docs` (the documentation). Its compose
  file sits in a folder that also holds the clone as `src/salmobase`, `datafiles/` (mounted at `/datafiles` in
  `app`), `logs/` and `postgres-data/`, with the settings in a `.env`.
- **Apache is inside the `app` container.** Its configuration is `server_config/apache2/salmobase.conf` in the
  repository, copied into the image when the image is built. It answers `/datafiles` and `/static` itself, sends
  `/docs` to the `docs` service by its name, and everything else to Django on 127.0.0.1:8000 in the same container.
  It adds `Access-Control-Allow-Origin: *` to every answer, for JBrowse.
- **Only port 80 is published**: https ends somewhere in front of it, which is not in the repository.
- **Its Django** (5.2) has sessions and an admin: cookies `sessionid` and `csrftoken`, for https only. Addresses it
  uses: `/`, `/admin/`, `/genes/`, `/genomes/`, `/blast/`, `/jbrowse/`, `/alignments/`, `/import_run/` and
  `/robots.txt`. **`/snp` is free**: salmobase.org and test.salmobase.org answer 404 there today.
- From Orion, `ssh salmobase` is the live server (web-05.orion.nmbu.no) and `ssh test.salmobase` the test server;
  the user's `datafiles/` there is the served folder, with the releases in `datasets/salmo-snp/releases/`.

Not in the repository, so not known: the compose folder's path on the two servers, how salmobase's own containers
are rebuilt and by whom, what ends https in front of port 80, and the servers' memory. The survey below reads the
first and the last; the table at the end collects all of it.

## How the portal joins it

- **A container of its own, in a compose project of its own** (`snpportal/deploy/compose.salmobase.yml`), on
  salmobase's network under the name `snp`. Apache in salmobase's `app` container reaches it by that name, as it
  reaches `docs`. (An address on 127.0.0.1 would not do: Apache is inside a container, and its 127.0.0.1 is its own.)
- **One block in salmobase's Apache file** sends `/snp` to it. That is the one change in salmobase's own
  repository; it takes effect when salmobase's `app` image is built again and its container replaced.
- After that the portal is built, updated and stopped **without touching salmobase's containers**.
- **The data is read where it is published.** The portal mounts the same `datafiles/` folder as salmobase's `app`,
  read only, at `/datafiles`, and writes nothing there.

  | What | Where under the datafiles folder |
  |---|---|
  | The releases | `datasets/salmo-snp/releases/<version>/`, with each one's `pool/` |
  | The genomes | The address in each release's manifest: `genomes/AtlanticSalmon/Ssal_v3.1/sequence_Ensembl/` and `genomes/RainbowTrout/USDA_OmykA_1.1/sequence_Ensembl/`, each `.fa.gz` with its `.fai` and `.gzi` |
  | The Locus browser's tracks | `datasets/Aqua-Faang/` (842 files for salmon, 771 for trout) |
  | The ChromBPNet model of the Predict button | `datasets/chrombpnet/AtlanticSalmon/v1/Gill/` |

  A file that is not there is read from its address instead, as on any other machine, so nothing breaks when a
  path differs: the container's first lines say how much it found (below).
- **Its own folder** (`data/` beside its compose file): `results/` (each kept 30 days, mode 0700) and
  `secret_key`. No database.
- **Which releases it shows**: the ones its version names (`snpportal/snpportal/serve.py`, `RELEASE` and
  `RELEASES`), found in the releases folder. A release that is published but not named yet is not shown, so a
  publish changes nothing on the live site; the deploy of a version that names it does.
- **Public pools** are never built on the server: its releases folder is read only. They are built on Orion and
  published with the release. After a change to the tier rules (`snpscore/src/snpscore/weights.yaml`) the pools no
  longer fit, the Overview leaves out its public comparison, and the container says so when it starts: build them
  again on Orion and publish again ("A new data release, or new tier rules", below).
- **What it takes**: measured on the container in a cloud session, 100 MB of memory at rest and 1.3 GB at the most
  while the examples were scored (a job may take 2 GB: `SNPPORTAL_DUCKDB_MEMORY`); two threads a job, one job at a
  time; it answers five seconds after it starts. The image is 571 MB.

## Beside salmobase's own site

The portal is a second application on the same host name. What keeps the two apart; the addresses, the cookies and
the headers were tried behind salmobase's own Apache file with a stand-in for its Django (a site with a form of its
own under Django's usual cookie names):

- **Addresses**: everything of the portal is under `/snp/`: its pages, its forms and its static files
  (`/snp/static/`). It answers nothing else, and salmobase's `/static/`, `/datafiles/` and `/docs` are not touched.
- **Cookies**: the portal's have names of their own (`snpportal_csrftoken`, `snpportal_*`, `snp_species`) and the
  path `/snp/`, so salmobase's pages never receive them, and the portal neither reads nor replaces salmobase's
  `csrftoken` and `sessionid`. Tried with one browser on both sites: each site's form was accepted with the other's
  cookies present, and the stand-in received only its own.
- **Headers**: its pages may be framed by its own pages only, browsers are told not to guess content types, a
  result's page is never stored by caches or listed by search engines, and the block below takes salmobase's
  `Access-Control-Allow-Origin: *` off the portal's answers.
- **No request to other sites**: Bootstrap and htmx come with the package. salmobase's cookie-consent script and
  tag manager are not on the portal's pages.
- **Its own container**: it shares no database, no code and no session with salmobase's application. While it is
  stopped or being updated the site answers as before, and `/snp/` answers an error from Apache.
- **What it may use**: one list is scored at a time (others wait, at most ten), with two threads and 2 GB at the
  most; an upload is at most 300 MB and is deleted once scored; results go after 30 days. Its compose file caps
  the container at 4 GB and two cores, so that scoring cannot starve salmobase's own containers.

Navigation between salmobase's pages and the portal (a menu entry there, a way back here) is left for later (G,
2026-11-25): until then the portal is an address, `https://salmobase.org/snp/`.

## Step 0: look at the server

`snpportal/deploy/survey.sh` only reads; it creates, changes and starts nothing. From the clone on Orion:

```bash
ssh test.salmobase 'bash -s' < snpportal/deploy/survey.sh
ssh salmobase 'bash -s' < snpportal/deploy/survey.sh
```

What to take from it, into the table at the end of this file:

| From the survey | Needed for |
|---|---|
| The network of salmobase's containers (`docker network ls`; usually `<its folder's name>_default`) | `SALMOBASE_NETWORK` |
| The folder mounted at `/datafiles` in salmobase's `app` container | `DATAFILES` |
| Whether this user may use Docker (the docker group) | Everything below; if not, stop and tell G |
| The name of salmobase's `app` container, and its Apache's proxy lines as they are now | Where the block goes |
| Memory and cores | Whether the 4 GB ceiling suits the server |
| Whether the server reaches GitHub, PyPI and Docker Hub | Building there, or sending the image from elsewhere |
| What listens on 443 | What ends https, and may limit an upload's size |

Start on the test server (`test.salmobase`); repeat on the live one when G says.

## Install, once

The portal is deployed as a Docker image (G, 2026-11-26: "we'll only be deploying as a docker image. We should have
the docker uploaded into the same salmobase datafiles, then salmobase can use this docker to set it up on it's
server"). Each version's image is one file in the datafiles folder, `datasets/salmo-snp/docker/`, beside
`compose.yml` (the repository's `snpportal/deploy/compose.salmobase.yml`), `smoke.sh` (`tools/smoke.sh`),
`SHA256SUMS` and `latest.json`, which names the newest version. The release workflow builds the image for each
vX.Y.Z tag, and `snpportal/deploy/publish_image.sh` puts it there from Orion ("Working from Orion"). The server needs
no clone of the repository.

**1. The portal's own folder and container** (any folder this user owns; beside salmobase's is tidy). `D` is the
datafiles folder on the server (the survey says which):

```bash
mkdir -p ~/snp/data && cd ~/snp
D=<the datafiles folder>; V=<the version latest.json names, e.g. 0.2.0>
(cd "$D/datasets/salmo-snp/docker" && sha256sum -c --quiet SHA256SUMS && gunzip -c "salmo-snp-$V.docker.tar.gz" | docker load)
cp "$D/datasets/salmo-snp/docker/compose.yml" docker-compose.yml && cp "$D/datasets/salmo-snp/docker/smoke.sh" .
cat > .env <<EOF
SALMO_SNP_VERSION=$V
SALMOBASE_NETWORK=<salmobase's network, from the survey>
DATAFILES=$D
SITE=test.salmobase.org
PORTAL_USER=$(id -u):$(id -g)
EOF
docker compose up -d && docker compose logs --tail 20 snp
```

`SITE` is the name the site answers to: `salmobase.org` on the live server. The container runs as this user, so
`data/` needs no other owner. Its first lines:

```
release 2026-11-25 (Atlantic salmon): genome on the disk; 842 of 842 track files on the disk; public pool fits
release trout-2026-11-25 (Rainbow trout): genome on the disk; 771 of 771 track files on the disk; public pool fits
System check identified no issues (0 silenced).
```

Fewer track files than all, or `genome read from its address`: a path under the datafiles folder is not where the
table above says. The portal still works if the container reaches `https://salmobase.org`, more slowly. `no release
at ...`: the version names a release that is not in the releases folder (not published, or `DATAFILES` is not the
served folder). `PUBLIC POOL MISSING OR BUILT FOR OTHER WEIGHTS`: see "A new data release, or new tier rules".

**2. Check it before salmobase knows it.** The container also listens on the server's own 127.0.0.1:8090
(`PORTAL_PORT` in `.env` for another port):

```bash
bash smoke.sh http://127.0.0.1:8090 test.salmobase.org
```

**3. The block in salmobase's Apache file**, `server_config/apache2/salmobase.conf` in salmobase's repository,
inside its `<VirtualHost>`, after the `<Location /docs>` block and before `ProxyPass /datafiles !`:

```apache
	# the functional SNP portal (https://github.com/garethgillard/salmo-snp): its own container, on this network as `snp`
	<Location /snp>
		ProxyPass http://snp:8000/snp timeout=300 disablereuse=On
		ProxyPassReverse http://snp:8000/snp
		RequestHeader set X-Forwarded-Proto "https"
		LimitRequestBody 314572800
		Header onsuccess unset Access-Control-Allow-Origin
		Header onsuccess unset Access-Control-Allow-Headers
		Header onsuccess unset Access-Control-Expose-Headers
	</Location>
```

- It follows the file's own `/docs` block. `ProxyPreserveHost On` is already set for the whole host there, and the
  modules it needs (`proxy`, `proxy_http`, `headers`) are the ones salmobase's image turns on.
- `timeout=300` and `LimitRequestBody` are for uploads: lists of up to 300 MB, scored for up to five minutes before
  the page answers. `X-Forwarded-Proto` tells the portal that the visitor came by https, so that it marks its
  cookies for https only. `disablereuse=On` makes Apache look the name `snp` up for each request, so a new
  container of the portal is found at once. The three `Header` lines keep salmobase's JBrowse headers off the
  portal's answers.
- Two ways to put it in place, both only when G says, as both act on salmobase's own container:
  - **For good**: a merge request to salmobase's repository, which G accepts (G, 2026-11-25: "I have access to
    the repo and can accept the pull"). The change is ready as a file, `snpportal/deploy/salmobase-snp.patch` (the
    block with a comment; it applies to salmobase's `master` and `dev`). From a clone of salmobase with the right to
    push, the last command opens the merge request by itself:

    ```bash
    git fetch origin && git checkout -b snp-portal origin/master
    git apply <the salmo-snp clone>/snpportal/deploy/salmobase-snp.patch
    git commit -am "feat: send /snp to the functional SNP portal's container"
    git push -u origin snp-portal -o merge_request.create -o merge_request.target=master \
      -o merge_request.title="Send /snp to the functional SNP portal's container"
    ```

    What to say in it: the portal (https://github.com/garethgillard/salmo-snp) runs as a container of its own that
    joins this project's network as `snp`, from a compose file in its own repository, so `docker-compose.yml` here
    does not change; everything of it is under `/snp/` and no other address changes; where no such container runs
    (the devcontainer) Apache starts as before and `/snp` answers an error; its cookies do not meet this site's.
    Then, with the merge pulled into `src/salmobase` on the server, salmobase's `app` image is built again and its
    container replaced, the way its maintainers do it (in salmobase's compose folder: `docker compose build app &&
    docker compose up -d app`). The whole site is away for the seconds that takes.
  - **To try it on the test server first, without building anything**: put the edited file into the running
    container and let Apache read it again, which interrupts nothing. It lasts until that container is replaced.

    ```bash
    docker cp <app container>:/etc/apache2/sites-available/salmobase.conf salmobase.conf   # then add the block
    docker cp salmobase.conf <app container>:/etc/apache2/sites-available/salmobase.conf
    docker exec <app container> apachectl configtest && docker exec <app container> apachectl graceful
    ```

    Not tried on salmobase's own image: the block itself was tried on Apache 2.4.71 with salmobase's file.
- Apache starts with the block also while no container named `snp` exists (`/snp/` then answers an error), so the
  block and the portal can arrive in either order.

**4. Check it through salmobase**: on the server through salmobase's published port 80, then from anywhere.

```bash
bash smoke.sh http://127.0.0.1 test.salmobase.org
bash smoke.sh https://test.salmobase.org
```

Then upload a list of a few MB through the public address by hand (the Score page): what ends https in front of
salmobase is not known and may limit the size of a request.

What was tried, in a cloud session, with salmobase's Apache file and the block: `/snp` redirects to `/snp/`; the
smoke test passed for both species and an uploaded list was scored through Apache; `/snpfoo` and every other
address stayed salmobase's; the portal's container was replaced under another address on the network and `/snp/`
answered at once, with Apache left running; the container ran as an ordinary user with the datafiles folder read
only, and nothing in that folder changed.

## Check a deploy

`tools/smoke.sh` asks the health page, then scores every example of the Score page for each species through the job
queue, opens each result and deletes it:

```
health: ok; release 2026-11-25 (Ssal_v3.1); species {'atlantic_salmon': '2026-11-25', 'rainbow_trout': 'trout-2026-11-25'}; genome local; public pool fits; tracks {'salmobase.org': True, 'read from the disk': '842 of 842'}; predict {'models': ['chrombpnet_gill'], 'packages': True}
atlantic_salmon known_loci: scored in 17 s
...
smoke: ok
```

It ends with `smoke: ok` or says which example failed, and exits accordingly. `EXAMPLES=known_loci` scores only
that one. The second argument is the name the site answers to. The health page alone: `/snp/health/?tracks=1`;
`docker compose ps` in the portal's folder shows `healthy` once the image's own check of that page has passed.

## Update to a new version

Only when G says. Pull main on Orion first and read what changed in this file. Publish the new version's image
(`publish_image.sh`, "Working from Orion"), then in the portal's folder on the server:

```bash
cd ~/snp && D=<the datafiles folder>; V=<the new version>
(cd "$D/datasets/salmo-snp/docker" && sha256sum -c --quiet SHA256SUMS && gunzip -c "salmo-snp-$V.docker.tar.gz" | docker load)
cp "$D/datasets/salmo-snp/docker/compose.yml" docker-compose.yml && cp "$D/datasets/salmo-snp/docker/smoke.sh" .
sed -i "s/^SALMO_SNP_VERSION=.*/SALMO_SNP_VERSION=$V/" .env
docker compose up -d && docker compose logs --tail 20 snp
```

Then the smoke test. salmobase's own containers are not touched. To go back: `SALMO_SNP_VERSION` in `.env` to the
version before (its image is still loaded, and its file is still in the docker folder), then `docker compose up -d`.
Results and the secret key are in `data/` and survive both. `docker image prune` removes images no container uses.

To take the portal away: `docker compose down` in its folder, the block out of salmobase's Apache file, and the
folder removed. Nothing else on the server was changed by it.

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

Then `docker compose restart snp` on the server: a running portal may keep the old pool's numbers.

## Working from Orion

- Every command on the server is `ssh salmobase '<command>'` (or `ssh test.salmobase`) from a login node. A login
  node cuts a long connection (an rsync after about ten minutes), so start anything long detached and read its log:
  `ssh salmobase 'cd ~/snp && nohup docker compose up -d > up.log 2>&1 &'`, then `ssh salmobase 'tail -3 ~/snp/up.log'`.
- **Publishing a version's image** (before installing or updating it; only when G says): in a checkout of that
  version on Orion, on a login node, `MODE=dry bash snpportal/deploy/publish_image.sh <version>`, then `MODE=run`.
  It takes `salmo-snp-<version>.docker.tar.gz` from the GitHub Release of the tag `v<version>` (the release workflow
  builds it, about 300 MB), checks it, stages it in the share's `datasets/salmo-snp/docker/` with `compose.yml`,
  `smoke.sh`, `SHA256SUMS` and `latest.json`, and sends that folder to the server, checked there. Earlier versions
  stay, so a server can go back. Without a tag (to try a commit): `sh snpportal/deploy/image.sh build <version> <folder>`
  where Docker is, then `FILE=<folder>/salmo-snp-<version>.docker.tar.gz MODE=run bash snpportal/deploy/publish_image.sh
  <version>`. The server needs neither GitHub nor PyPI nor Docker Hub: everything comes from its datafiles folder.
- **Logs**: `docker compose logs snp`. They hold event names, a job's reference, counts and timings, never a SNP or
  a file name. Nothing else needs looking after: results delete themselves, and `free_gb` on the health page is the
  room left in the data folder.

## Another server, without Docker

Not salmobase's case; kept for a server where Apache runs on the machine itself. The same start script runs from a
virtual environment as a service of the user:

```bash
git clone https://github.com/garethgillard/salmo-snp.git ~/salmo-snp/code && cd ~/salmo-snp/code
python3.12 -m venv ~/salmo-snp/venv
~/salmo-snp/venv/bin/pip install --upgrade ./snpscore "./snpportal[chrombpnet]" gunicorn
mkdir -p ~/salmo-snp/data ~/.config/systemd/user
```

`~/.config/systemd/user/salmo-snp.service`:

```ini
[Unit]
Description=salmo-snp portal

[Service]
Environment=PATH=%h/salmo-snp/venv/bin:/usr/bin:/bin
Environment=SNPSCORE_SALMOBASE=<the datafiles folder>
Environment=SNPPORTAL_DATA=%h/salmo-snp/data
Environment=SNPPORTAL_BIND=127.0.0.1:8090
Environment=DJANGO_ALLOWED_HOSTS=<the site's name>
ExecStart=/bin/sh %h/salmo-snp/code/snpportal/deploy/server.sh
Restart=on-failure
MemoryMax=4G
CPUQuota=200%

[Install]
WantedBy=default.target
```

Then `systemctl --user daemon-reload && systemctl --user enable --now salmo-snp`, and in Apache the block above with
`http://127.0.0.1:8090/snp` in place of `http://snp:8000/snp`. The start script was tried this way on the mock,
started by hand; the unit file was not (no systemd in a cloud session), and a user service applies `MemoryMax` and
`CPUQuota` only where the system lets users set them.

## What is not known yet

Fill this in from the survey, and tell G what it means.

| | test.salmobase | salmobase |
|---|---|---|
| Cores and memory | | |
| salmobase's compose folder, and its network's name | | |
| The folder mounted at `/datafiles`, and whether both servers serve the same one | | |
| The user, its user and group numbers, and whether it may use Docker | | |
| The name of salmobase's `app` container | | |
| How salmobase's own containers are rebuilt, and by whom | | |
| What ends https in front of port 80, and the largest request it lets through | | |
| The port on 127.0.0.1 for the checks (8090 unless taken) | | |
| Reaches GitHub, PyPI, Docker Hub | | |

For G: the merge request with the block is G's to accept (above); who then replaces salmobase's `app` container on
the two servers, and which of salmobase's branches each server runs (`master` or `dev`: the merge request goes to
that one); whether the portal should carry salmobase's cookie-consent and tag-manager scripts (it
carries none); the menu entry on salmobase and the way back, later; and DECISIONS #67 and #68 (whether the portal
should take the newest published release by itself, and how the build chat hands back). Also open: a tagged version
for each deploy instead of a commit of main, and when the NREC demo is switched off.
