# MAD design

MAD launches independently configured agents on a shared task and preserves
observable trajectories and artifacts for analysis. Python runs the controller
and harnesses on the host; Docker provides one isolated execution environment
per agent. Docker Desktop supports local execution on macOS.

## Experiment setup

The synthetic optimization task uses a seeded objective, independent Gaussian
measurement noise, and an experiment budget for each agent. Each accepted
experiment consumes budget, including repetitions and interrupted calls. Invalid
parameters consume no budget. Submission ends the session and selects any valid
configuration for noise-free evaluation by the controller.

Agents have private workspaces and configurable access to live lab notes and
experiment records. Run visibility and note visibility independently support
`own` and `all`. Instructions and initial files are configurable. The pilot
conditions study discovery with neutral directory descriptions, explicit peer
awareness, and permission to interact through artifacts.

Experiment latency and start offsets are configurable. Session time limits
begin after each agent's start offset. Exhausting experiment budget leaves
analysis, file access, waiting, and submission available until a session limit.
An agent reaching a limit without submitting has no final score.

## Components

- The rollout controller prepares environments, launches concurrent sessions,
  enforces limits, and collects outputs.
- Harness adapters provide OpenAI Agents SDK execution and scripted plumbing
  checks. Additional adapters require Python changes.
- The environment manages containers, private workspaces, live artifact
  publication, visibility, and creator-only note editing.
- The task provides parameter validation, noisy measurements, budgets,
  submission, and final evaluation.
- The recorder preserves observable model requests and responses, tool calls
  and results, experiments, submissions, timestamps, usage, and termination.
- The offline explorer displays saved evidence and a reviewer-only numerical
  estimate of the synthetic objective's maximum.

## Isolation and artifact access

Agent containers use separate process namespaces and private workspaces, distinct
non-root UIDs, read-only lab mounts, no network, and configured resource limits.
Credentials, rollout configuration, controller logs, objective source, and
reviewer estimates stay on the host. Model requests run through the host SDK.

Trusted file tools publish notes atomically and enforce creator-only editing.
A locked ownership registry serializes competing claims to the same shared
filename. Published experiment records are immutable. Python can read permitted
lab artifacts and maintain private workspace files; file tools maintain notes.

File tools record structured access events. File access inside arbitrary Python
is not individually traced. Provider reasoning summaries are recorded when
returned. Observable logs support inspection of interaction; coordination flags
identify candidate events for that inspection.

## Configuration and outputs

TOML configuration specifies agent count, tools, harness/model settings, task
instructions and initial files, budgets, turn/time limits, seeds, bounds, noise,
artifact visibility, note metadata, experiment duration, and start offsets.
Run outputs contain resolved configuration, runtime metadata, identities, event
logs, experiment records, submissions, final scores, and an artifact archive.

See [README.md](README.md) for commands and examples, and
[implementation details](docs/implementation.md) for execution semantics and
operational limits.
