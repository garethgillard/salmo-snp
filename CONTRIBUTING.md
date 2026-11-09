# Contributing to salmo-snp

salmo-snp belongs to the Norwegian University of Life Sciences (NMBU) and is maintained by Gareth Gillard. Its code is
under the [PolyForm Noncommercial 1.0.0](LICENSE) licence; collaborators are invited, and their work comes in through
pull requests.

## The agreement

Before your first pull request is merged, you accept the [Contributor License Agreement](CLA.md). You keep the
copyright in what you write; NMBU gets a permanent licence to use it and to license the project, with your work in
it, on any terms (including commercial licences). A check on each pull request asks you to sign once, by writing the
sentence it shows in a comment; it then remembers you. NMBU staff contributing as part of their job, and the
maintainer, don't need to sign.

## How to contribute

- Read AGENTS.md (and the AGENTS.md of the folder you change): the plan, the rules and which decisions are the
  maintainer's (biology: thresholds, weights, state definitions, trait mappings).
- Work on a branch and open a pull request against `main`; `bash tools/check.sh` runs what CI runs.
- Never commit breeder data (genotypes, GWAS results, array manifests), not even in tests or examples, and never
  `data/`, `release/` or results folders.
- Changes to the biology files (`.github/CODEOWNERS` lists them) need the maintainer's review.
- Keep it small: few files, little code, readable over clever; ask before adding a dependency.
