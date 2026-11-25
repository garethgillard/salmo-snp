"""deploy/species.sh's cleanup rule (G, 2026-11-25) on a mock of the demo VM's folders: a release the code no longer
names is removed only when no job, Design panel or saved project kept there was made with it."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "species.sh"


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
