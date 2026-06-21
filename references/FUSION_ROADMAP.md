# Fusion roadmap

> Working roadmap built from the idea dump + the live backlog. Organized as **clusters** (the map) and
> a **recommended sequence** (the route). Tags: **effort** T/M/L (trivial/moderate/large) ·
> **invariant** = relationship to the `turn.text`-only forward-context rule (safe = display-only, out
> of context like the margin; turn.text = legitimate forward content; **sensitive** = consciously
> touches/extends the rule) · **deps** = what it needs first. Phase numbers deliberately not assigned —
> they'd go stale; pick from a wave and number it when you build it.

---

## Already landed / resolved (the pile is smaller than it looks)
- **Draggable composer / "pull up the bar to type"** → built (Phase 20.5).
- **"Does OR give cost via API, even retrospectively?"** → yes: `usage.cost` is returned inline in
  every response automatically, plus a retrospective `/generation` lookup. Feeds the cost feature.
- **Per-room reasoning-effort dial** → built (Phase 20). The note just wants it in converse mode too (a
  trivial extension — see Wave 1).
- Context: theming, model-status bar, truthful model pill, per-panelist web search — all built.

---

## The map (six clusters)

### Cluster 1 — Surface wins (cheap awareness + UX)
| Item | Effort | Invariant | Deps / notes |
|---|---|---|---|
| Real cost per model / chat (`usage.cost`) | M | safe | OR returns it; model-bar cost slot already built. **Front-runner.** |
| Copy button on output | T | safe | — |
| Effort level in converse mode | T | safe | effort dial (built) |
| Per-model context gauge (colour ring per tile) | M | safe | each model's fill vs *its own* window; trigger surface for per-model compaction |
| OR model dropdown under providers, live from `/models` | M | safe | reuses Phase 20's `/models` fetch — data's already there |

### Cluster 2 — Structured multi-model modes (the vision core)
| Item | Effort | Invariant | Deps / notes |
|---|---|---|---|
| Divergence/agreement synthesis (judge emits structured, source-attributed, cross-panelist map) | M | turn.text | research mode (exists). **Front-runner** — the thing Abacus structurally *can't* do. |
| Side-by-side: one prompt → two models, adjudication = a diff | M | safe | a 2-pane mode + diff render; the lightweight, mechanical cousin of synthesis |
| Personas / roles per seat + templates (e.g. the 5-expert-perspectives preset) | M | safe | per-seat **system prompt**, invisible to other panelists. Optional, default off. Sets up debate. |
| "Yes-and" pattern (answer → build-on → you) | M | turn.text | a turn-flow variant |
| Auto debate-loop until a conclusion (multi-model `/loop`; define output + turn cap) | L | turn.text | termination logic; **richer with personas/roles**. The marquee autonomous mode. |

### Cluster 3 — Files & multimodal
| Item | Effort | Invariant | Deps / notes |
|---|---|---|---|
| Inline `.md`/`.txt` drop | — | turn.text | **in flight (Phase 22)** |
| `.md` artifact *out* (a model emits a spec file you can grab) | M | safe | extract/render a `.md` block from turn.text. Directly serves your CC-spec workflow. |
| **Unpacker-model pattern** (one capable model describes a file/image into a turn for the others) | M | turn.text | a vision/file-capable seat (available post-20). **The general solution to non-text input across a mixed panel.** |
| Image paste / document load | M | turn.text | rides the unpacker pattern for non-multimodal seats |
| Room types (gate models by capability) | T/M | safe | minor; folds in alongside the above |
| Managed file library (toggleable context prefix) | M/L | safe* | inline proven first. *Prefix block, not a turn — sits alongside `build_context`. **Prereq for projects.** |
| Projects (a project = multiple rooms + shared files) | L | safe* | managed library first. Folds into rooms-as-folders (project folder + shared `files/`). North star. |

### Cluster 4 — Navigation & visualization
| Item | Effort | Invariant | Deps / notes |
|---|---|---|---|
| **Per-turn summary infra** (a utility summarizer) | M | safe | none. **Infra unlock** — feeds the summary bar, trajectory labels, *and* seeds compaction. Build it deliberately. |
| Running per-turn summary bar (scrollable) | M | safe | summary infra |
| Trajectory graph (vertical lines, swerve-to-speaker brighter, margin rail with horizontal connectors, click-to-jump) | L | safe | summary infra (labels) + click-to-jump wiring. Signature viz; spec is detailed; wants some real use to validate the swerve/round semantics. |

