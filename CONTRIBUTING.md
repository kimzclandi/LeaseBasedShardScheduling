# Contributing / 贡献指南

Start with the [README](README.md) installation instructions. This repository uses Python 3.12+ / standard library.
For bug reports, include the commit, environment, exact command and a small reproducible
input. Feature requests should state the problem, proposed behavior and acceptance check.
Chinese and English contributions are welcome.

## Local checks

Install the README development/check dependencies before running these commands from the
repository root. Use a new output directory if a command refuses an existing one.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/verify_evidence.py
python3 .github/scripts/check_docs.py
```

The [existing CI workflow](.github/workflows/ci.yml) records the full
check scope. Report commands actually run and failures; do not describe saved-output checks
as new model inference or training. Add a focused regression test for a behavioral fix.

## Pull requests

Fork the repository or use a topic branch. Keep one concrete change per PR, describe its
before/after behavior, and fill in the validation section. Avoid unrelated formatting.
Do not overwrite frozen protocols, input manifests, predictions, reports or failed runs.
Use a separate output directory for new experiments and record the input identity,
configuration and limitations. Never tune against a consumed holdout.

Do not include secrets, model weights, private data or third-party material without the
necessary rights. Attribution and data/model licenses remain separate from code licensing.
See the [community conduct policy](CODE_OF_CONDUCT.md) and
[maintenance guide](docs/MAINTAINING.md) for project structure and release checks.
