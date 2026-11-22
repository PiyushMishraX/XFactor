# X FACTOR — AI DEVELOPMENT PROMPT PACK

## MASTER INSTRUCTIONS (USE BEFORE EVERY STEP)

You are developing X FACTOR, an Agentic AI-powered Supply Chain Resilience Platform for the SAP Resilient Supply Chains Hackathon.

### Core architecture

The system consists of:
- LangGraph Supervisor — central orchestration and decision-making.
- Agent 1 — Disruption Sensing Agent.
- Agent 2 — Scenario Planning Agent.
- Agent 3 — Rerouting & Logistics Agent.
- Agent 4 — Inventory Rebalancing Agent.
- Agent 5 — Compliance & Audit Agent.
- Gemini API — LLM reasoning.
- Python tools — deterministic calculations and external API operations.
- FastAPI — backend.
- PostgreSQL — persistent application data and workflow checkpointing.
- SAP connectors — enterprise integration.
- React — frontend.

### Mandatory development rules

1. Inspect the existing project before modifying anything.
2. Never rebuild working components unnecessarily.
3. Follow the established project architecture.
4. Implement only the features requested in the current step.
5. Do not create fake agent collaboration. All handoffs must use actual LangGraph state and execution.
6. Use Pydantic models for structured agent inputs and outputs.
7. Keep deterministic calculations separate from LLM reasoning.
8. Never allow an LLM to invent financial calculations, inventory quantities, route distances or compliance results.
9. Use environment variables for API keys and credentials.
10. Handle API failures, invalid responses, timeouts and retries.
11. Add tests for every major component.
12. Use mock data only when external services or SAP credentials are unavailable, and clearly identify simulated results.
13. Never expose API keys in frontend code.
14. Do not implement unauthorized real-world operational actions.
15. Keep code modular, readable and beginner-friendly.
16. Do not remove existing functionality without a technical reason.
17. Update README.md with new setup instructions and completed functionality after each major phase.

At the end of every step:
- Summarize files created or modified.
- Explain what was implemented.
- List installation commands.
- List environment variables required.
- Provide exact commands to run and test the implementation.
- Identify incomplete functionality.
- Do not proceed to the next step automatically.

---

# STEP 0 — PROJECT INITIALIZATION AND ARCHITECTURE

**Prompt:**

Inspect the current project directory and initialize the X FACTOR project according to the master architecture.

Create a modular Python FastAPI backend and React + Vite frontend.

### Backend structure

backend/
- app/
  - main.py
  - api/
  - agents/
  - orchestration/
  - tools/
  - integrations/
  - models/
  - schemas/
  - services/
  - database/
  - config/
  - utils/
- tests/
- requirements.txt
- .env.example

### Frontend structure

frontend/
- src/
  - components/
  - pages/
  - services/
  - hooks/
  - layouts/
  - assets/

### Requirements

1. Configure FastAPI.
2. Configure React and Vite.
3. Configure PostgreSQL connection.
4. Configure Pydantic settings and environment variables.
5. Add a health-check endpoint.
6. Configure CORS.
7. Add basic logging and error handling.
8. Create a clean README.
9. Add .gitignore.
10. Create a requirements file with compatible dependencies.

Prepare configuration placeholders for Gemini, LangGraph and SAP integration.

Do not implement any AI agents yet.

Do not add unnecessary features or packages.

**Expected result:** Both frontend and backend run independently, and the frontend can successfully communicate with the backend.

---

# STEP 1 — GEMINI INTEGRATION AND DISRUPTION SENSING AGENT

**Prompt:**

Implement the first functional AI agent: Disruption Sensing Agent.

Use Google Gemini API with LangGraph-compatible architecture.

### Agent responsibilities

1. Analyze incoming disruption information.
2. Identify disruption type.
3. Identify affected geographic locations.
4. Determine potential supply-chain impact.
5. Identify potentially affected shipments and suppliers using provided database information.
6. Estimate disruption severity based on available evidence.
7. Recommend the next investigation or recovery action.

### Supported disruption categories

- Maritime security threats.
- Severe weather.
- Geopolitical developments.
- Tariff changes.
- Port congestion.
- Supplier failures.
- Transportation delays.
- Infrastructure disruptions.

### Implementation requirements

Create:
- disruption_sensing.py
- disruption_schemas.py
- gemini_service.py
- relevant unit tests.

Use structured Pydantic outputs.

Expected response format:

