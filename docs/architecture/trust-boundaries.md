# Trust Boundaries

## Boundary 1: Client and Channel Ingress -> API/Control Plane

- Inbound data is untrusted until signature, freshness, and dedupe checks pass.
- Channel events must map to a normalized internal schema before orchestration.

## Boundary 2: Control Plane -> Execution Plane

- Control plane should admit, plan, and queue work.
- Execution plane should perform long-running actions and return durable results.
- Policy decisions and approvals must be verified before side effects.

## Boundary 3: Execution Plane -> External Tools/Providers

- Outbound operations should be mediated by policy/capability checks.
- Secrets should be fetched via scoped references, not ambient credentials.

## Boundary 4: Data Plane

- Authoritative state belongs in durable databases.
- Artifacts belong in object storage.
- Local filesystem is scratch/dev support and not source-of-truth state for production.
