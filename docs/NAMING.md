# Naming and compatibility

This project is now **Shard Runner** (`shard-runner`), previously `ai-data-shard-lab`.
The rename changes the public repository and display name, not the experiment or its results.

## Current checkout

```sh
git clone https://github.com/kimzclandi/shard-runner.git
cd shard-runner
```

For an existing checkout, update its remote from the repository root:

```sh
git remote set-url origin https://github.com/kimzclandi/shard-runner.git
```

Renaming the local checkout directory is optional. Existing issue and PR numbers are retained.

## Compatibility and historical records

Python distribution/import names, command-line entry points, Go module paths and protocol
identifiers remain unchanged. Use the installation and run commands in the current README;
a public rename does not require a package or database migration.

Frozen protocols, manifests, source archives, measured outputs, dated reports and license
notices retain their original text and hashes. Old names in those records identify the
historical project and are not separate implementations. No experiment is rerun or rebranded
as a new result. New public navigation uses the current names.


[GitHub repository rename behavior](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)
