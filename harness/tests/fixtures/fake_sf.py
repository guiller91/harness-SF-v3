#!/usr/bin/env python3
"""`sf` de mentira para los tests de configuración: org list y org login web."""
import json
import sys

args = sys.argv[1:]
if args[:2] == ["org", "list"]:
    print(json.dumps({"status": 0, "result": {
        "nonScratchOrgs": [
            {"alias": "sit", "username": "dev@acme.sit", "instanceUrl": "https://acme--sit.sandbox.my.salesforce.com",
             "connectedStatus": "Connected", "isSandbox": True},
            {"alias": "prod", "username": "admin@acme.com", "instanceUrl": "https://acme.my.salesforce.com",
             "connectedStatus": "Connected"}],
        "scratchOrgs": [{"alias": "harness-dev", "username": "test-x@example.com", "isScratch": True,
                         "instanceUrl": "https://x.scratch.my.salesforce.com", "status": "Active",
                         "expirationDate": "2026-12-01"}]}}))
elif args[:3] == ["org", "login", "web"]:
    alias = args[args.index("--alias") + 1]
    print(json.dumps({"status": 0, "result": {"username": f"{alias}@acme.com"}}))
else:
    print(json.dumps({"status": 1, "message": "no soportado"}))
    sys.exit(1)
