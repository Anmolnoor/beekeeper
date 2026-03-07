# Research Basis

This roadmap was built from a mix of **official standards**, **official architecture guides**, and a few **production papers**. Not every source is a formal white paper, but every source below is either a standard, a major production paper, or official operational guidance.

---

## Standards and frameworks

## [R1] NIST SP 800-218 — Secure Software Development Framework (SSDF) 1.1
What it contributed:
- use outcome-based secure development practices
- tie gaps to risk tolerance and resources
- build a maturity/action plan instead of vague “we should secure this” language

Why it matters here:
- the project needs evidence-based maturity and release gates, not optimistic claims

## [R2] NIST SP 800-218A — SSDF Community Profile for Generative AI and Dual-Use Foundation Models
What it contributed:
- AI/GenAI-specific secure development expectations
- extra emphasis on model/system development lifecycle concerns
- stronger framing for provenance, testing, and secure delivery of AI systems

Why it matters here:
- this platform is not only software infrastructure; it is AI-enabled execution infrastructure

## [R3] NIST AI RMF 1.0
What it contributed:
- governance, risk management, and trustworthiness framing
- practical structure for AI system risk management
- support for using a flexible but operationalizable risk model

Why it matters here:
- “governed agents” must be grounded in governance that actually changes system behavior

## [R4] NIST AI RMF Generative AI Profile (NIST AI 600-1)
What it contributed:
- emphasis on governance, content provenance, pre-deployment testing, and incident disclosure
- recognition that GenAI brings novel or amplified risks
- concrete risk-management lens for LLM-based systems

Why it matters here:
- policy, provenance, testing, and incident handling should be first-class design concerns

---

## Policy and authorization

## [R5] Open Policy Agent (OPA) / Rego
What it contributed:
- decouple policy decision-making from the application
- treat policy as code
- support explicit policy input/output contracts and versioning

Why it matters here:
- policy logic should not live as scattered `if` statements inside Queen or channel handlers

## [R6] Zanzibar: Google’s Consistent, Global Authorization System
What it contributed:
- idea of a uniform data model and configuration language for authorization
- support for reasoning about scalable, explainable authorization structures

Why it matters here:
- the platform needs better policy/authorization structure across org, hive, queen, user, tool, and resource scopes

---

## Durable execution and production workflow orchestration

## [R7] Temporal official documentation
Coverage used:
- task queues
- workers
- worker deployment/performance
- worker versioning
- production readiness checklist

What it contributed:
- durable execution model
- task queues and external workers
- persistence across worker failures
- long-running worker deployment discipline
- versioned rollout patterns

Why it matters here:
- it directly addresses the current mixing of orchestration and execution, and the weak recovery story

---

## Storage, eventing, and distributed systems patterns

## [R8] Azure Architecture guidance
Coverage used:
- event sourcing
- transactional outbox
- web-queue-worker
- multitenant architecture guidance

What it contributed:
- clean separation of write state, event history, and worker processing
- reliable message publication patterns
- storage/query tradeoff clarity
- practical multi-tenant architecture framing

Why it matters here:
- the current filesystem/event-store story needs explicit boundaries and reliable messaging

---

## Observability

## [R9] OpenTelemetry official docs
Coverage used:
- signals
- traces
- context propagation

What it contributed:
- unified traces, metrics, logs
- end-to-end correlation across boundaries
- distributed context propagation

Why it matters here:
- logging alone is not enough to operate a distributed agent platform

---

## Isolation and sandboxing

## [R10] gVisor docs and production guide
What it contributed:
- sandboxing containers from the host kernel and from each other
- defense-in-depth rationale
- relevance for multi-tenant and sensitive workloads

Why it matters here:
- policy checks are not sandboxing; the platform needs a real isolation story

## [R11] Firecracker microVM guidance
What it contributed:
- microVM-based isolation for secure multi-tenant container/function workloads
- practical strong isolation model with lighter footprint than traditional VMs

Why it matters here:
- generated or untrusted worker code should have a stronger isolation option than ordinary containers

---

## Security operations and verification

## [R12] OWASP guidance
Coverage used:
- Secrets Management Cheat Sheet
- Logging Cheat Sheet
- Microservices Security Cheat Sheet
- ASVS

What it contributed:
- centralized secrets management, least privilege, rotation
- security logging and correlation
- microservice correlation IDs and structured logging
- a concrete verification standard for application security controls

Why it matters here:
- the current project needs better defaults, better evidence, and better logging discipline

---

## Supply chain and release confidence

## [R13] SLSA levels
What it contributed:
- progressive maturity levels for provenance and build hardening
- a practical language for “what assurance level do we really have?”

Why it matters here:
- the project needs a way to talk honestly about build/release maturity, especially if worker forge becomes real

---

## Testing and feedback at scale

## [R14] Taming Google-Scale Continuous Testing
What it contributed:
- fast feedback matters
- test resources are finite
- prioritization and practical CI discipline are essential
- not every test path deserves the same cost model

Why it matters here:
- the platform needs a realistic testing strategy with golden paths, not only local/mock/unit optimism

---

## Research-based design conclusions used in the roadmap

1. **Policy must be externalized** enough to be versioned, reasoned about, and tested. (`[R5]`, `[R6]`)
2. **Execution must be durable and external** to the control-plane process. (`[R7]`, `[R8]`)
3. **Filesystem append-only logs are useful, but not a sufficient production substrate** for state. (`[R8]`)
4. **Observability must cross service and worker boundaries** through shared correlation data. (`[R9]`, `[R12]`)
5. **Governance without provenance, approval state, and testing is incomplete** for AI systems. (`[R2]`, `[R3]`, `[R4]`)
6. **Sandboxing must be real**, not just logical policy checks. (`[R10]`, `[R11]`)
7. **Release maturity should be described progressively**, not as a binary “ready/not ready.” (`[R1]`, `[R13]`)
8. **Test confidence should come from executable paths in clean environments**, not only from local assumptions. (`[R14]`, `[R12]`)
