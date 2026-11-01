# clustering-claim-audit

Version 0.1.0 audits documented grouping capability against Python source using static syntax inspection. It reads the root README.md and Markdown under a docs directory. Fenced examples are excluded; inline code is included. Source is never executed. The tool works offline and does not modify audited files.

Install and run with Python 3.9 or later:

```sh
python3 -m pip install clustering-claim-audit
clustering-claim-audit .
python3 -m clustering_claim_audit . --json
python3 -m clustering_claim_audit . --verbose --ignore vendor --fail-on MEDIUM
python3 -m clustering_claim_audit --version
```

The default failure threshold is HIGH. Test evidence alone produces MEDIUM. Exit status is 0 below the threshold, 2 for findings meeting the threshold, and 1 for usage or input errors. Repeat --ignore for additional relative path prefixes. JSON output includes status, findings, claim locations, and evidence paths. Verbose text output includes evidence paths.

Supported evidence consists of recognized estimator constructors from sklearn and hdbscan, plus hierarchy operations from scipy. Imports and aliases are resolved within each module; local definitions override imported names. Syntax errors provide no evidence. Tests are tracked separately. Symbolic links and source beneath fixtures, docs, and examples are excluded. Static inspection cannot prove runtime behavior, resolve dynamic imports, or establish whether an operation is reachable.

Finding identifiers:

```text
documented-clustering-claim-false
documented-no-clustering-claim-false
```

Development:

```sh
python3 -m unittest discover
python3 -m build
```

Distributed under the MIT license.
