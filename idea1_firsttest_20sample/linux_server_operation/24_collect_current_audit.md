# 24 — collect the current audit

Run this after the current 19 environment repair and 22/20 model attempts, including when one of those steps fails:

```bash
bash linux_server_operation/24_collect_current_audit.sh \
  --export-root /root/autodl-tmp/idea1_firsttest_20sample/exports_scope_v2_20261018T101136Z_wHG53v
```

The export-root argument is optional; without it, the collector selects the lexically latest `exports_scope_v2_*` directory under `DATA_ROOT`. The collector uses the standard library and only reads existing artifacts. It includes the selected export's summary and `_run/*.json`, its existing evidence ZIP, the latest step-19 environment report and model setup bundle, the newest 19/20/21/22 logs, the newest camera probe bundle, and each model run's manifest and predictions. It does not include model weights or caches, and it never starts inference, simulation, or installation.

The output is a uniquely named ZIP under `$DATA_ROOT/logs/`. Its `audit_manifest.json` records included-file hashes and sizes, missing expected items, environment and model-manifest status, and prediction byte/nonempty-line counts. The printed archive path is the file to return for review. This operation collects evidence; it does not establish that candidate labels or predictions are correct.
