# HARA Skill Architecture

## 1. Design Goal

The goal of this skill system is not to generate a HARA table that merely looks complete. The goal is to replace a competent human HARA analyst for routine analysis work, while making the result more systematic, more traceable, and less dependent on individual reviewer habits.

The target quality bar is:

- No major hazardous event should be missed because a function, malfunction, operating mode, or risk object was not considered.
- No scenario should be accepted unless the malfunction is a necessary cause of the hazardous event.
- No S/E/C rating should be assigned without explicit scenario-based evidence.
- No ASIL should be produced by free-form judgment when it can be derived by a deterministic matrix.
- No safety goal should be disconnected from a hazardous event and its highest ASIL.
- Every result must be reviewable through traceability from item definition to safety goal.

The architecture therefore uses staged generation, independent review, deterministic validation, and a structured knowledge base. It should behave less like a single writer and more like an analysis team with specialist reviewers and checklists.

## 2. Core Design Principles

### 2.1 Split Generation From Judgment

HARA has multiple reasoning layers:

```text
item definition
-> function
-> malfunction
-> vehicle-level hazard
-> operational scenario
-> hazardous event
-> S/E/C
-> ASIL
-> safety goal
```

These layers must not be generated in one prompt. A single prompt tends to optimize for a coherent final table, not for correctness at each layer. The skill must preserve each intermediate artifact and make later stages depend only on validated upstream data.

### 2.2 Treat Review As Testing, Not Re-reading

Review agents must not simply answer whether the previous output is reasonable. They must run adversarial checks:

- Is the malfunction a necessary cause of the hazardous event?
- Is the scenario inside the function operating domain?
- Are vehicle motion, road geometry, speed, risk object position, and injury mechanism physically consistent?
- Is the scenario a duplicate with only weather, road name, or speed changed?
- Does the S/E/C evidence actually come from the scenario?
- Does the safety goal cover the highest-risk hazardous event?

Review outputs must be structured as pass/fail findings. Vague approvals are not valid review evidence.

### 2.3 Use Deterministic Tools Wherever Possible

The LLM should reason about ambiguous engineering content. It should not perform mechanical checks that tools can do more reliably.

Tool-owned checks should include:

- JSON schema validation
- required field coverage
- enum validation
- traceability integrity
- ASIL matrix calculation
- duplicate ID detection
- scenario count limits
- missing review coverage
- final export consistency

### 2.4 Use Knowledge Narrowly

Each stage should read only the knowledge needed for its task. Broad knowledge loading causes contamination between stages, especially when scenario generation sees ASIL guidance too early and starts constructing scenarios to reach high ASIL.

Knowledge routing is part of the architecture, not an implementation detail.

## 3. Top-Level Skill Layout

```text
skills/
  hara-orchestrator/
  hara-item-definition/
  hara-function-malfunction/
  hara-hazard-identification/
  hara-scenario-generation/
  hara-scenario-review/
  hara-sec-rating/
  hara-sec-review/
  hara-safety-goal/
  hara-final-review/
  hara-export/

knowledge-base/
  hara/
    standards/
    taxonomy/
    rules/
    function-patterns/
    hazard-mechanisms/
    sec/
    anti-patterns/
    examples/

schemas/
  hara_item.schema.json
  hara_function.schema.json
  hara_malfunction.schema.json
  hara_hazard.schema.json
  hara_scenario.schema.json
  hara_sec.schema.json
  hara_safety_goal.schema.json
  hara_final.schema.json

tools/
  validate_schema.py
  route_knowledge.py
  apply_asil_matrix.py
  check_traceability.py
  check_scenario_consistency.py
  detect_duplicate_scenarios.py
  export_hara_excel.py
```

## 4. Workflow Architecture

### Stage 0: Item Definition

Purpose: define the analysis object before any risk reasoning.

Inputs:

- Product or system description
- Functional description
- Boundaries and interfaces
- Vehicle context
- Known operating modes
- Assumptions and exclusions

Outputs:

- item boundary
- intended functions
- operating modes
- user/driver role
- external actors
- interfaces
- environmental and vehicle preconditions
- explicit assumptions
- out-of-scope items

Quality gates:

- Every function must belong to the item scope.
- Every operating mode must be traceable to source text or declared assumption.
- Exclusions must be explicit, not implicit.

### Stage 1: Function and Malfunction Analysis

Purpose: derive credible malfunctioning behaviors for each function.

Malfunction taxonomy:

- loss of function
- unintended activation
- wrong timing
- delayed response
- wrong magnitude
- wrong direction
- stuck output
- intermittent output
- misleading status or warning
- missing indication or warning

Outputs:

- function ID
- normal behavior
- malfunction ID
- malfunction description
- affected vehicle behavior
- preconditions
- operating-domain relevance
- initial safety relevance

Quality gates:

- Each malfunction must be tied to a normal expected function.
- Each malfunction must describe behavior, not root cause.
- Duplicates must be merged or justified.
- Non-safety malfunctions may remain but must be marked as no-hazard candidates.

### Stage 2: Vehicle-Level Hazard Identification

Purpose: map malfunctions to vehicle-level hazards before generating scenarios.

Outputs:

- malfunction ID
- vehicle-level hazard
- hazardous vehicle state
- risk mechanism summary
- no-hazard rationale if applicable

Quality gates:

- Hazard must be at vehicle level, not component level.
- Hazard must be caused by malfunctioning behavior.
- Ordinary road risk must not be confused with item malfunction risk.
- No-hazard decisions require explicit rationale.

### Stage 3A: Scenario Generation

Purpose: create operational scenarios and hazardous events for each vehicle-level hazard.

This is the most important generation stage. It must not directly enumerate road, weather, and speed combinations. It must generate scenarios through a risk mechanism model:

```text
malfunction
-> abnormal vehicle behavior
-> required physical/operational conditions
-> risk object in dangerous path
-> injury mechanism
-> hazardous event
```

Required intermediate reasoning:

- abnormal vehicle behavior
- necessary physical conditions
- risk object and position
- dangerous path
- injury mechanism
- operating-domain check
- counterfactual check

Counterfactual check:

```text
If the malfunction is removed, does the same hazardous event still occur?
```

If yes, the scenario is invalid or must be rewritten.

Scenario archetypes:

- highest plausible severity path
- high exposure path
- low controllability path
- boundary operating-domain path
- common real-world path
- low-risk comparison path
- invalid or excluded path, recorded as analysis rationale but not used for SEC

Outputs:

- scenario ID
- linked malfunction ID
- linked hazard ID
- road type
- road geometry
- road surface
- environment
- vehicle state
- speed range
- traffic or risk object
- driver state
- additional conditions
- hazardous event
- scenario reasoning

Quality gates:

- Scenario must be physically possible.
- Scenario must be within operating domain, unless it is an unintended activation outside the expected domain.
- Risk object must be in the vehicle's dangerous path.
- Weather, road surface, or traffic density must not replace malfunction causality.
- Similar scenarios must differ by a meaningful risk mechanism, not just enum values.

### Stage 3R: Scenario Review

Purpose: reject weak or artificial hazardous events before SEC rating.

Review mode:

- Independent context
- No access to generator's free-form deliberation
- Access only to item definition, malfunction, hazard, scenario, and review rules
- Structured pass/fail checklist

Required checks:

- fault necessity
- operating-domain validity
- physical consistency
- vehicle motion consistency
- risk object position
- scenario uniqueness
- hazardous event wording
- excluded anti-pattern match

Outputs:

- per-scenario review result
- issue type
- required fix
- reviewer confidence
- accepted/rejected status

Gate rule:

- SEC rating cannot run on rejected scenarios.

### Stage 4: S/E/C Rating

Purpose: rate each accepted hazardous event.

S, E, and C should be evaluated independently. The system should avoid one agent assigning all three at once because S/E/C can contaminate each other.

Severity evaluator:

- Focuses on plausible injury outcome.
- Uses collision energy, vulnerable road users, occupant exposure, and injury mechanism.
- Does not consider probability or controllability.

Exposure evaluator:

- Focuses on frequency of the operational situation.
- Uses operating domain, common traffic situations, and vehicle use assumptions.
- Does not consider severity.

Controllability evaluator:

- Focuses on whether a typical driver or involved road user can avoid harm.
- Uses detectability, time to react, available maneuver space, vehicle speed, driver in-loop state, and surprise level.
- Does not modify severity.

Outputs:

- S value and rationale
- E value and rationale
- C value and rationale
- evidence references
- uncertainty notes

Quality gates:

- Each rating must cite scenario facts.
- Rating rationale must not introduce new scenario conditions.
- If evidence is insufficient, the output must mark uncertainty instead of guessing.

### Stage 5: ASIL Derivation

Purpose: derive ASIL deterministically from S/E/C.

ASIL must be produced by a matrix tool, not free-form LLM judgment.

