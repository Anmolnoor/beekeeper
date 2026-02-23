# 07 — Extension Guide

## How to Add a Custom Worker

Custom workers let you extend the platform with new task types without modifying the core.

### Step 1: Create Your Worker Class

```python
# my_workers/summarizer.py
from beekeeper.contracts import TaskEnvelope, WorkerKind
from beekeeper.worker import BaseSpecialistWorker, WorkerContext
from pydantic import BaseModel

class SummaryOutput(BaseModel):
    summary: str
    word_count: int

class SummarizerWorker(BaseSpecialistWorker):
    worker_kind = WorkerKind.custom
    output_model = SummaryOutput

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> SummaryOutput:
        text = task.payload.get("text", "")
        # Call LLM or custom logic here...
        summary = f"Summary of {len(text)} chars"
        return SummaryOutput(summary=summary, word_count=len(summary.split()))
```

### Step 2: Register via Plugin

Create `.honeycomb/workers/plugins.json`:
```json
{
  "summarizer": "my_workers.summarizer:SummarizerWorker"
}
```

### Step 3: Register via Code

```python
from beekeeper.queen import QueenAgent, QueenConfig
from beekeeper.contracts import WorkerKind
from my_workers.summarizer import SummarizerWorker

config = QueenConfig(honeycomb_root=".honeycomb")
queen = QueenAgent(config)
# Pass extra_workers to WorkerRuntime (set in QueenConfig or override)
```

### Step 4: Route Intents to Your Worker

Override `_route_worker_kind()` or register the intent in your worker's skill profile.

---

## How to Add a Custom Guardrail

```python
from beekeeper.contracts import PolicyDecision, RuleProfile, TaskEnvelope
from dataclasses import dataclass

@dataclass
class ProfanityGuardrail:
    blocked_words: tuple[str, ...] = ("badword1", "badword2")

    def evaluate(
        self, task: TaskEnvelope, rule_profile: RuleProfile
    ) -> tuple[bool, str | None]:
        text = " ".join(str(v) for v in task.payload.values()).lower()
        for word in self.blocked_words:
            if word in text:
                return False, "profanity_detected"
        return True, None
```

Register it when building `GuardrailPolicyEngine`:
```python
from beekeeper.guardrails import GuardrailPolicyEngine, SchemaGuardrail, PIIGuardrail
from my_guardrails import ProfanityGuardrail

engine = GuardrailPolicyEngine([
    SchemaGuardrail(),
    PIIGuardrail(),
    ProfanityGuardrail(),
])
```

---

## How to Add a Custom Skill Profile

Skills are the "what can this worker do" profile. They can be defined in code or as Markdown files.

### In Code
```python
from beekeeper.contracts import SkillProfile

my_skill = SkillProfile(
    skill_profile_id="skill.summarizer",
    name="Summarizer Skill",
    description="Summarizes long documents",
    when_to_use="When the user asks to summarize or condense content",
    can_search_web=False,
    can_execute_code=False,
    capabilities=["text_summarization"],
    tool_allowlist=["summarize"],
    max_parallel_tools=1,
)
```

### As Markdown
Create a `.md` file and use `beekeeper.skill_loader.load_skills_from_md()` to parse it.

---

## How to Add a Custom Soul Profile

```python
from beekeeper.contracts import SoulProfile

formal_soul = SoulProfile(
    soul_profile_id="soul.formal",
    name="Formal Assistant",
    tone="assertive",           # neutral | concise | detailed | assertive
    risk_appetite="low",        # low | balanced | high
    verbosity="high",           # low | medium | high
    escalation_style="strict",  # strict | balanced | lenient
    traits={"language": "formal", "persona": "executive assistant"},
)
```

---

## How to Add a Custom LLM Provider

Implement the `LLMProvider` abstract class:

```python
from beekeeper.llm_provider import LLMProvider, LLMResponse

class MyCustomProvider(LLMProvider):
    def chat(
        self,
        prompt: str,
        system: str | None = None,
        messages: list[dict] | None = None,
        model_override: str | None = None,
    ) -> LLMResponse | None:
        # Call your custom LLM endpoint
        response_text = call_my_api(prompt, system)
        return LLMResponse(text=response_text, source="my_provider", model="my-model")
```

Build the `LLMRouter` manually:
```python
from beekeeper.llm_provider import LLMRouter
router = LLMRouter(providers=[MyCustomProvider(), fallback_provider])
```

---

## How to Define an Agent Blueprint Template

Templates allow reusable Queen/Worker shapes with fixed profile bundles.

```bash
# Export current defaults as templates
python -m beekeeper.migrate_blueprints

# Instantiate a template into a new Queen for a hive
beekeeper templates instantiate tpl_xxx --hive hive_yyy --name "Research Queen"
```

Or via API:
```bash
curl -X POST http://localhost:8787/templates/instantiate \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"template_id": "tpl_xxx", "hive_id": "hive_yyy", "name": "My Queen"}'
```

---

## How to Add a New Channel Integration

1. **Store credentials**:
   ```bash
   beekeeper channels set myplatform '{"myplatform_bot_token": "token123"}'
   ```

2. **Add webhook route** in `beekeeper_api/routes.py`:
   ```python
   @router.post("/webhooks/myplatform")
   async def myplatform_webhook(request: Request):
       # verify signature, parse message, call Queen
       body = await request.json()
       ...
   ```

3. **Add channel auth** in `channel_auth.py` for signature verification.

4. **Add allowlist support** in `channel_allowlist.py` if per-user access control is needed.

---

## How to Build New Workers (from docs/)

See `docs/BUILDING_NEW_WORKERS.md` for the full canonical guide including:
- Worker lifecycle hooks (`preflight`, `execute`, `validate`, `terminate`)
- Output model conventions
- Plugin registration
- Testing patterns