{
  "event_id": "EV001",
  "disruption_type": "Maritime",
  "description": "Shipping disruption in the Red Sea",
  "location": "Red Sea",
  "severity": "Critical",
  "risk_score": 92,
  "affected_shipments": ["SH001", "SH002"],
  "affected_suppliers": [],
  "potential_impact": [],
  "recommended_next_action": "Evaluate alternative shipping routes",
  "confidence": 0.94,
  "evidence": []
}

These values are illustrative. Do not hardcode them.

### Important rules

- Risk scores must use a deterministic scoring function based on available evidence.
- The LLM can interpret unstructured information but cannot invent shipment records.
- Validate shipment references against PostgreSQL.
- Include source information and timestamps when available.
- Handle missing or contradictory information.
- Do not execute operational actions.

### Testing

Test the agent using:
1. A maritime disruption.
2. A severe weather event.
3. A supplier failure.
4. An irrelevant news article.
5. An incomplete disruption report.

**Expected result:** A working Disruption Sensing Agent that returns validated structured information.

---

# STEP 2 — EXTERNAL TOOLS AND DETERMINISTIC BUSINESS LOGIC

**Prompt:**

Develop the complete tools and business logic layer for X FACTOR.

Do not build additional AI agents in this step.

Create two clearly separated modules.

## A. External and internal tools

Implement modular connectors for:

1. Weather API.
2. News API.
3. Maritime Alerts API.
4. Port Congestion API.
5. Tariff Data API.
6. Supplier API.
7. Carrier API.
8. Shipment Tracking API.
9. Mapping API.
10. SAP Connector interface.

Use configurable API credentials and timeouts.

If an API requires paid access or credentials that are unavailable, implement a mock adapter with realistic sample data.

Do not pretend mock data is live information.

## B. Deterministic business logic

Implement independent Python services for:

1. Risk Scoring Engine.
2. Cost Calculation Engine.
3. Route Optimization Engine.
4. Lead-Time Estimation Engine.
5. Inventory Calculation Engine.
6. Safety Stock Calculation Engine.
7. Supplier Ranking Engine.
8. Compliance Rules Engine.
9. Budget Validation Engine.
10. Approval Management Engine.

### Important implementation requirements

- Use actual formulas and deterministic calculations.
- Validate inputs.
- Return structured outputs.
- Add unit tests.
- Document assumptions.
- Avoid placing calculations inside LLM prompts.
- Keep each tool independently reusable by multiple agents.

### Example tool interface

calculate_route_cost(route, carrier, shipment)
calculate_delivery_time(route, carrier)
calculate_inventory_shortage(product, warehouse)
calculate_safety_stock(demand, buffer_days)
calculate_risk(event, shipment)
validate_budget(proposed_cost, available_budget)
validate_compliance(proposal, applicable_rules)

For route optimization, compare only routes supported by available route data.

For supplier ranking, use configurable weighted criteria such as reliability, price, capacity and lead time.

For compliance, return specific rule violations rather than allowing the LLM to declare a proposal compliant without deterministic validation.

**Expected result:** A tested, reusable business logic and API tools layer accessible through Python functions.

---

# STEP 3 — BUILD THE REMAINING FOUR AI AGENTS

**Prompt:**

Implement the remaining four specialized AI agents for X FACTOR.

The Disruption Sensing Agent already exists. Preserve it.

Use Google Gemini API, Pydantic and the existing business logic tools.

Each agent must have a distinct responsibility and structured input/output.

## AGENT 2 — SCENARIO PLANNING AGENT

Responsibilities:

1. Receive disruption details and affected supply-chain information.
2. Generate multiple recovery strategies.
3. Request route and logistics analysis.
4. Request inventory impact analysis.
5. Compare recovery alternatives.
6. Evaluate financial impact, delivery time and risk.
7. Rank feasible scenarios.
8. Explain why the recommended scenario is preferable.

Generate at least three alternatives when sufficient data exists.

Example:

- Continue with existing route.
- Reroute through an alternative maritime route.
- Use an alternative carrier or supplier.

Do not invent feasibility or cost data.

## AGENT 3 — REROUTING & LOGISTICS AGENT

Responsibilities:

1. Identify alternative transportation routes.
2. Evaluate available carriers.
3. Calculate transportation costs.
4. Estimate delivery time.
5. Evaluate route-related risks.
6. Compare logistics alternatives.
7. Return ranked feasible options.

Use Mapping API and deterministic route/cost calculation tools.

## AGENT 4 — INVENTORY REBALANCING AGENT

Responsibilities:

