# Production integration acceptance

## Offline verification

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:KG_MYSQL_ENABLED='0'
$env:KG_NORM_MILVUS_ENABLED='0'
conda run -n env_agent python -m pytest kg_extract_build/tests -q
```

The current offline baseline is `328 passed, 1 skipped, 51 subtests passed`.
`test_production_full_audit.py` verifies that every task in the published task library receives an isolated execution record and is preserved in the draft report.

## Real-service probe

```powershell
$env:PYTHONIOENCODING='utf-8'
conda run -n env_agent python -m kg_extract_build.scripts.production_probe
```

The probe does not print credentials. It checks published normative releases, Neo4j read-only retrieval, and JSA availability. A stopped Neo4j or JSA service is reported as a degradation diagnostic.

## Task-count reconciliation

The current published task library contains 44 tasks: 27 deterministic, 6 offline completion, 1 JSA, 4 semantic compliance, and 6 semantic reasonableness. The production issue text says 42 tasks; acceptance follows the checked-in task library and therefore records 44 task executions until the specification is reconciled.

## Required live configuration

Set `KG_AUDIT_NORMATIVE_RELEASE_ID` to one of the published MySQL release IDs before starting the UI. Start MySQL, Milvus, Neo4j, JSA, and the selected provider, then run the probe and the gated live dashboard test.
