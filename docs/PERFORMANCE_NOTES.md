# Question latency and resource profiles

## Observation

The user reported that asking a question felt slow. The elapsed time, whether
the request was a follow-up, and which stage dominated have not yet been
measured. Do not treat any candidate cause below as a confirmed diagnosis.

The local computer reported approximately 8 GB of RAM, an Intel i5-11300H
(4 cores / 8 logical processors), and an NVIDIA RTX 3050 Laptop GPU with about
4 GB of reported graphics memory. Availability changes with other running apps.
The base Ollama Compose configuration uses CPU. An optional NVIDIA override was
verified on 20 November (results below). Embedding and reranking remain on CPU.

## Measure before tuning

- Record cold and warm timings separately, including queue wait, optional
  follow-up rewrite, query embedding, BM25 construction and search, vector
  search, reranking, generation, and any citation-repair attempt.
- Record peak system RAM and GPU memory, CPU/GPU utilization, corpus size,
  model and prompt versions, context/output limits, and whether the model was
  already loaded. Avoid logging questions, document text, or prompts.
- Run the same small, reviewed question set for each configuration; report
  latency alongside retrieval quality, answer support, and citation accuracy.
  First-question and follow-up cases should both be included.

## Candidate configurations

**Resource-constrained systems:** keep processing sequential and use modest
context and output limits. Consider a smaller quantized local generation model
only after evaluating answer and citation quality. Cache BM25 within a bounded
memory budget, with ownership checks and invalidation for source changes.
Experiment with fewer reranking candidates or making reranking optional; compare
retrieval quality before selecting a default. Longer model keep-alive can reduce
reloading, but occupies memory longer and must be measured against RAM pressure.

**Systems with more available resources:** retain hybrid retrieval and
reranking; consider GPU acceleration for Ollama where Docker, drivers, GPU
access, and available VRAM support it. Verify actual model offloading and
compare cold and warm runs before claiming a speedup. Larger contexts, models,
and parallel requests require additional memory and should be enabled only
after measurement. A bounded BM25 cache remains useful at either resource level.

On this computer, GPU access is a particularly relevant experiment, not a
guarantee that every model and context will fit in 4 GB of VRAM. If
acceleration is unavailable or only partly offloaded, retain a working CPU
configuration. Keep changes tied to measured speed and quality. The original 3B
model was retained during the first smaller-model experiment; the current release
profile and its quality limitations are recorded below.

## Historical investigation — 16 November 2026

On 16 November, the new synthetic summary check could not complete with
`llama3.2`: the normal 120-second request timed out, and a diagnostic 300-second
request also timed out. Ollama logs showed model tensor loading during these
attempts. Windows reported about 0.8 GB free physical RAM during diagnosis.
Stopping the idle workspace API and worker did not resolve the extended check.
This does not establish a generation-speed benchmark: successful cold-load and
generation timings are still needed. The user has been asked whether to test a
smaller local model; the user approved that test. The candidate is
`llama3.2:1b-instruct-q4_K_M`, tested through a per-process model override. The
application model and timeout remain unchanged while results are reviewed.

### Smaller-model experiment — 16 November 2026

