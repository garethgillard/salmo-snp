"""The demo VM's deploy scripts on a mock of its folders. deploy/species.sh's cleanup rule (G, 2026-11-25): a release
the code no longer names is removed only when no job, Design panel or saved project kept there was made with it.
deploy/update.sh: the steps after the checkout are the new commit's own, and a commit the portal does not answer at
is taken back."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "species.sh"
UPDATE = SCRIPT.with_name("update.sh")


@pytest.mark.skipif(os.name == "nt", reason="a bash script of the Linux demo VM")
def test_cleanup_removes_only_unnamed_releases_nothing_was_made_with(tmp_path):
    root = tmp_path / "srv"
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").symlink_to(sys.executable)
    serve = root / "salmo-snp" / "snpportal" / "snpportal" / "serve.py"
    serve.parent.mkdir(parents=True)
    names = 'RELEASE = "2026-11-24"  # the default\nRELEASES = {"atlantic_salmon": RELEASE, "rainbow_trout": "trout-2026-11-24"}\n'
    serve.write_text(names)
    for v in ("2026-11-05", "2026-11-20", "trout-2026-11-13", "trout-2026-11-24"):
        (root / "releases" / v).mkdir(parents=True)
        (root / "releases" / v / "manifest.json").write_text(json.dumps({"version": v}))
    (root / "release").mkdir()
    (root / "release" / "manifest.json").write_text(json.dumps({"version": "2026-11-24"}))
    job = root / "results" / "0000" / "job.json"  # a result made with the release before
    job.parent.mkdir(parents=True)
    job.write_text(json.dumps({"release": "2026-11-20"}))
    project = root / "projects" / "mine" / "v1" / "meta.json"  # a saved project version on an older trout release
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps({"release": "trout-2026-11-13"}))

    def cleanup():
        out = subprocess.run(["bash", str(SCRIPT), "cleanup"], env={**os.environ, "SNPPORTAL_ROOT": str(root)},
                             capture_output=True, text=True)
        return out.stdout, sorted(p.name for p in (root / "releases").iterdir())

    said, left = cleanup()
    assert left == ["2026-11-20", "trout-2026-11-13", "trout-2026-11-24"]  # only the one nothing was made with went
    assert "release 2026-11-05 removed" in said and "release 2026-11-20 kept" in said
    job.unlink()  # the result expired, but a file that can't be read stops the look: nothing goes on a guess
    project.write_text("{not json")
    assert cleanup()[1] == ["2026-11-20", "trout-2026-11-13", "trout-2026-11-24"]
    serve.write_text("")  # nor when the names can't be read
    project.unlink()
    assert cleanup()[1] == ["2026-11-20", "trout-2026-11-13", "trout-2026-11-24"]
    serve.write_text(names)
    assert cleanup()[1] == ["trout-2026-11-24"]  # the named release stays, with the default one beside releases/
    assert (root / "release" / "manifest.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="a bash script of the Linux demo VM")
def test_update_runs_the_steps_of_the_commit_it_deploys(tmp_path):
    """A change to update.sh's own steps (a package more in its pip line) takes effect in the deploy that brings it:
    the script checks the commit out and runs that commit's steps. Until 2026-11-25 it took a second deploy."""
    root, origin, stubs = tmp_path / "srv", tmp_path / "origin", tmp_path / "bin"
    git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.org", "-c", "init.defaultBranch=main"]
    script = UPDATE.read_text()
    assert '-e "snpportal[chrombpnet]"\n' in script

    def commit(files):  # {path in the repository: text}; returns the commit
        for name, text in files.items():
            (origin / name).parent.mkdir(parents=True, exist_ok=True)
            (origin / name).write_text(text)
        subprocess.run([*git, "-C", str(origin), "add", "-A"], check=True)
        subprocess.run([*git, "-C", str(origin), "commit", "-q", "-m", "a change"], check=True)
        return subprocess.run([*git, "-C", str(origin), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    origin.mkdir()
    subprocess.run([*git, "init", "-q", str(origin)], check=True)
    commit({"snpportal/deploy/update.sh": script, "snpportal/deploy/species.sh": "exit 0\n", "snpportal/manage.py": ""})
    subprocess.run([*git, "clone", "-q", str(origin), str(root / "salmo-snp")], check=True)  # the VM's checkout
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").symlink_to(sys.executable)
    (root / "env").write_text("DJANGO_ALLOWED_HOSTS=demo.example,127.0.0.1\n")
    stubs.mkdir()
    for path, body in ((stubs / "sudo", "exit 0"), (stubs / "sleep", "exit 0"),  # the restart, and the wait after it
                       (stubs / "curl", f'[ -e "{root}/salmo-snp/broken" ] && echo 500 || echo 200'),  # the portal's answer
                       (root / "venv" / "bin" / "pip", f'echo "$@" >> "{root}/pip.log"')):
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def deploy(sha):
        env = {**os.environ, "SNPPORTAL_ROOT": str(root), "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path)}
        env.pop("SSH_ORIGINAL_COMMAND", None)
        out = subprocess.run(["bash", str(root / "salmo-snp" / "snpportal" / "deploy" / "update.sh"), sha], env=env,
                             capture_output=True, text=True)
        head = subprocess.run([*git, "-C", str(root / "salmo-snp"), "rev-parse", "HEAD"], capture_output=True, text=True)
        return out, head.stdout.strip()

    more = commit({"snpportal/deploy/update.sh": script.replace('-e "snpportal[chrombpnet]"\n', '-e "snpportal[chrombpnet]" one-more-package\n')})
    out, head = deploy(more)
    assert out.returncode == 0 and head == more and "deployed" in out.stdout, out.stderr
    assert "one-more-package" in (root / "pip.log").read_text().splitlines()[-1]  # the new commit's pip line, at once
    out, head = deploy(commit({"broken": ""}))  # a commit the portal does not answer at
    assert out.returncode == 1 and head == more and "back to" in out.stderr  # taken back, and the deploy fails