### Cluster 5 — Persistence & context continuity (the capstone)
| Item | Effort | Invariant | Deps / notes |
|---|---|---|---|
| **Per-model compact-and-swap** (when one model's context fills, the margin model compacts *its* history and a fresh instance continues; other seats keep going) | L | **sensitive** | per-model gauge + summary infra. Feeds a *derived* summary forward — conscious invariant design. Lets any-context-length models coexist and run indefinitely. Keystone. |
| **SQLite + FTS5 retrieval index** (derived, searchable index over the canonical JSONL; pull relevant past `turn.text` on demand) | L | safe* | *indexes/retrieves `turn.text` only — invariant-consistent; **not** semantic RAG (transparent keyword FTS). JSONL stays source of truth; the DB is a rebuildable index, not a replacement. **Complements** compaction: retrieval = on-demand detail, compaction = always-present gist. Largest single step. |
| Hermes-style persistent memory for project rooms | L | sensitive | projects + the two above. Reduces handoff pressure. |
| ~~Sandboxed folder read/write~~ | — | — | **Reframed away** — agent-harness drift. The real need under it (persistent memory / context carryover) *is* the two mechanisms above. Don't build the file sandbox. |

### Cluster 6 — IDE mirror (small, standalone)
| Item | Effort | Invariant | Deps / notes |
|---|---|---|---|
| Read-only Claude Code progress mirror + a "bring up VS Code" launch button | M | safe | needs CC to emit a tailing log/status (feasibility check first). The right *small* version of the embed you wanted. |

---

## The route (recommended build sequence)

Vision-forward, but each wave ships something usable on its own.

**Wave 1 — clear the cheap pile + the two front-runners.** Real cost surfacing; then batch the trivia
(copy button, effort-in-converse, OR model dropdown); context gauge. Cheap, immediate, and the cost +
gauge both feed later work.

**Wave 2 — the vision core (structured modes).** Divergence synthesis first (mostly prompt + render).
Then side-by-side/diff (cheap compare). Then personas/roles + the perspective templates (which set up
the next one). Then yes-and. Then the debate-loop as the marquee. This wave is the heart of
preside-over-many — build out the *modes the room can run*.

**Wave 3 — files & multimodal.** Inline files (22) lands first. Then `.md` artifact-out (serves your
spec workflow). Then the **unpacker-model pattern** — and once that exists, image/doc paste rides it,
and room types fold in. After this the room eats real inputs and emits specs.

**Wave 4 — navigation.** Build the **per-turn summary infra** deliberately (it's the unlock). Then the
summary bar, then the trajectory graph — by now you have long real sessions to validate its semantics
against.

**Wave 5 — the capstone (defeat the context limit).** Two complementary mechanisms: **per-model
compact-and-swap** (refresh a single model when *its* window fills — lets any-context-length models
coexist and run indefinitely) and a **SQLite+FTS5 retrieval index** (detailed, searchable history over
the canonical JSONL — on-demand detail to compaction's always-present gist; transparent keyword search,
not semantic RAG). Then the project stack: managed library → projects → persistent project memory. The
biggest, most invariant-sensitive bet — last by design, after the summary infra exists and real use has
shown where the handoff actually hurts. (FTS5 is the largest single step; sequence it once compaction
alone proves insufficient for the detail you need to retrieve.)

**Standalone — slot when ready.** The CC progress mirror, once you've confirmed CC can emit a log to
tail.

---

## Cross-cutting notes

- **Infra unlocks (build deliberately — each opens a cluster):** (1) per-turn summarizer → summary bar
  + trajectory + compaction; (2) the unpacker-model pattern → all non-text input; (3) managed library
  → projects.
- **Invariant-sensitive set = exactly one cluster:** persistence (compaction + persistent memory).
  Everything else is display-only (out of context like the margin) or legitimate `turn.text`. Personas
  are per-seat system prompts — invisible to the other panelists, so no leak.
- **The reframe:** the folder-sandbox instinct is the road not taken; its real need is the persistence
  capstone. Scratch the itch there.
- **Wants real use before finalizing:** the trajectory graph's swerve/round semantics, and compaction.
  You can sequence toward both, but lock their details after a few weeks of real sessions.
- **Already deferred, now placed:** managed library + projects (Wave 5 stack), margin-intake bookmarklet
  (independent, slot anytime), client-side Grok search loop (trigger = OR-Grok cost bites).