1. Inspect available inventory across warehouses.
2. Identify shortages.
3. Calculate safety stock requirements.
4. Identify alternative warehouses.
5. Evaluate stock redistribution.
6. Recommend inventory transfers.
7. Estimate the impact on product availability.

Never recommend transferring inventory that is unavailable or already committed.

## AGENT 5 — COMPLIANCE & AUDIT AGENT

Responsibilities:

1. Validate proposed recovery strategies.
2. Check regulatory restrictions.
3. Validate budget requirements.
4. Check operational policies.
5. Identify approval requirements.
6. Reject proposals violating mandatory rules.
7. Generate structured audit evidence.

The agent must use deterministic compliance and budget tools.

The LLM may explain results but cannot override failed validation.

### Common requirements for all four agents

- Create independent agent modules.
- Define Pydantic input/output schemas.
- Implement tool access.
- Use Gemini for reasoning.
- Return structured JSON.
- Handle missing information.
- Add logging.
- Add unit tests.
- Include confidence and evidence where appropriate.

Do not implement the central supervisor yet.

**Expected result:** All five specialized agents work independently and can be tested separately.

---

# STEP 4 — LANGGRAPH SUPERVISOR AND ORCHESTRATION

**Prompt:**

Implement the central LangGraph Supervisor for X FACTOR.

This is the most important part of the system.

The five specialized agents already exist. Connect them through a central supervisor using actual LangGraph nodes, state and conditional edges.

### Supervisor responsibilities

1. Receive a disruption event.
2. Invoke the Disruption Sensing Agent.
3. Inspect the returned disruption information.
4. Determine which agents are required.
5. Delegate tasks to appropriate agents.
6. Maintain shared workflow state.
7. Collect structured agent outputs.
8. Identify missing information.
9. Request additional analysis when needed.
10. Route results to the Compliance & Audit Agent.
11. Determine the next action.
12. Produce a final recovery recommendation.

### Required LangGraph components

- TypedDict or Pydantic-based workflow state.
- Five agent nodes.
- Supervisor node.
- Conditional routing.
- Shared state.
- Error-handling nodes.
- Workflow checkpointing.
- PostgreSQL-backed persistent checkpoints.

### Workflow requirements

The supervisor must not blindly execute every agent in a fixed sequence.

It should dynamically decide whether:
- Logistics analysis is required.
- Inventory analysis is required.
- Additional scenarios are required.
- A scenario needs revision.
- Compliance validation is required.
- The workflow can proceed to approval.

The supervisor should use validated structured results rather than relying on conversational memory.

### Execution requirements

Implement:
- Initial workflow invocation.
- State updates.
- Conditional agent routing.
- Retry handling.
- Workflow interruption.
- Resume from checkpoint.

Create a clear graph visualization or Mermaid workflow documenting the implementation.

### Testing

Test:
1. Normal disruption.
2. Disruption affecting multiple shipments.
3. Missing route information.
4. No feasible recovery scenario.
5. Agent failure.
6. Invalid agent output.

**Expected result:** A working LangGraph Supervisor coordinating all five agents through shared state and conditional execution.

---

# STEP 5 — MULTI-AGENT COLLABORATION AND AUTONOMOUS REPLANNING

**Prompt:**

Upgrade X FACTOR from a basic sequential multi-agent workflow into a coordinated agentic decision-making system.

Preserve the existing LangGraph architecture.

Implement genuine collaboration between the five specialized agents.

### Required capabilities

1. Dynamic task delegation.
2. Structured inter-agent communication.
3. Shared workflow state.
4. Agent result evaluation.
5. Feedback loops.
6. Conditional replanning.
7. Tool selection.
8. Failure recovery.
9. Scenario comparison.
10. Bounded autonomous iteration.

### Example collaboration scenario

A Red Sea disruption affects a pharmaceutical shipment.

1. Disruption Sensing identifies the affected shipment.
2. Supervisor delegates recovery analysis.
3. Scenario Planning requests logistics and inventory analysis.
4. Logistics Agent discovers that the alternative route increases transportation costs.
5. Inventory Agent discovers that another warehouse can supply part of the required inventory.
6. Scenario Planning incorporates both findings and generates an improved recovery strategy.
7. Compliance Agent discovers that one proposed strategy violates a predefined operational policy.
8. Supervisor rejects that strategy and requests a revised proposal.
9. Scenario Planning generates a compliant alternative.
10. Supervisor sends the final proposal for approval.

### Technical requirements

