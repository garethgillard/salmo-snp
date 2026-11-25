# The portal on the salmobase server: brief (2026-11-25)

This brief is for the chat that deploys the portal on the salmobase server: the chat on Orion over SSH, which also
builds and publishes the data releases ([ORION.md](ORION.md)). Nothing here has been run on the server yet. Every
command was tried in a cloud session on a mock of the server's folders made from the published releases. Read
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
docker run -d --name salmo-snp --restart unless-stopped -p 127.0.0.1:8090:8000 \
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

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload && systemctl --user enable --now salmo-snp
journalctl --user -u salmo-snp -n 20 --no-pager
```

The same script was tried this way in a cloud session on the mock (started by hand, as there is no systemd there).
The unit file itself has not been tried.

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

## Apache, once (whoever administers the server)

In salmobase's virtual host:

```apache
ProxyPass        /snp/ http://127.0.0.1:8090/snp/
ProxyPassReverse /snp/ http://127.0.0.1:8090/snp/
ProxyPreserveHost On
RequestHeader set X-Forwarded-Proto "https"
ProxyTimeout 300
LimitRequestBody 314572800
```

The last two are for uploads: lists of up to 300 MB, scored for up to five minutes before the page answers. Then
the button on salmobase that links to `/snp/`.

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
| Operating system, cores, memory | | |
| The datafiles folder's path | | |
| The user the portal runs as | | |
| Docker or Podman | | |
| Python 3.11 or newer | | |
| A service this user may keep running | | |
| Who edits Apache | | |
| The port (8090 unless taken) | | |
| Reaches GitHub, PyPI, Docker Hub | | |

Open, for G (DECISIONS #66 to #68): whether the portal should take the newest published release by itself instead
of the one its version names; a tagged version for each deploy instead of a commit of main; when the NREC demo is
switched off.
