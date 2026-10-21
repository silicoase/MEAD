# Cross-provider setup and output pilot

Work for [MEAD issue #12](https://github.com/silicoase/MEAD/issues/12).
The setup pilots are complete; the three-model full experiment is configured but unstarted.
See [HANDOFF.md](HANDOFF.md) for destination-machine setup, capacity checks and launch commands.

The active unified plan currently retains **Z.ai GLM 5.3 Flash, Anthropic Claude Haiku 5.5, OpenAI GPT-6 Luna**.
The other models were removed from the future roster after the fresh pilot; all
pilot definitions and raw results remain archived. Additional models are being
considered and have not been added or launched.
The full experiment currently specifies twenty matched sets × three models × two
conditions: 120 runs, 1,200 agent sessions, and up to 12,000 measurements. There is no
`aware` arm or mixed-model team. Full execution has not started.

Full sets 1–20 use objective seeds 1000–1019 and noise seeds 2000–2019.
The separate `pilot-seven-models.toml` uses one matched set with seeds 42/123,
14 runs and 140 agent sessions. This pilot runs with instant experiments and
the 1-second starting stagger; its data is excluded from the full experiment. The two prompt files are exact copies
from `examples/pilot`; only the original interaction sentence differs. Both arms
retain shared notes and records. Other retained settings are eight dimensions,
noise SD 0.1, instant measurements (no artificial delay), a 1-second starting stagger, notebook timestamps,
80 turns, and a 30-minute timeout per agent. Active configurations limit completions to 16,384 tokens,
including reasoning where the provider counts it; reasoning uses provider defaults.

## Routing and scheduling

Provider pinning is optional. The current setup configurations omit pins so
OpenRouter may select/fall back between compatible hosts for the same model.
Specifying `harness.routes.provider` restricts the host and disables fallbacks.
Actual model/host, generation/request IDs, raw usage/cost, latency and failures
are recorded per response. Structured reasoning is replayed on its original
assistant tool-call turn, isolated per agent. API keys stay in the host `.env`.

The retained active configurations allow ten concurrent API requests per arm and
up to three same-model retries for HTTP 429, transient 500/502/503/504 or connection errors, and the specific truncated upstream-response case: 10-second exponential backoff
with jitter. Retries release the request slot while waiting. SDK HTTP retries
remain disabled; attempted requests, failures and retry delays are recorded.
No tool actions are replayed by a generation retry. Invalid provider payloads are archived before retry; general request-validation errors are not retried. Latency includes queue/backoff.

`experiment.toml` uses schema version 3 to define the model/condition matrix with
one manifest and review index. Conditions run together in isolated labs; model
pairs run sequentially, so at most 20 agent sessions run at once. A failed pair
stops later models/sets. The seven model folders remain available individually:
Gemini 3.1 Flash-Lite, Qwen3 Next 80B A3B Instruct, DeepSeek V3.2, Llama 4 Scout,
MiniMax M2, GLM 4.7 and Kimi K2 Thinking.
Standalone per-model definitions retain one repetition.

Offline validation makes no API calls and starts no Docker containers:

```sh
uv run mad batch experiments/cross-provider-tinkering/experiment.toml --dry-run
```

Remove `--dry-run` to execute when authorized. Set `OPENROUTER_API_KEY` in the
repository `.env` (shell values take precedence).

## Recorded setup iterations

- `20261007T165342Z-abd82333`: first pinned attempt stopped after one Gemini agent
  hit upstream 429; 19/20 submissions in that pair.
- `20261007T170035Z-7fde3be2`: bounded 429 recovery; completed Gemini pair and
  interrupted Qwen pair, cancelled when provider pinning was dropped.
- `20261007T171159Z-1d8ce814`: active unpinned two-set setup batch.

These directories live under `outputs/cross-provider-tinkering/`. Raw inputs,
events and partial/failed runs remain intact. Review snapshots are stored separately
under `outputs/cross-provider-review/`; they do not overwrite raw evidence.

## Requested outcomes and figures

Generate a model-aware comparison and scientific figures:

```sh
uv run python scripts/review_cross_provider.py BATCH_PATH REVIEW_PATH
uv run python scripts/plot_cross_provider.py collect REVIEW_PATH/figures --batch BATCH_PATH
uv run --with matplotlib --with numpy --with fonttools python scripts/plot_cross_provider.py plot REVIEW_PATH/figures
```

The gallery exports PNG/SVG figures, source JSON, and two CSV tables. Each model is
shown separately; only complete within-model control/interact pairs enter aggregates.
Interrupted, failed and pending pairs stay in the diagnostic comparison report.

- **Mean agent best:** each agent's best noiseless score among completed measurements,
  averaged over agents with results and then runs with results, with equal run
  weights. Starts at the first result; agent/run denominators change as results
  arrive. Missing scores are not imputed as zero.
- **Run maximum:** maximum noiseless score across completed measurements in a run,
  then mean across runs. Final submissions are excluded from both trajectories.
- **Elapsed-time share:** first agent start to last agent finish, excluding setup/cleanup.
- **Budget share:** accepted experiments / (agents × per-agent budget). Budget is
  consumed before a result arrives. Later analysis/interactions map to the last
  budget fraction; finished runs carry terminal values through unused allocation to 100%.
- **Experiment step:** align agents by their completed experiment count. At step k,
  use each agent’s best score from its first k results, then average/maximize
  within runs and average across runs. Finished agents carry their last measured best forward through unused steps; all agents/runs remain included.
- **Reference-style final table:** pooled-agent mean final submitted score, mean
  per-run maximum final score, and mean within-run sample SD (ddof=1). Submissions
  and missing scores are reported alongside these outcomes.
- **Interaction panels:** cumulative logged peer-file reads, peer-mention candidate
  responses, and specific-agent mentions, summed over agents and averaged across
  runs. Plain released reasoning text/summaries are included; encrypted blocks,
  prompts and tool results are excluded. Specific mentions are a subset. Python
  bulk reads are not captured, and reasoning availability varies across hosts.
- **Discovery panels:** agent-level indicators flip to 1 at the first successful
  listing showing a peer-authored result, notebook, or either. Returned author IDs
  establish ownership; directories, unknown authors, own files and failed listings
  do not count. Plot the proportion of all agents, averaged equally over runs.
  Indicators remain 1; listing does not establish reading or understanding. Python
  listings are excluded. First-listing evidence and final per-agent indicators are
  saved in outcomes.json.

Measured-best and final-submission tables are separate because agents can submit
configurations worse than their best tested configuration. These small setup runs
validate instrumentation and output; they do not establish an interaction effect.


## Second-set recovery and combined outputs

The unpinned first set completed with 60/60 submissions. Gateway 504s stopped its
initial second-set Gemini pair. `retry-set-two.toml` reused seeds 43/124 and completed
Gemini, then stopped when DeepInfra returned a truncated-data payload during Qwen.
`retry-set-two-tail.toml` reruns only Qwen and the pending MiniMax pair. All failed
attempts are retained. Routing/retry changes are setup iterations, not fixed-protocol
confirmatory trials.

`scripts/combine_setup_runs.py` creates a derived, source-linked review of the latest
attempt per model/condition/seed, validates that the objective code is identical,
and leaves all raw evidence intact. Its inputs are the original unpinned batch and
both recovery batches. The combined report/gallery is under
`outputs/cross-provider-review/two-matched-sets/`. These derived outputs record source
batch/run identities; failed or pending pairs do not enter aggregate figures.


The interactive viewer selects one outcome and either one or all models/time axes.
Compare models fixes a time axis; compare time axes fixes a model; compare both
shows the full model/time grid. Selections persist in the URL fragment. Every trajectory metric has elapsed-time, global-budget and per-agent
experiment-step figures, each exported separately as PNG/SVG. Final submitted-score
tables remain separate summaries. `figure-manifest.json` indexes the exports.

Wait counts include every logged `tool_called` event for the `wait` tool, including
failed/cancelled calls. Provider backoff and measurement delays do not count. Totals
per run and per agent are in `wait-call-totals.csv` and `outcomes.json`.
Interaction step k counts each agent's events through completion of its kth
experiment; finished agents carry terminal totals through unused steps. Final work after the last
experiment is included at that last step and then carried forward.
Archived setup runs used 15-second measurements; new configurations use zero delay.

The cost outcome shows cumulative provider-reported USD, averaged over runs.
Receipts from provider-response metadata are counted once, without adding SDK
copies. The viewer and cost-table.csv report totals and means per run/agent, with
cost coverage counts. Unreported costs remain unknown. Failed attempts outside
the selected complete runs are excluded. Cost step k includes receipts through
each agent's kth experiment result; final analysis costs are included at the last used step and carried forward.

The live SVG explorer supports selecting any subset of models and conditions,
side-by-side model panels or overlaid curves, and multiple time axes. Hover shows
stepwise values; drag zooms horizontally; legends toggle curves. Each chart can
export its current view to SVG/PNG. The viewer embeds chart-data.json, so it works
from a local file without a server. Curves use the same precomputed run averages
as the static plots, with shared outcome-specific vertical scales.

The delta mode computes Interact minus Control within each matched repetition
at every axis point, then averages available matched-pair differences. Both arm
values must be available; hover reports the contributing pair count. Delta scales
are shared across models/time axes and symmetric around zero. Discovery deltas
use percentage points; cost deltas use USD. Positive means Interact is higher,
which is not necessarily better for cost or other outcomes.

`start_stagger_seconds = 1.0` spaces initial agent starts at 0, 1, …, 9 seconds
for ten agents. Set it to `0.0` for simultaneous starts. It only delays initial
starts; experiments remain instant. Custom `start_offsets_seconds` can be used
instead. Providing both a nonzero stagger and inconsistent offsets is rejected.

Budget-share curves carry each finished run's terminal values through unused
allocation to 100%, retaining the same runs in every average and matched delta.
For example, the Qwen3 Next 80B A3B Instruct control discovery mean stays 60%
through 100%, including the run that finished at 98% allocation.

The 1–10 experiment-step axis retrospectively aligns a fixed group of agents.
Agents that finish early carry their best measured score and terminal cumulative
counts/costs through unused steps. Final tool/cost events after the last experiment
are included at that last used step. Agents still running are not carried forward;
unknown scores remain unknown. The same definitions apply to matched deltas.

## Seven-model pilot attempt

`outputs/cross-provider-seven-model-pilot` attempted the initial model sequence;
Llama 4 Scout failed routing because the only tool-compatible endpoint requires
a Google BYOK credential. The batch stopped before GLM 4.7 / Kimi K2 Thinking.
`pilot-seven-models-tail.toml` continued those two models separately. Raw data is
preserved in `outputs/cross-provider-seven-model-pilot-tail`.

The derived review at `outputs/cross-provider-review/seven-model-pilot` contains
12 completed runs across six models, 104/120 final submissions, and both Meta
routing failures in its completion table. Reported selected-run cost is $7.1105.
Qwen3 Next 80B A3B Instruct had one 80-turn empty-Python-output loop. Its tool help
now explicitly requires print(...) for stdout; the tail used this clarified help.
DeepSeek V3.2 had 11 timeouts and three final answers without a submit call.
Kimi K2 Thinking had one final answer without a submit call. Meta was subsequently dropped from the future roster. Full 20-pair execution has not started.


## Final-score imputation

Report submission rate and submitted-only noiseless final scores together.
Separately, actual submitters retain their final score; each non-submitter receives
`min(lowest submitted score in its run, its own best completed noiseless experiment score)`.
This is analysis only and never creates a submission. If a run has no submitted
scores or a non-submitter has no completed experiments, its value is unknown.
The pooled group mean is unknown if any agent is unresolved; no agents are dropped
and no zero or arbitrary failure floor is introduced. `final-agent-outcomes.csv`
records actual, imputed and unknown values; the summary table reports coverage.
Notebook filenames remain agent choices; ownership collisions remain observable
failed tool calls rather than being prevented by filename instructions.

The fresh six-model pilot uses `pilot-six-models.toml`, one matched set with objective/noise seeds 43/124, ten request slots, and DeepSeek V3.1 Terminus. It is separate from the earlier pilot and the formal seeds 1000–1019/2000–2019.

Fresh six-model pilot completed: 119/120 actual submissions, 1,184 measurements, $9.0343 reported cost, and two successful text-only continuations. GLM Control has one reasoning-only token-cap error; it was retained rather than rerun. Kimi finished in a separate same-settings tail batch. Review: `outputs/cross-provider-review/six-model-pilot/figures/index.html`; audit: `outputs/cross-provider-review/six-model-pilot/index.html`. Full execution has not started.

GPT-5.6 Luna was added to the planned roster without launching it. All three retained configs currently keep the setup cap of 4,096 total completion tokens per API response; reasoning and visible output share this cap on most providers. This cap is under review after the GLM reasoning-only truncation.

Claude Haiku 5.5 was added to the future roster. The active GLM/Kimi/Luna/Haiku configs now use `max_tokens = 16384` per model response, replacing the 4,096 setup cap. Reasoning and visible output still share that allowance on most providers; reasoning effort remains at provider defaults. Existing turn, time, measurement, concurrency and stagger limits are unchanged. Historical pilot snapshots retain their original 4,096 cap.

## Four-model pilot at the increased token cap

`pilot-four-models.toml` ran one matched set at objective/noise seeds 44/125.
GLM 4.7, Kimi K2 Thinking and Claude Haiku 5.5 each had 20/20 actual submissions.
OpenAI GPT-5.6 Luna had 4/20 submissions and 16 rate-limit errors: OpenRouter
limits new accounts to 20 requests/minute for this model across conditions.
The two-turn live preflight passed but did not establish load capacity.
The batch stopped at Luna; `pilot-four-models-haiku-tail.toml` completed the
remaining Haiku pair with identical config, seeds, prompts and runtime code.
No agent or episode was rerun. All eight terminal episodes remain in the review.

Overall: 64/80 submissions, 670 measurements and $4.12892969 reported cost;
1,261 response receipts had reported costs. Separate preflights cost $0.0007481.
No token truncations; five non-submitted scores could be imputed, eleven remain
unknown because the agents had no own experiments. Luna full-cohort imputed
means remain unknown. One Haiku Interact agent used nine experiments and submitted;
its terminal values carry forward through step 10 and 100% allocation.

Review: `outputs/cross-provider-review/four-model-pilot/figures/index.html`;
audit: `outputs/cross-provider-review/four-model-pilot/index.html`.
Luna needs shared request pacing or removal of the temporary account limit, plus
a load check and deadline assessment, before scaling. Formal execution remains
unstarted.

## Luna retry

`pilot-luna-retry.toml` reran a fresh Luna-only matched set at seeds 45/126,
with the existing 1-second stagger and no added API pacing. Result: 6/20
actual submissions (3/10 each arm), 66 experiments, 152 HTTP 429 errors,
14 terminal rate-limit failures, $0.05460907 across 147 reported responses.
The same `openrouter_new_account` restriction remained in force. Four missing
final outcomes could be imputed; ten remain unknown because the agents had
no own measurements. Both episodes remain included. Review and shareable
sanitized error: `outputs/cross-provider-review/luna-retry/index.html`.
The full experiment has not started.

## Luna removed from the active roster

OpenAI GPT-5.6 Luna was removed from `experiment.toml` after the retry confirmed
the same OpenRouter new-account 20-RPM restriction. No model-specific request
pacing was added. Historical Luna configs, pilot definitions and raw results are
retained for reference. The active plan is twenty matched sets across GLM 4.7,
Kimi K2 Thinking and Claude Haiku 5.5: 120 runs and 1,200 agent sessions.
The one-second initial stagger and instant experiments remain configured.
Full execution has not started.

## GPT-6 Luna and Gemini 3.8 Flash pilot

GPT-6 Luna (`luna6`) and Gemini 3.8 Flash (`gemini38`) were added following
the user's selection. Both passed native two-turn read_file/submit compatibility
checks through the existing OpenRouter harness. `pilot-new-models.toml` tests
one fresh matched set for each at objective/noise seeds 46/127, with unchanged
10-agent, 10-experiment, one-second start stagger, instant-experiment and
16,384-token settings. No added request pacing. Pilot data is separate from the
formal seeds. The full five-model experiment has not started.

New-model pilot result: both preflights passed, but both models hit the same
OpenRouter new-account 20-RPM restriction. GPT-6 Luna's pair was interrupted
when Docker stopped (no complete terminal summaries; no final submissions).
Gemini's first startup attempt made zero model requests. After Docker restoration,
the Gemini pair completed: 1/20 actual submissions, 17 rate-limit failures and
two 80-turn failures, with 26 experiments. Raw attempts remain separate.
Both models reported reasoning tokens alongside live tool calls. Known pilot
receipt subtotal $1.771597235, plus $0.00184115 for preflights; interrupted Luna
cost coverage may be incomplete. No new-model full experiment or coordinated
pause policy has been launched. Review: `outputs/cross-provider-review/new-models-pilot/index.html`.


## Coordinated rate-limit recovery

All five active model configs now enable the same matched-pair recovery policy:

```toml
[harness]
coordinated_pause = true
max_pause_seconds = 1800
```

Only an HTTP 429 explicitly marked `openrouter_new_account` triggers this policy.
Both conditions stop admitting new API requests and tools; admitted work drains
without replay. Their sandbox containers then pause together, including detached
Python processes. Requests queue until the provider reset time (with a one-second
guard; missing or invalid reset information uses 60 seconds). Concurrent errors
extend a shared pause. Ordinary provider errors retain the existing bounded retry
policy. The cumulative frozen-time allowance is shared by the pair; exhaustion
or suspension/resumption failure fails closed and remains a recorded failure.
The feature defaults off outside these configs; compatibility probes keep their
strict wall-time deadline and do not use this recovery policy.

Agent deadlines and start staggering use active time. Both wall and active event
clocks are recorded, and the viewer offers an additional active-time axis. Draining
and container suspension/resumption overhead count as active time. Experiment and
turn limits, per-agent noise streams, submitted scores, and allocation/step axes
are unchanged. Historical raw results have not been rewritten.

Suggested writeup footnote: “Infrastructure rate-limit recovery pauses both
matched conditions after admitted work drains. New requests and tools queue, and
sandbox processes are suspended. Only fully frozen intervals are excluded from
agent deadlines and active-time plots. In-flight completions and resumed queue
order can affect artifact visibility and collaboration timing; artifacts retain
wall timestamps. Experiment budgets, noise streams and scoring are unchanged.”

Recovery has been checked with simulated HTTP errors and sandbox suspension.
No live pilot or formal experiment has been launched with this policy yet.


## Coordinated-pause live check and pilot

`pilot-coordinated-pause.toml` reserves one fresh matched set across all five
models at objective/noise seeds 47/128. The formal experiment remains unstarted.
Before launch, all five two-turn compatibility checks passed, and all 17 pause
tests (including the real Docker suspension test) passed. A separate bounded
twenty-agent, two-turn GPT-6 Luna probe exercised two real new-account 429s: one
shared 48.62-second freeze, 20/20 actual submissions, 40 costed responses, no
activity during the freeze, zero scientific experiments, $0.0030185 reported
cost. The probe took about 61 seconds wall time and 13 seconds active time.
Compatibility probes separately cost $0.00550605.

Raw pilot: `outputs/cross-provider-coordinated-pause-pilot/run-01`.
Recovery audit and progress: `outputs/cross-provider-review/coordinated-pause-pilot/index.html`.
`scripts/check_coordinated_pause.py` runs the bounded live check;
`scripts/review_coordinated_pause.py` reads saved pilot logs and reports frozen
actions, duplicate receipts, clock inconsistencies and experiment-budget overruns.
Probe and pilot data are separate from formal-experiment data.


The coordinated-pause pilot was manually suspended during an already-quiescent
GPT-6 Luna recovery window for laptop relocation. The pilot process and all
remaining agent containers stayed suspended, with no in-flight model or tool
operations. On return, a tested accounting hook credited the operator interval
separately from the API freeze cap and corrected wall time for macOS sleep; agent
active clocks, model/experiment budgets, noise streams and scores were unchanged.
The existing process resumed both Luna conditions, with Gemini scheduled next.
The administrator-authorized hook and accounting source are saved as supplemental
provenance in `outputs/setup-checks-coordinated-pause`; raw pre-pause events and
original input snapshots were not rewritten. Wall plots include operator downtime,
while active-time plots exclude it.


Coordinated-pause pilot result: GLM 4.7, Kimi K2 Thinking, Claude Haiku 5.5 and
GPT-6 Luna each produced 20/20 actual submissions. Gemini 3.8 Flash produced
0/20; three agents exhausted ordinary retries on Google HTTP 504 responses,
and the remaining seventeen stopped when the shared 1,800-second API freeze
allowance could not accommodate the next reset. Gemini completed 30 experiments (21 Control,
9 Interact), with 42 completed pauses, about 12.03 active minutes and 29.93
API-paused minutes. This is an infrastructure termination, not exhaustion of
its 80 model turns or 30 active minutes. All raw episodes and missing final
outcomes remain included; no experimental outcome was relabeled a submission.

Across the pilot: 80/100 actual submissions, 822 completed experiments and
$8.615004653 reported task cost. Compatibility and live recovery probes separately
cost $0.00852455. The read-only audit found no frozen activity, duplicate response
receipts, noise-stream mismatches, final-score mismatches or experiment-budget
overruns. Luna completed 32 shared pauses with 20/20 actual submissions after
the operator pause/resume; its natural API allowance remained 30 minutes.
Before formal execution, the API recovery guard must be reviewed against the
configured request budget: 20 agents times 80 turns is up to 1,600 successful
requests, which needs roughly 80 minutes at 20 RPM before latency and retries.
Google returned 75 HTTP 504 responses in this pair; the cause of those upstream
failures has not yet been established. The formal twenty-pair experiment remains
unstarted.

Gemini 3.8 Flash was removed from the active full-experiment roster after the
coordinated-pause pilot. Its configuration, historical pilot definitions and raw
results remain available for diagnosis. The active roster is GLM 4.7, Kimi K2
Thinking, Claude Haiku 5.5 and GPT-6 Luna. No new runs were launched.

The active plan now replaces GLM 4.7 with GLM 5.3 Flash (`z-ai/glm-5.3-flash`,
model key `glm53`) and removes Kimi K2 Thinking. Claude Haiku 5.5 and GPT-6
Luna remain. GLM 5.3 Flash inherits the existing limits, stagger and recovery
settings; compatibility checks and a matched-pair pilot are still pending.
Historical pilot definitions and model configurations remain unchanged.

GLM 5.3 Flash compatibility and pilot completed: the native two-turn check
passed through InferenceNet ($0.00010866). `pilot-glm53.toml` ran one fresh
Control/Interact matched pair at objective/noise seeds 48/129. Control produced
9/10 actual submissions and 94 experiments in 26.50 minutes; Interact produced
10/10 submissions and 100 experiments in 21.90 minutes. One Control agent
received an empty response with `finish_reason=length` at the 16,384-token
allowance (Friendli). No API errors or coordinated pauses occurred. Reported
task cost was $1.5225778, with no missing receipt costs or audit violations.
The unsuccessful final outcome remains missing, not replaced by an experiment.
Review: `outputs/cross-provider-review/glm53-pilot/index.html`; interactive
figures: `outputs/cross-provider-review/glm53-pilot/figures/index.html`.
The formal twenty-pair experiment remains unstarted; the empty truncated
response needs a policy decision before scaling.

The three active models now use a fixed 32,768-token response allowance in
both conditions. Empty token-limited responses terminate with reason `error`
and explicit `error_kind=empty_truncated_response`; their response receipt and
cost are retained. No extra generation attempt, tool replay, or submission
imputation is performed. A dedicated test verifies this behavior.
`pilot-glm53-32k.toml` repeats the earlier GLM-only matched pilot seeds 48/129
under the larger cap; raw data is separate from the original pilot.

The three active model configs now allow 3,600 active seconds (60 minutes)
per agent, while retaining 80 model turns, ten experiments and the fixed
32,768-token response cap. The API freeze allowance remains 1,800 seconds
per matched pair. The already-running 32k pilot retains its original
1,800-active-second snapshot; future launches use the longer timeout.

The 32k GLM pilot finished at its original 30-active-minute limit: Control
9/10 submissions with 100 experiments, Interact 6/10 submissions with 89
experiments. Five agents ended at the active-time limit; none had empty
truncated responses or API errors. Reported cost was $1.53645561, plus
$0.00010808 for compatibility. The score/noise/budget audit found no violations.
Future launches use the approved 60-minute active timeout. The full
experiment remains unstarted. Results: `outputs/cross-provider-review/glm53-32k-pilot`.
