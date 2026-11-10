# Contributing to salmo-snp

salmo-snp belongs to the Norwegian University of Life Sciences (NMBU) and is maintained by Gareth Gillard. Its code is
under the [PolyForm Noncommercial 1.0.0](LICENSE) licence. Anyone may propose a change by pull request (from a fork);
invited collaborators may also push branches here.

## The agreement

Before your first pull request is merged, you accept the [Contributor License Agreement](CLA.md). You keep the
copyright in what you write; NMBU gets a permanent licence to use it and to license the project, with your work in
it, on any terms (including commercial licences). A check on each pull request asks you to sign once, by writing the
sentence it shows in a comment; it then remembers you. NMBU staff contributing as part of their job, and the
maintainer, don't need to sign (the maintainer adds NMBU colleagues to the check's allowlist).

- If your employer has rights in what you write (most employment contracts give them that), make sure it agrees
  before you accept, as the agreement asks you to confirm (CLA.md, section 4).
- The check matches each commit's author to a GitHub account: commit with an email address that is on your GitHub
  account (GitHub: Settings, Emails), or it can't tell that you signed.

## How to contribute

- Read AGENTS.md (and the AGENTS.md of the folder you change): the plan, the rules and which decisions are the
  maintainer's (biology: thresholds, weights, state definitions, trait mappings).
- Work on a branch and open a pull request against `main`; `bash tools/check.sh` runs what CI runs.
- Never commit breeder data (genotypes, GWAS results, array manifests), not even in tests or examples, and never
  `data/`, `release/` or results folders.
- Changes to the biology files (`.github/CODEOWNERS` lists them) need the maintainer's review.
- Keep it small: few files, little code, readable over clever; ask before adding a dependency.