- Use LangGraph state and conditional edges.
- Pass structured task objects between agents.
- Track agent execution history.
- Record tool calls and results.
- Set maximum iteration limits.
- Prevent infinite loops.
- Handle unavailable tools.
- Track why the supervisor selected each agent.
- Preserve previous scenario results when replanning.

Do not simulate collaboration by simply displaying fabricated agent messages.

Agent interactions must correspond to actual executed functions and returned results.

**Expected result:** X FACTOR can reason across multiple agents, identify failed proposals and dynamically develop alternative recovery plans.

---

# STEP 6 — HUMAN-IN-THE-LOOP AND AUTHORIZED EXECUTION

**Prompt:**

Implement human approval and controlled execution in X FACTOR.

Use LangGraph interrupts and persistent checkpoints.

### Workflow

1. Supervisor receives the final validated recovery proposal.
2. Approval Management Engine evaluates the approval requirements.
3. If approval is mandatory, interrupt the LangGraph workflow.
4. Display the proposal in the approval interface.
5. An authorized manager reviews the proposal.
6. Manager approves, rejects or requests modifications.
7. Resume the workflow using the saved checkpoint.
8. If approved, execute authorized operations.
9. If rejected, return the feedback to the supervisor for reconsideration or close the workflow.
10. Record the entire decision history.

### Approval requirements

Require approval for:
- High-impact shipment rerouting.
- Major inventory redistribution.
- Actions exceeding defined budget thresholds.
- Sensitive supplier changes.
- Other configurable high-impact decisions.

### Security requirements

- Only authenticated and authorized users can approve.
- Never trust approval status submitted by an unauthenticated frontend request.
- Record approver identity and timestamp.
- Prevent duplicate execution.
- Use idempotency keys for operational actions.
- Validate approval against the current proposal version.

### Execution

Create an execution service that supports:
- Shipment plan updates.
- Inventory transfer requests.
- Carrier change requests.
- SAP API execution.

Use mock execution adapters when real enterprise credentials are unavailable.

Never perform actual operational actions without explicit authorization.

**Expected result:** A persistent, resumable workflow with secure approval and controlled execution.

---

# STEP 7 — SAP INTEGRATION

**Prompt:**

Implement the SAP integration layer for X FACTOR.

The purpose is to demonstrate how the Agentic AI system connects to enterprise supply-chain operations.

Use supported SAP APIs and OData services.

### Explore and prepare connectors for:

1. SAP S/4HANA.
2. SAP Business Accelerator Hub APIs.
3. SAP BTP.
4. SAP Integration Suite.

### Required integration capabilities

READ OPERATIONS:
- Shipment information.
- Purchase orders.
- Supplier records.
- Inventory levels.
- Material information.

AUTHORIZED WRITE OPERATIONS:
- Shipment plan updates where supported.
- Inventory transfer requests where supported.
- Approved operational changes.

### Architecture

SAP Enterprise Systems
→ SAP Integration Connector
→ FastAPI Backend
→ LangGraph Supervisor
→ Specialized Agents
→ Human Approval
→ Authorized SAP API Execution.

### Requirements

- Create a modular SAP connector.
- Use environment-based authentication.
- Follow the selected SAP API's authentication and payload requirements.
- Implement request validation.
- Handle rate limits and API failures.
- Log integration requests and responses without exposing secrets.
- Separate read and write permissions.
- Require approval before sensitive write operations.

If SAP sandbox credentials are unavailable, create a mock SAP adapter with realistic sample records.

Clearly distinguish real API integration from simulated integration.

Do not claim live SAP integration when using mock data.

**Expected result:** A working SAP integration interface that can retrieve enterprise information and demonstrate authorized operational updates.

---

# STEP 8 — AGENT ACTIVITY AND DECISION DASHBOARD

**Prompt:**

Develop the React frontend for X FACTOR.

Prioritize making the agentic system visible to hackathon judges.

Do not create a generic business analytics dashboard as the primary interface.

Create an enterprise-grade Agent Activity and Decision Center.

### Required pages

1. Overview.
2. Disruption Monitoring.
3. Agent Activity.
4. Scenario Comparison.
5. Approval Center.
6. Shipment Management.
7. Inventory Management.
8. Audit History.

### AGENT ACTIVITY PAGE — HIGHEST PRIORITY

Display:
- Current workflow ID.
- Active disruption.
- Current supervisor decision.
- Five individual agents.
- Agent execution status.
- Current agent task.
- Tools invoked.
- Structured agent results.
- Agent handoffs.
- Replanning events.
- Workflow progress.
- Errors and retries.

Use React Flow to display the agent workflow.