Outputs:

- S/E/C
- ASIL or QM
- matrix trace

Quality gates:

- No manual override unless explicitly recorded with reviewer approval.
- Every ASIL must map to exactly one scenario and hazardous event.

### Stage 6: Safety Goal Generation

Purpose: derive vehicle-level safety goals from hazardous events and ASIL.

Rules:

- Safety goals must be vehicle-level.
- Safety goals must avoid implementation-specific design.
- Similar hazardous events may be grouped only if the same safety intent covers them.
- The safety goal inherits the highest ASIL among covered hazardous events.

Outputs:

- safety goal ID
- safety goal statement
- covered hazardous events
- inherited ASIL
- rationale
- safe state concept, if applicable

Quality gates:

- Every ASIL-relevant hazardous event must be covered.
- No safety goal may cover unrelated hazards just for consolidation.
- Safety goal wording must describe the unsafe outcome to prevent, not a technical mechanism.

### Stage 7: Final Review

Purpose: perform cross-stage consistency review.

Checks:

- item-function traceability
- function-malfunction traceability
- malfunction-hazard traceability
- hazard-scenario traceability
- scenario-SEC consistency
- SEC-ASIL matrix consistency
- hazardous event-safety goal coverage
- duplicate or conflicting safety goals
- assumptions and evidence gaps

Outputs:

- final acceptance status
- blocking findings
- non-blocking warnings
- residual assumptions
- recommended human review points

Gate rule:

- Final export is blocked if traceability is broken, ASIL mapping is invalid, or any ASIL-relevant hazardous event lacks safety goal coverage.

## 5. Knowledge Base Architecture

The knowledge base should be designed for retrieval and judgment, not for passive reading.

### 5.1 Standards Layer

Purpose: provide process-level definitions and boundaries.

Examples:

- ISO 26262 concept phase summary
- HARA workflow
- item definition expectations
- safety goal principles

Usage:

- Read by orchestrator and final review.
- Not normally read by scenario generation.

### 5.2 Taxonomy Layer

Purpose: constrain language and output fields.

Examples:

- malfunction taxonomy
- road type enum
- road geometry enum
- vehicle state enum
- risk object enum
- operating mode enum

Usage:

- Read by generation stages.
- Validated by tools.

### 5.3 Rule Layer

Purpose: provide testable engineering rules.

Good rule format:

```text
Rule VD-001: Unintended vehicle movement requires a longitudinal force source.
Applicable to: parking, low-speed hold, brake hold, creep control
Invalid pattern: weather or low friction as the sole cause of movement
Required evidence: slope, drive torque, external force, or transmission state
Review action: reject or require rewrite
```

Rules should be written as checks, not essays.

### 5.4 Function Pattern Layer

Purpose: provide common malfunction and hazard mechanisms by function family.

Function families:

- braking
- steering
- propulsion
- parking brake
- gear selection
- lighting
- HMI and warning
- door and lock
- charging or energy management
- ADAS and automation
- thermal management

Each function pattern should include:

- typical functions
- typical malfunctions
- typical vehicle hazards
- required scenario conditions
- invalid scenario patterns
- recommended risk objects

### 5.5 Hazard Mechanism Layer

Purpose: encode reusable causal mechanisms.

Examples:

- unintended acceleration
- unintended deceleration
- loss of braking
- insufficient braking
- unintended steering
- loss of steering assist
- unintended vehicle movement after parking
- missing warning leading to delayed driver response
- misleading indication causing wrong driver decision

Each mechanism should include:

- abnormal vehicle behavior
- possible injury paths
- required physical conditions
- relevant vehicle states
- relevant risk objects
- common invalid assumptions

### 5.6 SEC Layer

Purpose: support S/E/C rating.

Files:

- severity guide
- exposure guide
- controllability guide
- ASIL matrix

SEC knowledge must not be read by scenario generation. It is only for rating and review.

### 5.7 Anti-Pattern Layer

Purpose: make the system better than a generic analyst by systematically catching known mistakes.

Anti-pattern examples:

- weather-only causality
- low-friction-only rollback
- pedestrian not in movement path
- front vehicle described but oncoming occupant selected as injured party
- parked vehicle with high speed
- highway scenario for a function only active in parking
- scenario duplicated by changing only weather
- safety goal written as component design
- controllability lowered without surprise, time, or space evidence

Anti-patterns should be machine-readable where possible:

```json
{
  "id": "AP-PARK-001",
  "name": "Weather-only rollback",
  "applies_to": ["parking_brake", "hold_control"],
  "invalid_pattern": "Vehicle rolls because of rain, snow, ice, fog, or night without slope, drive torque, or external force.",
  "required_fix": "Add a valid longitudinal force source or reject the scenario.",
  "review_severity": "blocking"
}
```

## 6. Review Architecture

### 6.1 Independent Review Context

Reviewer agents must not share the generation context. They receive:

- upstream validated JSON
- generated artifact
- narrow review rules
- relevant anti-patterns

They should not receive:

- generator's hidden reasoning
- broad unrelated knowledge
- downstream ASIL expectations

### 6.2 Specialist Reviewers

For high-quality HARA, one generic review is not enough. Use specialist reviews:

- operating domain reviewer
- vehicle dynamics reviewer
- scenario uniqueness reviewer
- S/E/C evidence reviewer
- safety goal coverage reviewer

Each reviewer has a narrow checklist and must produce structured findings.

### 6.3 Review Output Contract

Each review finding should include:

```json
{
  "artifact_id": "...",
  "check_id": "...",
  "status": "pass|fail|warning|not_applicable",
  "finding": "...",
  "evidence": "...",
  "required_action": "accept|revise|reject|needs_human_decision",
  "confidence": "high|medium|low"
}
```

## 7. Quality Metrics

The skill should measure its own analysis quality.

Coverage metrics:

- functions analyzed
- operating modes covered
- malfunctions per function
- hazards per malfunction
- scenarios per hazard
- risk objects covered
- scenario archetypes covered
- ASIL-relevant hazardous events covered by safety goals

Quality metrics:

- rejected scenario rate
- duplicate scenario rate
- anti-pattern hit rate
- review finding closure rate
- unresolved uncertainty count
- ASIL distribution
- safety goal consolidation ratio

These metrics help identify whether the system is too shallow, too repetitive, or too aggressive.

## 8. How This Can Beat Ordinary Human Analysis

The skill can exceed ordinary manual analysis in specific ways:

- It can force complete traceability for every row.
- It can systematically apply the same S/E/C rules across all scenarios.
- It can remember anti-patterns and apply them consistently.
- It can generate broader scenario coverage than a time-limited human workshop.
- It can preserve rejected scenarios and rationale, which improves auditability.
- It can automatically detect duplicate or weak scenarios.
- It can run multiple specialist reviews on every scenario, not just a sample.

However, it should be honest about uncertainty. When source data is insufficient, the skill should record assumptions and request confirmation rather than inventing hidden operating conditions.

## 9. Required Human Interaction Points

The goal is to replace routine human analysis, but not to hide assumptions. Human input is still required when:

- item boundary is ambiguous
- operating domain is missing
- vehicle architecture affects hazard plausibility
- exposure depends on market, vehicle class, or use case
- controllability depends on HMI timing or driver warning design
- safety goal grouping has project-level implications

The skill should minimize these interruptions by making conservative assumptions explicit, but it must not fabricate project-specific facts.

## 10. Minimum Viable Implementation

The first usable version should include:

1. Item definition extraction
2. Function and malfunction generation
3. Vehicle hazard mapping
4. Scenario generation through hazard mechanism
5. Scenario review with anti-pattern checks
6. Independent S/E/C rating
7. Deterministic ASIL matrix
8. Safety goal generation
9. Traceability and schema validation
10. Excel export

Do not start with a single end-to-end generator. Start with the traceable pipeline and improve knowledge quality over time.

## 11. Non-Negotiable Gates

The following gates should block downstream processing:

- Item definition missing functional boundary
- Malfunction not linked to a function
- Hazard not linked to malfunction
- Scenario lacks malfunction necessity
- Scenario violates operating domain without explanation
- Scenario has physical inconsistency
- Scenario is rejected by review
- S/E/C rationale lacks scenario evidence
- ASIL does not match matrix
- ASIL-relevant hazardous event lacks safety goal
- Final traceability is broken

## 12. Final Architecture Summary

The architecture should be a safety analysis pipeline:

```text
orchestrator
  -> item definition
  -> function and malfunction analysis
  -> vehicle hazard identification
  -> hazard mechanism planning
  -> scenario generation
  -> scenario review
  -> independent S/E/C rating
  -> deterministic ASIL derivation
  -> safety goal generation
  -> final consistency review
  -> export
```

The system should not try to imitate one human analyst writing a table. It should imitate a disciplined HARA workshop with separate authors, reviewers, checklists, tools, and an audit trail.

