# MAD design

Status: design agreed through discussion on October 3, 2026; a first local
implementation was added on October 4, 2026. This document records the discussion;
the original pasted prompt is background material, not an implementation
specification. See [implementation choices](docs/implementation.md) for resolved
defaults, deviations, verification scope, and remaining work.

## Purpose and scope

Build a general tool for configuring and recording rollouts: launch an arbitrary
configured number of agents, give them tasks and an environment, let them work
concurrently, and preserve their trajectories and artifacts for later analysis.

The initial scientific question is whether agents independently discover other
agents' work and develop emergent coordination. Initial instructions must not
tell agents that other agents exist or encourage coordination. Discovery should
happen through task artifacts, not peer processes or orchestration metadata.

Task setup should support instructions, initial files, available tools, and
task-specific evaluation. Synthetic optimization is the first task family,
not the defining abstraction of the rollout system.

## Settled requirements

### Initial optimization experiment

- Every agent optimizes the same underlying synthetic black-box function.
- Each experiment returns a noisy observation, with independently sampled noise
  on every call, including repeated parameter configurations.
- Seeded randomness makes generated functions and noise sequences reproducible.
  This does not imply that concurrent agent trajectories are reproducible.
- Each agent can run at most X experiments. Repeating parameters consumes budget.
- An agent may submit any valid configuration, whether or not it personally
  tested it. Reuse of another agent's results and inference are allowed.
- A `submit(parameters)` tool records the choice and ends the agent's run.
  Submission uses no experiment budget and reveals no new measurement.
- MAD computes the submitted configuration's noise-free objective afterward.
- Exhausting the experiment budget blocks further experiments but does not end
  the run. Analysis, artifact access, note writing, and submission remain possible
  until submission or a configured model-turn or elapsed-time limit.
- Agents that finish early exit. Delayed submission is a behavior to preserve
  for analysis, rather than automatically prevent.

### Environment and artifacts

- Each agent has a private `/workspace/` for its instructions and working files.
- A common lab exposes `/lab/runs/` and `/lab/notes/`.
- Experiment records appear automatically in `/lab/runs/` and are immutable.
- Publishing notes is voluntary.
- An agent may create files and edit files it created, but cannot edit files
  created by another agent.
- Other agents' experiment records and notes are both visible initially.
- Run visibility and note visibility are independently configurable, initially
  supporting `own` and `all`.
- Instructions describe the directories neutrally. Names and tool descriptions
  must not unnecessarily announce multiple agents or collaboration.

### Harness and execution

- Use Python and the OpenAI Agents SDK for the first harness.
- Keep the harness replaceable so other harnesses can be supported later.
- Target a Linux VM with one Docker container per agent.
- MAD and the SDK run outside agent containers. Agent-generated Python executes
  inside the corresponding container.
- Initially expose explicit file tools and sandboxed Python, without a shell
  tool. Python's OS access still requires enforced isolation and permissions.
- Containers do not have external network access initially. Model requests are
  made by MAD outside them.
- Agents must not see peer processes, private peer workspaces, rollout config,
  orchestration logs, API credentials, or hidden objective/evaluator source.

## Proposed implementation boundaries

The following is an implementation outline, not a commitment to a particular
module layout or configuration format.

1. **Rollout controller:** load configuration, prepare environments, launch
   independent agents concurrently, enforce limits, and collect outputs.
2. **Harness adapter:** translate one agent's instructions and tool access into
   SDK execution and return its observable trajectory and termination state.
   The adapter does not expose handoffs, agent lists, or messaging tools.
3. **Environment backend:** manage containers, private workspaces, artifact
   visibility, and file ownership. Enforce restrictions beneath both file tools
   and Python so direct filesystem access cannot bypass them.
4. **Task adapter:** provide initial task materials, experiment execution,
   parameter validation, submission handling, and evaluation. Keep the synthetic
   optimization implementation outside the general rollout controller.
5. **Recorder:** retain model messages available from the harness, tool calls
   and results, experiments, submissions, artifact changes, timestamps, usage,
   errors, and termination reasons outside agent-accessible storage.

Keep experiment execution and budget enforcement in trusted MAD code, outside
agent Python. Use container process isolation and a correctly scoped process
filesystem; do not share host or peer process namespaces. Configure filesystem
permissions and mounts explicitly rather than relying on container defaults.

Creator-only editing should also prevent replacing another agent's file through
deletion or rename. The exact permission and publication mechanism still needs
design and verification, including concurrent creation and filename collisions.

File tools provide structured access events. Arbitrary Python can access files
directly, so complete file-read attribution requires additional instrumentation.
Do not claim complete filesystem tracing from tool-call logs alone. Preserve
observable model output without claiming access to hidden model reasoning.

## Configuration scope

The initial configuration should describe agent count, harness/model settings,
task instructions and initial files, tool access, experiment budget per agent,
model-turn and elapsed-time limits, objective and noise seeds, parameter schema,
noise settings, and independent run/note visibility.

Support configurable experiment duration and agent start offsets to create
opportunities to encounter evolving artifacts. Their exact scheduling semantics
and initial defaults are open. Record them as experimental conditions.

Later configurations may introduce isolation, explicit awareness of peers,
instructions to coordinate, related objective variants, and additional harnesses.
These are extension directions, not required first-milestone implementations.

## First successful rollout

One command launches a small configured set of agents on a Linux VM. They work
concurrently on the same synthetic optimization problem, can discover permitted
live lab artifacts, and can submit final choices. MAD preserves transcripts,
tool calls/results, workspace and lab artifacts, experiment records, submissions,
evaluation results, and termination reasons in a run-specific output directory.

Verification must cover experiment budget enforcement, independent seeded noise,
submission behavior, visibility modes, record immutability, creator-only editing,
and isolation through both Python and file tools. A small real SDK rollout should
verify the complete path once infrastructure and model access are available.

## Open details before implementation

- Configuration format, CLI shape, and output schema.
- Initial model and operational limits; credentials and VM provisioning.
- Synthetic function family, parameter types/ranges, and noise distribution.
- Whether experiment-budget charges occur on invalid calls or failed execution.
- Seed derivation and noise ordering under concurrent execution.
- Experiment-duration and start-offset defaults and semantics.
- Artifact author metadata, naming, publication, and ownership enforcement.
- Python session persistence, available libraries, and execution resource limits.
- File-access instrumentation depth and its known blind spots.
- Turn/time-limit accounting, including pending calls and experiment waits.
- Handling of agents that reach a limit without submitting. The proposed behavior
  is to record no submission rather than invent a final choice; this is not yet
  explicitly settled.

## Implementation sequence

1. Resolve the necessary open details and define minimal config/event contracts.
2. Build container environment preparation and verify isolation and permissions.
3. Add the synthetic task, experiment budgets, automatic records, and submission.
4. Connect one independent SDK agent through the harness adapter and recorder.
5. Launch multiple agents concurrently and exercise a tiny end-to-end rollout.
6. Document the runnable workflow, tested guarantees, and instrumentation limits.