Use actual backend execution events, not fabricated activity.

### SCENARIO COMPARISON

Display alternatives with:
- Route.
- Estimated delivery time.
- Transportation cost.
- Risk score.
- Inventory impact.
- Compliance status.
- Recommendation.

### APPROVAL CENTER

Display:
- Proposed action.
- Reason for recommendation.
- Cost impact.
- Risk impact.
- Agent validation results.
- Approve/reject controls.
- Approval history.

### DESIGN

Use a modern enterprise control-tower aesthetic.

- Dark navy or clean light enterprise theme.
- Consistent typography.
- Clear rectangular architecture components.
- Professional status indicators.
- Responsive layout.
- Interactive charts.
- Clear agent execution timeline.

### Backend integration

Connect every page to actual FastAPI endpoints.

Implement loading, error and empty states.

Do not hardcode fake agent execution results.

**Expected result:** A fully connected frontend that visibly demonstrates the actual agent workflow.

---

# STEP 9 — TESTING AND END-TO-END VALIDATION

**Prompt:**

Perform a complete technical audit of X FACTOR.

Do not add unnecessary features.

Test the complete system from disruption detection to authorized execution.

### TEST SCENARIO

A maritime disruption affects a shipment of pharmaceutical products travelling from Mumbai to Rotterdam.

### Verify the following

1. Disruption ingestion.
2. Disruption Sensing Agent.
3. Risk scoring.
4. Supervisor delegation.
5. Scenario Planning Agent.
6. Rerouting & Logistics Agent.
7. Inventory Rebalancing Agent.
8. Compliance & Audit Agent.
9. Agent collaboration.
10. Autonomous replanning.
11. Human approval.
12. Workflow checkpointing.
13. Authorized execution.
14. SAP connector.
15. Database persistence.
16. Audit history.
17. Frontend updates.

### Additional failure tests

- Gemini API unavailable.
- External API timeout.
- Invalid LLM output.
- Missing shipment data.
- No alternative routes.
- Insufficient inventory.
- Compliance violation.
- Manager rejects proposal.
- Duplicate execution request.
- Database connection failure.

### Quality requirements

- Add unit tests.
- Add integration tests.
- Add end-to-end workflow tests.
- Fix critical errors.
- Validate security boundaries.
- Check logging and exception handling.
- Verify that workflow state persists.
- Check that the system does not execute rejected actions.

Generate a final report:

- Completed features.
- Incomplete features.
- Known limitations.
- Test results.
- Critical bugs.
- Deployment readiness.

**Expected result:** A stable and demonstrable end-to-end agentic system.

---

# STEP 10 — DEPLOYMENT AND HACKATHON DEMONSTRATION

**Prompt:**

Prepare X FACTOR for the SAP Resilient Supply Chains Hackathon demonstration.

Do not redesign or rebuild the working system.

### Deployment

1. Prepare Dockerfiles.
2. Configure Docker Compose.
3. Configure frontend and backend environment variables.
4. Configure PostgreSQL.
5. Configure persistent workflow checkpoints.
6. Verify service communication.
7. Add health checks.
8. Verify startup and shutdown behavior.

### Demo preparation

Prepare one complete Red Sea disruption scenario.

The demonstration must visibly show:

1. Disruption detection.
2. Supervisor reasoning and task delegation.
3. All five specialized agents executing.
4. External tool usage.
5. Deterministic calculations.
6. Agent collaboration.
7. Scenario comparison.
8. Compliance rejection and replanning.
9. Human approval.
10. Authorized execution.
11. Audit record creation.

### Final deliverables

- Working application.
- Source code.
- Architecture diagram.
- LangGraph workflow diagram.
- API documentation.
- Database schema.
- README.
- Docker deployment.
- Test report.
- Demo scenario and sample data.

Ensure all claims in the presentation match actual implemented functionality.

**Expected result:** A stable, fully demonstrable X FACTOR prototype.

---

# FINAL INSTRUCTION — DEVELOPMENT CONTROL

Follow the steps in order.

Do not combine all steps into one enormous code-generation task.

After completing each step, wait for the developer to review and test it before continuing.

If an issue is discovered in an earlier phase, fix it before proceeding.

The priority is to build a genuinely functional multi-agent system with autonomous coordination, real tool execution, dynamic replanning, human approval and SAP integration.

The objective is not to create five AI chatbots.

The objective is to create one coordinated Agentic AI supply-chain resilience platform.

**X FACTOR: Detect → Reason → Simulate → Approve → Execute.**