# V2: Coding Worker Contract

V2 defines the contract between Beekeeper and the coding worker.

## Detailed Plan

- `02_coding_worker_contract.md`

## V2 Goal

Beekeeper should know how to describe a coding task, receive worker events, handle approval requests, store artifacts, and understand final results without depending on FCLI's human terminal UI or internal module layout.

## V2 Scope

- Task input schema.
- Event schema.
- Approval request schema.
- Result schema.
- Artifact schema.
- Side-effect categories.
- Verification status vocabulary.
- Contract tests with sample JSON and NDJSON fixtures.

## V2 Exit Criteria

V2 is done when Beekeeper can validate example coding-worker task, event, approval, result, and artifact payloads without launching the worker.