Tested `llama3.2:1b-instruct-q4_K_M` using per-process overrides, with the
workspace services running. Ollama's catalog identifies the Q4 model as 808 MB:
[model details](https://ollama.com/library/llama3.2:1b-instruct-q4_K_M).

- The first synthetic summary worker call returned in 54.75 seconds but failed
  structural validation. A warm diagnostic returned in 13.09 seconds and also
  failed: several fields used strings instead of cited claim objects.
- The summary request now supplies an explicit JSON schema to Ollama, while
  retaining independent server validation (`summary-v2`). A warm check completed
  in 12.45 seconds with valid structure and reference IDs.
- Manual review still found errors: the model invented a research question and
  misclassified findings and author-reported limitations. Structural success
  therefore did not establish an acceptable summary.
- The existing real Q&A smoke check failed twice. On the diagnostic run, the
  answer replaced the required batch-size value, 64, with a citation marker:
  `The study used a batch size of [1] and 16 training epochs. [1]`
- The candidate was not adopted as the workspace default. The test model remains
  downloaded for reproducibility; at that stage the application retained `llama3.2`.

These are narrow synthetic checks, not a general model benchmark. Elapsed
summary time includes the worker and local inference call. The failed larger
model runs did not produce a successful comparable timing. Reports are under
`.cache/summary-1b-q4-*.json`; they contain synthetic data only.

1. Reproduce the reported slow question and measure each stage, cold and warm.
2. Check Docker GPU visibility and Ollama's actual CPU/GPU split; measure memory.
3. Bounded BM25 caching is implemented; measure its effect on repeated searches.
4. Compare optional resource profiles and record speed, memory, and quality
   tradeoffs before selecting settings.

References: [Ollama Docker setup](https://docs.ollama.com/docker),
[context length and offloading](https://docs.ollama.com/context-length), and
[model keep-alive and parallelism](https://docs.ollama.com/faq).

## Verified NVIDIA profile — 20 November 2026

The existing pinned Ollama image passed `nvidia-smi` with Docker GPU access.
`compose.workspace.gpu.yaml` adds `gpus: all`; use it together with the base
Compose file. No model, data volume, or database change is required.

With the original `llama3.2` model and a 2048-token summary context, Ollama logged
29/29 model layers offloaded (about 1918 MiB GPU model buffer plus a 308 MiB host
buffer). The real one-passage summary check completed in **37.46 seconds**. Its
saved findings correctly retained batch size 64, 90 percent accuracy on a synthetic
dataset, and small sample size; unsupported question/approach fields stayed empty.
The real Q&A smoke check also reproduced batch size 64 and 16 epochs with valid
references. Its generation request took about 51 seconds. At its 4096-token
context, `ollama ps` reported 20% CPU / 80% GPU and about 2.9 GB total allocation.

These successful narrow checks resolve the previous pending live checks; they
do not establish a universal accuracy or latency target. The previous CPU runs
timed out during loading, so no equivalent successful CPU run exists from which
to calculate a speedup. A GPU does not eliminate host RAM pressure.

## Final retrieval run and RAM pressure — 21 November 2026

The 37-question fictional corpus includes 34 answerable retrieval cases and three
unanswerable questions. All four retrieval modes completed against real embeddings,
pgvector, BM25, and the cross-encoder. The saved report is
`eval/workspace_results.json`; source-level Recall@3 / MRR@3 / nDCG@3 are documented
in `EVALUATION.md`. Unanswerable questions are deliberately excluded from retrieval
scores and require separate answer/abstention review.

Windows reported only about **65 MB free physical RAM**, with roughly 4.3 GB in
the Memory Compression process, during the final benchmark. Project servers were
paused to reduce contention. Stack samples showed both expensive cold
PyTorch/Transformers imports and time inside real embedding inference. These
observations support memory pressure as a bottleneck in this run; they do not
prove what caused the user's earlier slow question.

The run used `TOKENIZERS_PARALLELISM=false`, `RAYON_NUM_THREADS=1`, and
`OMP_NUM_THREADS=2`. These conservative defaults are supplied in `.env.example`
and loaded before retrieval model imports without overriding explicit environment
values. They reduce thread oversubscription, not the models' memory requirements.
Measured warm means were dense 2.904 s, BM25 0.089 s, hybrid 0.266 s, and reranked
12.194 s. Memory pressure changed during the sequential modes, so these are
diagnostic observations, **not a controlled comparative speed benchmark**.

For an 8 GB machine, keep one worker, close unnecessary workloads, run builds and
benchmarks separately, retain bounded contexts and a bounded BM25 cache, and use
the verified GPU profile where supported. With adequate RAM/VRAM, keep the same
quality checks while testing larger contexts, model sizes, or concurrency one
change at a time. Faster 1B output remains unsuitable when it fails factual checks.

## Release inference profile and runner memory — 21 November 2026

The release candidate is `qwen3:4b-instruct-2507-q4_K_M` (manifest prefix
`0edcdef34593`). The tested host profile uses 2048 Q&A context tokens, prompt batch
128, a 300-second cold-start timeout, and 15-minute model retention. Explicit
`OLLAMA_GPU_LAYERS=99` placed it fully on the RTX 3050 Laptop 4 GB GPU, at roughly
2.8 GB allocation. This setting is optional; leave it unset on unverified hardware
or for automatic/CPU placement. Summary synthesis uses a larger context, so its
placement must be checked separately.

A sustained answer run then failed with a CUDA error while Windows had about
42 MB free physical RAM. The runner log showed eight old prompt states occupying
roughly 787 MiB, with an 8192 MiB cache limit. This identifies avoidable memory
retention, but does not prove that it alone caused the CUDA error. The Compose
profile now disables this host prompt cache (`LLAMA_ARG_CACHE_RAM=0`) and context
checkpoints (`LLAMA_ARG_CTX_CHECKPOINTS=0`), and allows one loaded model and one
parallel request. Model weights and application evidence are unchanged. The
runner's old-prompt cache is distinct from the application's bounded BM25 cache.

The pinned runner's `--help` documents these environment controls. They are also
described in the [upstream server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
For machines with adequate host RAM, `WORKSPACE_OLLAMA_CACHE_RAM_MB` can enable a
bounded old-prompt cache; measure sustained memory and answer quality before
changing the default. Keep inference, builds, and retrieval benchmarks sequential
on an 8 GB host. A fully GPU-offloaded model still consumes host memory.

With that cache disabled, all 37 answer replay cases completed without another
CUDA error. The final warm run's median generation-only time was 1.32 seconds;
this excludes retrieval and queue time and does not imply comparable real-paper
latency. A real three-passage `summary-v3` check completed in 23.33 seconds with
the model warm. All six calls stayed at 2048 tokens. Its saved summary retained
batch size 64, the reported 90 percent accuracy, and the author-reported small
sample limitation with original references. An earlier cold run took 159.61
seconds. The pre-guard synthesis had dropped the findings dimension; the server
now retains a validated mapped claim when synthesis empties a reported field.

The original fixed-4096 synthesis check also completed, at 100% GPU and roughly
3.1 GB allocation, but took 230.32 seconds including a context-size reload. The
dynamic context choice avoids that reload for concise synthesis inputs. Longer
summaries can still need 4096 tokens; no universal speedup or exhaustive summary
coverage is established by these narrow fixtures.

## Completion measurements — 22 November 2026

Both development and independent validation retrieval reports were recomputed
with Ollama stopped. Windows still reached roughly 15 MB free physical RAM.
The final generation runs were separated from retrieval model loading: first
development request 75.42 seconds cold, subsequent median 1.49 seconds; validation
median after the first case 1.30 seconds with the model warm. See `EVALUATION.md`
for support and abstention outcomes. These are generation-only timings.

The application now persists initial queue wait before attempting retrieval,
retains that value across retries, and exposes retrieval/rewrite and latest
generation/evidence-check durations under **Processing times**. Its application
and PostgreSQL clocks differed by about 0.01 seconds during verification.
Recorded stages can come from different attempts; they do not measure browser
transport/polling or provide a complete total across failures. Use these fields
to investigate an actual slow question before choosing further optimizations.
