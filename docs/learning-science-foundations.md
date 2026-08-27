# Learning-Science Foundations

**Keating's scientific charter.**

This document states what the learning-science evidence supports, what it does
not, and the design commitments that follow. It is written to outlive any
particular course, codebase, or model generation, and therefore contains no
roadmap, no implementation status, and no product plan — only the science and
the commitments it warrants.

---

## 1. Purpose, scope, and conventions

### 1.1 What Keating is

Keating is not an AI tutor. The "AI can explain things well" problem is treated as solved and is not the product. Keating is a **platform for AI-assisted learning**: the learner remains responsible for learning; the tool helps them organize, contextualize, and deepen it. The goal is *deepening* — durable, well-consolidated memory and transferable understanding (in Bjork's terms, storage strength) — and explicitly **not** accelerating or time-compressing learning. Every design decision is evaluated against that goal.

The platform's constitutional split, derived in §2.3 and stated as P1 below: **the learner performs the operations of learning; the platform performs the logistics.** Retrieval, generation, explanation, evaluation, and monitoring stay with the learner, because the memory trace forms in whoever does the work. Schedules, records, source-tracking, and canonical references are offloaded onto a store the learner can trust, because reliable saving demonstrably frees capacity for the next thing.

### 1.2 How to use this charter

- **§2 is the evidence.** Five domains of learning-science findings, each stated with its effect size, its boundary conditions, and its design translation. Read it when you need to know *why* a rule exists or how far it extends.
- **§3 is the operative part.** Twenty-five numbered design principles, cited throughout the project as **P1–P25**. These are the commitments the platform is held to.
- **§4 is the source list**, flagged by evidence quality.

**Precedence.** Where this charter and a convenience conflict, the charter wins. Where this charter and the teaching policy conflict, the charter is the more fundamental document and the policy should be amended to match. Section numbers (§2.1–§2.5) and principle numbers (P1–P25) are stable identifiers: cite them, and do not renumber them without updating every referring document.

**Amendment.** A design change that contradicts a principle in §3 must either cite newer evidence or amend this charter first. Amendments state what changed, which claim it rests on, and which principles move. A principle removed because the evidence eroded should be recorded as such rather than deleted silently — the reason a rule was abandoned is itself worth keeping.

### 1.3 Conventions and evidence standard

The findings below were adversarially verified against primary sources: claims checked against full texts or abstracts wherever reachable, refuted claims dropped, corrected claims used in their corrected form. Effects that could not be verified are marked as such in place.

- Effect sizes are Cohen's *d* or Hedges' *g* (roughly interchangeable at these magnitudes; 0.2 small, 0.5 medium, 0.8 large).
- **[Contested]** marks findings the field genuinely disputes. They are never presented as settled.
- **[Preprint]** marks work that has not passed peer review. It is used only as convergent support, never as a load-bearing citation.
- Boundary conditions are stated where they matter, because most of what goes wrong in learning products is applying a real effect outside its boundary.

---

## 2. What the science prescribes

### 2.1 Durable encoding: retrieval, spacing, interleaving

#### Retrieval practice is the foundation

Practicing retrieval of studied material produces substantially better long-term retention than restudying it for the same time — the testing effect. This is among the most robust findings in psychology, supported by four independent meta-analyses: g = 0.50 [0.42, 0.58] vs. restudy across 61 studies (Rowland 2014, https://doi.org/10.1037/a0037559); g = 0.61 vs. all controls (Adesope, Trevisan & Sundararajan 2017, https://doi.org/10.3102/0034654316689306); g = 0.499 across 222 studies and 48,478 students in real classrooms (Yang, Luo, Vadillo, Yu & Shanks 2021, https://doi.org/10.1037/bul0000309); 57% of 49 classroom effect sizes medium or large (Agarwal, Nunes & Blunt 2021, https://doi.org/10.1007/s10648-021-09595-9).

The critical boundary: **the effect grows with retention interval and reverses at very short delays.** In Roediger & Karpicke (2006, https://doi.org/10.1111/j.1467-9280.2006.01693.x), restudy beat testing at 5 minutes (83% vs. 71%) but testing won decisively at 1 week (61% vs. 40%). Any feature evaluated on end-of-session performance will be evaluated wrong — the ranking of techniques literally flips between session end and one week out.

Retrieval also beats popular "active" elaborative techniques, not just passive restudy: closed-book retrieval outperformed elaborative concept mapping on a 1-week test, including on inference questions, and held even when the final test *was* concept-map creation (Karpicke & Blunt 2011, https://doi.org/10.1126/science.1199327; independently replicated by Lechuga, Ortega-Tudela & Gómez-Ariza 2015, https://doi.org/10.1016/j.learninstruc.2015.08.002). The published methodological debate around this study turns largely on open-book vs. closed-book elaboration — elaboration performed *from memory* is itself a retrieval event, which is precisely the design lesson.

Across the ten most common study techniques, the systematic evidence review of Dunlosky, Rawson, Marsh, Nathan & Willingham (2013, https://doi.org/10.1177/1529100612453266) rates practice testing and distributed practice highest-utility; elaborative interrogation, self-explanation, and interleaving moderate; and the techniques learners default to — rereading, highlighting, summarization — low utility ("low" meaning low generality of benefit, not proven harm).

#### Performance during practice is a misleading — often inverted — signal

Conditions that raise current accessibility fastest (massing, blocking, restudy) often build durable learning slowest, and vice versa. This is the central dissociation of Bjork's new theory of disuse (Bjork & Bjork 1992; Soderstrom & Bjork 2015, https://doi.org/10.1177/1745691615569000): current performance is "an unreliable index" of the changes that support retention and transfer. It is a theoretical framework rather than a single measured effect, but the dissociation pattern itself — massed/blocked practice inflating immediate performance while spaced/interleaved/tested practice wins at delay — is among the most replicated patterns in the field, and it appears independently in the spacing, interleaving, and testing literatures below.

Design consequence: the platform needs *two* learner-facing constructs — "accessible now" (session performance) and "durable" (delayed-retrieval history) — and must never present in-session streaks as evidence of learning.

#### Difficulty is desirable only when it is overcome

A retrieval difficulty helps only when the attempt succeeds or is followed by corrective feedback. The experimentally verified pieces: without feedback, low-success recall practice loses its advantage (Kang, McDermott & Roediger 2007, https://doi.org/10.1080/09541440601056620); failed retrieval helps only when the answer is presented afterward (Kornell, Hays & Bjork 2009, https://doi.org/10.1037/a0015729); feedback benefits both correct and incorrect responses (Butler, Karpicke & Roediger 2007, https://doi.org/10.1037/1076-898X.13.4.273). Rowland (2014) reports moderator values suggesting feedback plus low success yields the *largest* benefits (g up to ≈ 0.99), but those success-band cutoffs come from a correlational between-study moderator analysis whose table values could not be re-verified against the paywalled text — so the operational rule the platform adopts is the experimentally supported one: **always show the correct answer after every attempt**, rather than tuning to precise success bands.

On feedback timing: moderately delayed feedback beat immediate feedback on a 1-week test (.70 vs. .60, d = .47; Butler, Karpicke & Roediger 2007), but the authors attribute this to spacing, and Smith & Kimball (2010, *JEP:LMC* 36(1), 80–95) found the delay-retention effect largely disappears when the feedback-to-test interval is equated — the delayed-feedback advantage is best understood as **spaced re-exposure**, and it presupposes learners actually process the delayed feedback, which applied studies show often fails to happen. Design translation: give immediate feedback on every attempt, and additionally re-present misses as a spaced retrieval event ("review your misses" hours later) that requires re-answering, never a dismissible banner.

#### Retrieval must repeat, to a criterion

One correct recall is not learning. Once an item has been recalled, additional *restudy* adds almost nothing, while continued *retrieval* roughly doubles delayed recall; dropping items from testing after one correct answer devastated retention (~80% vs. 36% at one week; Karpicke & Roediger 2008, https://doi.org/10.1126/science.1152408). The durability/efficiency sweet spot: about 3 correct recalls in initial learning, then relearning to criterion about 3 more times at widely spaced intervals — "successive relearning" (Rawson & Dunlosky 2011, https://doi.org/10.1037/a0023956; Rawson & Dunlosky 2022, https://dx.doi.org/10.1177/09637214221100484), which boosts real high-stakes exam performance when embedded in courses (Janes, Dunlosky, Rawson & Jasnow 2020, https://doi.org/10.1002/acp.3699).

#### Pretesting: attempts before exposure potentiate learning

Attempting questions *before* studying enhances learning of the pretested content — even when the attempt is guaranteed to fail — provided the correct answer is studied afterward (Kornell, Hays & Bjork 2009, https://web.williams.edu/Psychology/Faculty/Kornell/Publications/Kornell.Hays.Bjork.2009.pdf, whose Experiments 1–2 used unanswerable fictional questions; Richland, Kornell & Kao 2009, https://doi.org/10.1037/a0016496). Meta-analytically: g = 0.66 for prequestioned information but g = 0.01 for non-prequestioned information (King-Shepard et al. 2025, https://doi.org/10.1007/s10648-025-10075-7) — pretests are content-specific and do not potentiate untargeted material. Pretest errors do not harm learning when followed by correct-answer study (Pan & Carpenter 2023, https://doi.org/10.1007/s10648-023-09814-5). Design translation: open every lesson section with attempt-first questions covering the *specific* points the section teaches, require a committed guess, reassure that errors here are productive, always follow with the answer.

Retrieval also potentiates what comes *after* it: interpolated testing between content blocks improves encoding of subsequent new material (forward testing effect; Chan, Meissner & Davis 2018, https://doi.org/10.1037/bul0000166 — with the caveat that interference-prone material can reverse it), and interpolated quizzes during lectures reduced mind wandering, increased note-taking, and improved final-segment performance (Szpunar, Khan & Schacter 2013, https://doi.org/10.1073/pnas.1221764110 — lean on the meta-analytic forward effect rather than the mind-wandering mechanism, which has mixed follow-ups). A retrieval attempt before re-exposure amplifies what the re-exposure delivers (test-potentiated restudy; Arnold & McDermott 2013, *JEP:LMC* 39(3), 940–945). Segment content; quiz after each segment; force a retrieval attempt *before* re-displaying anything the learner has seen before.

#### Format: recall beats recognition, and feedback narrows the gap

Recall-format initial tests yield larger testing effects than recognition tests (Rowland 2014, abstract-level verified). Without feedback, multiple choice can beat short answer simply because unaided short-answer success is low; with feedback the ranking reverses and short answer wins (Kang et al. 2007). In real classrooms both formats work (McDermott et al. 2014, https://pdf.retrievalpractice.org/guide/McDermott_etal_2014_JEPA.pdf). Since an LLM can grade open responses cheaply, the platform's default should be type-an-answer recall with automatic feedback; multiple choice is used deliberately (plausible, competitive distractors — which themselves induce retrieval; Little et al. 2012) rather than as the lazy default. Feedback also neutralizes the classic worry about MC lures (Butler & Roediger 2008, https://doi.org/10.3758/MC.36.3.604).

#### Transfer: testing buys it, at about half strength, if you design for it

Test-enhanced learning transfers to new inference questions, rearranged contexts, and different formats at d = 0.40 [0.31, 0.50] against re-exposure controls — greatest across test formats and to application/inference questions, weakest for rearranged stimulus-response items, untested related material, and worked-example problems (Pan & Rickard 2018, https://pdf.retrievalpractice.org/transfer/Pan_Rickard_2018.pdf, 192 transfer effect sizes, N = 10,382). Moderators: response congruency, *elaborated* retrieval practice (broad questions, explanatory feedback), initial test performance. Two design rules follow: vary the surface form of items across repetitions of a concept and include application/inference items, not just definitional recall; and never assume quizzing fact A helps un-quizzed fact B — everything that matters must eventually be retrieved.

**[Contested]** Whether the testing effect shrinks or disappears for highly complex, high-element-interactivity material (multi-step problem solving learned from worked examples) is a live dispute: van Gog & Sweller (2015, https://doi.org/10.1007/s10648-015-9310-x) argue it weakens; Karpicke & Aue (2015, https://doi.org/10.1007/s10648-015-9309-3) rebut that element interactivity was never operationalized or manipulated. The effect is *not* in question for facts, vocabulary, and educationally realistic prose (Yang et al. 2021 spans math and science classrooms), and Pan & Rickard's weak transfer for worked-example problems partially supports the boundary for that material class. The platform's response: sequence by material type (see §2.4 on worked examples), and instrument its own outcomes by content type, because this boundary is exactly where the literature cannot yet answer.

#### Spacing: the most lopsided result in memory research

Distributed practice beats massed practice for equal total study time in 259 of 271 direct comparisons (839 assessments, 317 experiments; overall recall 47.3% spaced vs. 36.7% massed; Cepeda, Pashler, Vul, Wixted & Rohrer 2006, https://augmentingcognition.com/assets/Cepeda2006.pdf). The optimal gap scales with the target retention interval: in the 1,354-participant "temporal ridgeline" experiment, optimal gaps were 1, 11, 21, and 21 days for retention intervals of 7, 35, 70, and 350 days, with optimal-vs-massed gains of +64% recall, d = 1.1 (Cepeda, Vul, Rohrer, Wixted & Pashler 2008, https://files.eric.ed.gov/fulltext/ED505660.pdf). As a rough planning ratio, the optimal gap is about 10–30% of the retention interval at week-to-months horizons, falling to roughly 5–7% at a year.

Two operationally crucial asymmetries, both verified verbatim in Cepeda et al. (2008):

- **Spacing too little costs far more than spacing too much** — accuracy rises steeply with gap, then declines only gradually past the optimum. When uncertain, err longer.
- **Massed study produces "misleadingly high levels of immediate mastery that will not survive the passage of substantial periods of time."** High accuracy immediately after study is diagnostically worthless; "mastered" status must survive a real delay.

The expanding-intervals narrative (1-3-9 days) is folklore beyond the evidence: meta-analytically, expanding schedules perform no better than uniform spacing (g = 0.034, n.s.), while spaced retrieval beats massed retrieval strongly (g = 0.74) (Latimier, Peyre & Ramus 2021, https://link.springer.com/article/10.1007/s10648-020-09572-8). In the classic direct test, expanding won only at 10 minutes; equal spacing won at 2 days; and *delaying the first test* improved long-term retention regardless of subsequent schedule shape (Karpicke & Roediger 2007, https://learninglab.psych.purdue.edu/downloads/2007/2007_Karpicke_Roediger_JEPLMC.pdf). The wins come from (a) spacing retrievals at all, (b) delaying the first re-quiz, (c) adapting to observed performance — not from any geometric progression.

Personalization pays where it matters most: a semester-long classroom experiment found model-based personalized review beat massed study by 16.5% and one-size-fits-all spacing by 10.0% on a cumulative exam 28 days after semester end (d = 1.42 and 0.88), with the advantage concentrated on material introduced *early* in the semester — exactly the material naive schedulers abandon (Lindsey, Shroyer, Pashler & Mozer 2014, https://journals.sagepub.com/doi/abs/10.1177/0956797613504302; single embedded experiment, so moderate confidence). Modern schedulers of the FSRS family are demonstrably better *calibrated* than legacy algorithms (log loss ≈ 0.34 vs. 0.47 for half-life regression across ~10,000 Anki users and ~350M reviews; https://github.com/open-spaced-repetition/srs-benchmark; Ye, Su & Cao 2022, https://dl.acm.org/doi/10.1145/3534678.3539081) — but this is evidence of better recall *prediction* and review-cost efficiency, not evidence that any scheduler produces more durable learning per se. Adopt one for scheduling honesty (an explicit desired-retention knob, per-item stability estimates); do not market it as accelerated learning.

The biological literature supports treating inter-session time as the active ingredient — spaced training drives repeated waves of consolidation signaling that inherently require elapsed time (Smolen, Zhang & Byrne 2016, https://www.nature.com/articles/nrn.2015.18) — though the molecular timescales (minutes–hours) map only partly onto educational ones (days–weeks), so the behavioral literature carries the load. Practical rule either way: no "catch-up mode" that collapses missed sessions into one sitting; reschedule forward, never stack.

#### Interleaving: pay a fluency cost now for discrimination later

Interleaving confusable problem types sacrifices practice-phase fluency for large delayed gains: blocked practicers led during practice (89% vs. 60%) but interleavers won a week later 63% vs. 20% (Rohrer & Taylor 2007, https://link.springer.com/article/10.1007/s11251-007-9015-8 — small lab study); the preregistered 787-student classroom RCT found 61% vs. 38% (d = 0.83) on a surprise test a month later (Rohrer, Dedrick, Hartwig & Cheung 2020, https://gwern.net/doc/psychology/spaced-repetition/2019-rohrer.pdf). The mechanism is discriminative contrast — learning *which* strategy or concept goes with which case — plus embedded spacing.

Interleaving is **not** universally superior. Meta-analytically the overall effect is g = 0.42, but it ranges from g = 0.67 for visually confusable categories and 0.34 for math down to null for expository texts, and *reverses to favor blocking* (g = −0.39) for unrelated word-learning materials (Brunmair & Richter 2019, https://doi.org/10.1037/bul0000209). Interleave within families of confusable concepts; do not interleave arbitrary unrelated content to appear rigorous. Worked example: a comparative-religion course whose central task is distinguishing Buddhist from Hindu/Yogic from Vajrayana from humanistic-psychology framings of overlapping contemplative states is a discrimination problem end to end — exactly the high-between-category-similarity structure where interleaving earns its g = 0.67. The general test is whether a subject's difficulty *is* its confusable neighbors; where it is, interleaving is the highest-value practice format available, and where it is not, blocking may be the better arrangement.

#### Sleep and prior knowledge: modest, real, usable

Post-learning sleep supports consolidation, but keep claims modest: sleep-deprivation-after-learning harms memory at g = 0.277 (with significant publication bias and low power in primary studies; Newbury, Crowley, Rastle & Tamminen 2021, https://pmc.ncbi.nlm.nih.gov/articles/PMC8893218/), and sleep preferentially consolidates material tagged as relevant for the future (Wilhelm et al. 2011, https://www.jneurosci.org/content/31/5/1563). The usable rule: build at least one night of sleep between first exposure and the first scheduled re-quiz — a "learned today, verified tomorrow" rhythm — and let the learner flag material as mission-relevant. Do not gamify late-night streaks.

Prior-knowledge schemas dramatically accelerate integration of congruent new material (behaviorally robust across species; Tse et al. 2007, https://www.science.org/doi/10.1126/science.1135935). The specific neural mechanism (SLIMM's mPFC-vs-hippocampus division; van Kesteren et al. 2012) is contested — its core fMRI predictions failed a 2026 confirmatory test co-authored by a SLIMM author (Raykov et al. 2026, *Phil Trans R Soc B* 381:20250250) — so the platform keeps the claim behavioral: **activate and probe what the learner already knows before new material** (advance organizers, analogies, a quick recall probe), and give schema-*incongruent* facts extra spaced retrievals, since they consolidate more slowly.

**[Contested]** Reconsolidation-based "memory updating/erasure" in humans is unreliable — the replication record for Schiller-style reactivation-extinction effects is roughly evenly split, a highly powered registered replication failed (Chalkia et al. 2020, *Cortex* 129:510–525), and the original result depended on undisclosed participant exclusions (Chalkia et al. 2020, *Cortex* 129:496–509). The defensible, modest residue for education: retrieval with surprising corrective feedback is a privileged moment for modifying stored knowledge — including hypercorrection of high-confidence errors (Metcalfe, Kornell & Finn 2009, https://doi.org/10.3758/MC.37.8.1077). When a learner confidently answers wrong, deliver feedback immediately and re-test on an accelerated schedule. Build no product claims on "memory rewriting."

### 2.2 Generative learning: who makes the artifacts

#### The generation effect is the platform's constitutional principle

Material a learner produces is remembered better than equivalent material merely read: d = 0.40 across 445 effect sizes from 86 studies — "almost half a standard deviation" (Bertsch, Pesta, Wiscott & McDaniel 2007, https://doi.org/10.3758/BF03193441; origin: Slamecka & Graf 1978). Boundaries: generation requires enough prior knowledge to generate *from* (for novel content, the pretesting paradigm covers the gap), and generation directed at one feature can cost memory for non-generated surrounding details — hence generation plus feedback, not generation alone. The lab paradigms are mostly words and sentences; the extension to complex artifacts rests on the convergent generative-strategies literature (Fiorella & Mayer 2015; Fiorella & Mayer 2016, https://doi.org/10.1007/s10648-015-9348-9).

The platform-wide contract this implies: **the learner drafts every learning artifact before the AI reveals its version as a critique target.** An AI that writes the summary, the glossary entry, or the concept map while the learner watches removes exactly the component that makes the activity work.

#### Self-explanation and elaborative interrogation

Prompting learners to self-explain produces a robust medium benefit: g = 0.55 (69 effect sizes; Bisra, Liu, Nesbit, Salimi & Winne 2018, https://doi.org/10.1007/s10648-018-9434-x), persisting in digital environments (g = 0.46 overall, transfer g = 0.33; Tan, Gong, Wang et al. 2025, https://doi.org/10.1007/s10648-025-10001-x). Boundary: timing and cost — bolting self-explanation prompts onto worked examples *reduced* the worked-example benefit in math (Barbieri et al. 2023, https://doi.org/10.1007/s10648-023-09745-1); place prompts at natural pause points and keep them short. "Explain this in your own words / why does this step follow?" is the core interaction primitive, with the AI eliciting before explaining.

Elaborative interrogation — "why would this fact be true?" — improves fact learning at d = 0.56 (Donoghue & Hattie 2021, https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2021.581216/full), largest when the learner has relevant prior knowledge to elaborate from; surface a quick recall of prior knowledge first, then ask why the new fact makes sense given it.

#### Summarization and note-taking: conditional tools, commonly misused

Summarization helps only when summaries are good: d ≈ 0.44–0.50 when trained/guided (Fiorella & Mayer 2016; Donoghue & Hattie 2021), rated low-utility for untrained learners (Dunlosky et al. 2013), and high-ability students showed *negative* effects in moderator analysis. So: summarizing is a scaffolded, feedback-supported activity — learner writes, AI evaluates against the source and coaches revision — and an AI-written summary never substitutes for the learner's own.

Note-taking's encoding benefit is small (positive but modest across 57 studies; Kobayashi 2005, https://doi.org/10.1016/j.cedpsych.2004.10.001); most of its value is in later review (Kobayashi 2006, *Educational Psychology* 26(3), 459–477, https://www.tandfonline.com/doi/abs/10.1080/01443410500342070). Reviewing a complete, well-organized set of notes beats reviewing one's own sparse notes for factual recall (Kiewra's program — noting the foundational 1985 study had n = 23), so the strong arrangement is: learner takes their own notes first (encoding + generation), then a complete canonical reference set is revealed for review. The famous "longhand beats laptop" finding did not survive replication (direct replication and mini meta-analyses across eight studies found no medium effect: Urry et al. 2021, https://doi.org/10.1177/0956797620965541; Morehead, Dunlosky & Rawson 2019, https://doi.org/10.1007/s10648-019-09468-2). What survives is the mechanism: verbatim transcription correlates with shallow processing. Attack verbatim capture directly — block copy-paste into notes, prompt paraphrase — and make no medium-based rules.

#### Concept mapping and learning by teaching

Concept/knowledge mapping yields g = 0.58 overall (142 effects, N = 11,814), and *constructing* a map (g = 0.72) beats *studying* a provided one (g = 0.43) — moderator-level evidence, not a pooled head-to-head, but squarely consistent with the generation principle (Schroeder, Nesbit, Anguiano & Adesope 2018, https://doi.org/10.1007/s10648-017-9403-9). The design pattern: learner draws the map closed-book (making it a retrieval event, per Karpicke & Blunt); the AI compares against a privately held expert map and converts discrepancies into questions; the expert map is offered as a post-construction review artifact.

Preparing to teach yields g = 0.35 and actually teaching after preparation g = 0.56, persisting at delay, with larger effects when the teaching is interactive (Kobayashi 2019, https://doi.org/10.1111/jpr.12221). The protégé effect: learners exert more effort and self-monitor better when responsible for a teachable agent's understanding, with benefits most pronounced for lower achievers (Chase, Chin, Oppezzo & Schwartz 2009, https://doi.org/10.1007/s10956-009-9180-4). "Teach it back" — the AI as curious protégé asking genuine follow-ups — is a strong lesson-closer, as a complement to (not a substitute for) retrieval practice.

#### ICAP: a heuristic, not a law **[Contested at the top]**

The ICAP framework predicts learning increases across engagement modes Passive < Active < Constructive < Interactive (Chi & Wylie 2014, https://doi.org/10.1080/00461520.2014.965823). The Constructive > Active > Passive portion is reasonably supported; the Interactive > Constructive step and the assumption that overt behavior reliably indicates cognitive engagement have failed direct tests (Thurn, Edelsbrunner, Berkowitz, Deiglmayr & Schalk 2023, https://www.nature.com/articles/s41539-023-00197-4). Design translation: default lesson tasks to at least the Constructive tier (learner produces output beyond the presented material), treat AI dialogue as an optional layer without assuming it adds learning over constructive work, and never score engagement from surface behavior (clicks, words typed, time-on-task) — assess the generated content itself.

### 2.3 Metacognition and self-regulation: what must never be offloaded

#### The fluency illusion is systematic, predictable, and fixable

Learners misread easy, fluent processing as learning. Judgments of learning (JOLs) made with the answer in view are inflated (Koriat & Bjork 2005, https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Koriat_RBjork_2005.pdf); perceptual ease inflates JOLs with little-to-no difference in recall (Rhodes & Castel 2008, https://doi.org/10.1037/a0013684); learners' predictions of their own performance were *uncorrelated* with actual performance across conditions ranging 33–80% (Karpicke & Roediger 2008), and repeated-study participants predicted the best retention while performing worst (Roediger & Karpicke 2006). Worse, these wrong judgments causally drive study choices: when JOLs were experimentally dissociated from actual recall, restudy choices followed the illusion (Metcalfe & Finn 2008, https://doi.org/10.3758/PBR.15.1.174), and overconfident learners terminate study prematurely and retain less (Dunlosky & Rawson 2012, https://doi.org/10.1016/j.learninstruc.2011.08.003).

The fix is well-established: **delay the judgment until after a retrieval attempt.** Delayed JOLs are massively more accurate than immediate ones (accuracy advantage g = 0.93 across 112 effect sizes; Rhodes & Tauber 2011, https://doi.org/10.1037/a0021705; Nelson & Dunlosky 1991). Platform rules that follow: mastery estimates come from actual delayed retrieval outcomes, never felt sense of knowing; self-assessment is elicited only after a closed-book attempt, never with the answer visible; and the learner is explicitly shown the gap between their predictions and their delayed performance, because that comparison is what recalibrates.

A closely related null: **perceptual** difficulty is not a desirable difficulty. Disfluent fonts and degraded presentation produce no learning benefit — the original effects failed direct replications — while deflating confidence and inflating study time (Xie, Zhou & Liu 2018, https://doi.org/10.1007/s10648-018-9442-x, with the corrective commentary of Weissgerber, Brunmair & Rummer 2021 confirming the transfer null as the robust part). Friction must be *cognitive* (retrieval, generation, spacing), never cosmetic.

#### Self-regulated learning is teachable and cyclical

Explicit SRL strategy training reliably improves achievement: g = 0.68/0.71 in primary/secondary school, larger with metacognitive reflection (Dignath & Büttner 2008, https://doi.org/10.1007/s11409-008-9029-x); per-domain effects of writing 1.25, science 0.73, math 0.66, reading 0.36 (Donker et al. 2014, https://doi.org/10.1016/j.edurev.2013.11.002); in higher education overall g = 0.38, with feedback on strategy use predicting larger effects and metacognitive-theory-based programs outperforming purely cognitive ones (Theobald 2021, https://doi.org/10.1016/j.cedpsych.2021.101976). The validated frameworks agree learning runs as a recursive loop — forethought, performance, self-reflection (Zimmerman 2002); task definition, goals/planning, enactment, adaptation (Winne & Hadwin 1998; review: Panadero 2017, https://doi.org/10.3389/fpsyg.2017.00422) — whose engine is monitoring one's products against explicit standards. In adult/work-related learning, the constructs with the strongest independent effects are goal level, persistence, effort, and self-efficacy (17% of variance after controlling for ability; Sitzmann & Ely 2011, https://doi.org/10.1037/a0022777).

Self-grading against criteria works as a learning activity: g = .34 on subsequent tests in grades 3–12 (peer-grading similar at g = .29 — the meta-analysis did not test self vs. peer against each other; Sanchez et al. 2017, https://doi.org/10.1037/edu0000190); in higher education g = .455 overall, and crucially *larger when the self-assessment process is explicit and paired with feedback* (g = .664 vs. .213 without; Yan, Wang, Boud & Lao 2023, https://doi.org/10.1080/02602938.2021.2012644). Self-assessment accuracy is imperfect, so it functions as a learning activity — never as the system's mastery ground truth.

#### Goals: specific and difficult, with a critical reversal

Specific, difficult goals beat vague "do your best" goals (d ≈ 0.42–0.80 across the goal-setting literature; Locke & Latham 2002, https://med.stanford.edu/content/dam/sm/s-spire/documents/PD.locke-and-latham-retrospective_Paper.pdf), and proximal subgoals build self-efficacy and interest (Bandura & Schunk 1981). The reversal that matters for a learning platform: on novel, complex tasks, demanding performance-*outcome* goals imposed during early skill acquisition divert attention from strategy discovery and hurt learning, where specific *learning-process* goals help (Winters & Latham 1996, https://doi.org/10.1177/1059601196212007; Kanfer & Ackerman 1989). Early in a topic, goals should be about process ("produce three retrieval attempts on the Part I readings") not outcomes ("score 90%").

**[Contested]** Growth-mindset interventions as a lever: meta-analytically weak (d = 0.08; Sisk et al. 2018, https://doi.org/10.1177/0956797617739704) and best-practice re-analysis finds effects near null (Macnamara & Burgoyne 2023), with the defensible residue being small effects for academically at-risk students (Yeager et al. 2019). Performance-goal effects flip sign by operationalization (normative +.14, appearance −.14; Hulleman et al. 2010, https://doi.org/10.1037/a0018947). The platform ships no mindset module and builds no logic on goal-orientation typologies.

#### Cognitive offloading: the platform's sharpest double edge

This is the literature that defines what an AI-assisted learning platform must *never* do for the learner, and what it *should*.

- Offloading boosts immediate performance while diminishing the internal memory trace of the offloaded material (Risko & Gilbert 2016, https://doi.org/10.1016/j.tics.2016.07.002; Grinschgl, Papenmeier & Meyerhoff 2021, https://doi.org/10.1177/17470218211008060). The effect extends to everyday capture: photographing material impairs memory for it even when photos are deleted immediately (Henkel 2014; Soares & Storm 2018). Two protective boundaries: an explicit learning intention largely offsets the cost even when offloading is forced (Grinschgl et al., Exp 3 — announcing the memory goal is itself protective), and volitional, detail-focused capture can preserve visual memory (Barasch et al. 2017).
- Offloading the *right* things helps: saving already-processed information onto a **trusted** external store frees capacity that measurably improves memory for the next thing studied — saving-enhanced memory — but the benefit vanishes when the store is believed unreliable (Storm & Stone 2015, https://doi.org/10.1177/0956797614559285).
- Offloading decisions are driven by metacognitive *confidence*, not actual ability, with a systematic bias toward over-reliance on external aids (Boldt & Gilbert 2019, https://doi.org/10.1186/s41235-019-0195-y; Sachdeva & Gilbert 2020, https://doi.org/10.1016/j.concog.2020.103024). Calibration training improves offloading decisions only when confidence predictions are paired with performance *feedback* — predictions alone do nothing (Ngai & Gilbert 2026, https://pmc.ncbi.nlm.nih.gov/articles/PMC12982714/).
- **[Contested]** The famous "Google effect" (Sparrow et al. 2011) should not be built on: its Experiment 1 failed the preregistered Social Sciences Replication Project (Camerer et al. 2018, https://www.nature.com/articles/s41562-018-0399-z) and a corrected-protocol replication (2020, https://pmc.ncbi.nlm.nih.gov/articles/PMC7651475/); the saved/erased memory paradigm replicated only when participants had directly experienced that saving reliably worked. The design-relevant residue is exactly that conditionality: *expectations about future access shape encoding*, so the platform must be explicit about what it will and will not remember for the learner.

The synthesis for Keating: offload the **logistics** of learning (schedules, records, source-tracking, canonical references) onto a store the learner experiences as reliable — this genuinely frees capacity — and never offload the **operations** of learning (retrieval, generation, evaluation, monitoring), because the trace forms in whoever performs them.

### 2.4 Calibrated assistance: scaffolding that fades, productive struggle

#### What scaffolding actually is

Scaffolding is not "giving help." Its defining mechanism is a three-part cycle: **contingency** (help calibrated to a live diagnosis of the learner's current level), **fading** (progressive withdrawal), and **transfer of responsibility** (the learner takes over task control) (van de Pol, Volman & Beishuizen 2010, https://doi.org/10.1007/s10648-010-9127-6; Wood, Bruner & Ross 1976). Support lacking these features is not scaffolding in the evidence-backed sense. Contingency has an implementable titration rule with experimental support: after a failure, give slightly *more* specific help; after a success, give *less* next time — contingent tutors produced more independent post-test success than any fixed strategy (Wood, Wood & Middleton 1978; Wood & Wood 1999, https://doi.org/10.1016/S0360-1315(99)00030-5; replicated by Pratt & Savoy-Levine 1998). Boundary worth engineering around: weaker learners under-seek and mis-time help, so a hint button alone is insufficient — proactively offer the next rung on repeated failure.

#### Honest benchmarks: no 2-sigma

Bloom's famous 2-sigma is not a realistic benchmark: the d = 2.0 came from two dissertations that combined tutoring *with* mastery learning, on narrow experimenter-made tests, over ~3 weeks (Bloom 1984). Modern synthesis puts human tutoring at d ≈ 0.79 vs. no tutoring (VanLehn 2011, https://doi.org/10.1080/00461520.2011.611369) and field RCTs of real tutoring programs at 0.29–0.37 SD (Nickow, Oreopoulos & Quan 2024, https://doi.org/10.3102/00028312231208687). Local, curriculum-aligned tests inflate measured effects severalfold over standardized ones (median 0.73 vs. 0.13; Kulik & Fletcher 2016, https://doi.org/10.3102/0034654315581420). The honest prize for excellent tutoring-style interaction is ~0.3–0.8 SD, and the platform's own outcome measures must not be authored by the same pipeline that taught.

Three structural results from the tutoring literature shape the architecture:

1. **Step granularity is the plateau.** Systems giving feedback and hints on each reasoning step reach d = 0.76 — statistically indistinguishable from human tutors (0.79) — while answer-based systems sit near 0.3; going finer than steps adds nothing measurable (VanLehn 2011; ITS meta-analyses converge at g ≈ 0.42–0.66: Ma et al. 2014; Kulik & Fletcher 2016). Interact at the level of the learner's reasoning steps, not final answers, and do not over-invest in micro-dialogue.
2. **Interactivity pays only above the learner's level.** Tutorial dialogue beat reading well-written text only when the material was above the learner's current level; on level-matched content, dialogue conferred no reliable advantage — even for human tutors (VanLehn, Graesser et al. 2007, https://doi.org/10.1080/03640210709336984; single large multi-experiment paper, moderate confidence). Route within-reach content to clean exposition plus retrieval practice; spend the expensive dialogic machinery where the learner is out of their depth.
3. **The active ingredient is what the learner does.** When tutors were suppressed from giving explanations and feedback and restricted to prompting, students learned just as much (Chi, Siler, Jeong, Yamauchi & Hausmann 2001, https://doi.org/10.1207/s15516709cog2504_1); typical human tutors do not perform the deep diagnosis folk theory attributes to them (Graesser, Person & Magliano 1995). The AI's default move is converting would-be explanations into elicitations.

#### Mastery, feedback, and formative assessment

Mastery learning — demonstrated mastery of each unit before progression — raises exam performance by ~0.5 SD (mean ES 0.52 across 108 controlled studies), helps weaker students most, holds at 8-week follow-up (ES 0.71), and works better with stricter thresholds (91–100% criterion: 0.64 vs. 0.49 at 70–80%) (Kulik, Kulik & Bangert-Drowns 1990, https://doi.org/10.3102/00346543060002265; Slavin's 1987 critique — much smaller effects on standardized measures — keeps this at moderate confidence). Boundary: self-pacing depresses completion, so mastery gating must be paired with externally supplied pacing structure (schedules, commitments, check-ins).

Feedback is high-leverage but wildly heterogeneous: d ≈ 0.48 overall, ~0.99 for high-information feedback (task + process + self-regulation) and collapsing toward zero for praise and person-level comments (Wisniewski, Zierer & Hattie 2020, https://doi.org/10.3389/fpsyg.2019.03087; Hattie & Timperley 2007, https://doi.org/10.3102/003465430298487; about a third of feedback effects in the classic synthesis were *negative*, Kluger & DeNisi 1996). The platform codifies a feedback grammar: every piece of feedback states the criterion, the attempt's relation to it (task level), the strategy to try next (process level), and a self-monitoring prompt (self-regulation level) — and never evaluates the person, in either direction.

**[Contested]** Formative assessment's famous 0.4–0.7 SD range (Black & Wiliam 1998) was a narrative synthesis, not a meta-analytic estimate, and does not survive scrutiny at that magnitude; the stricter attempt landed at ~0.20 (Kingston & Nash 2011) but was itself criticized on methodological grounds (Briggs, Ruiz-Primo, Furtak, Shepard & Yin 2012). The defensible position: the average effect is modest and genuinely uncertain (plausibly ~0.2–0.3), and its value lies in the *instructional decisions it feeds*. Frequent low-stakes checks are sensors; their payoff exists only if the system changes what happens next.

#### Expertise reversal and fading

The scaffolds that help novices become redundant and then actively harmful as knowledge grows: meta-analytically, low-prior-knowledge learners benefit from high-assistance instruction at d = 0.51 while high-prior-knowledge learners do better with *low* assistance (d = −0.43) (Tetzlaff, Simonsmeier, Peters & Brod 2025, https://doi.org/10.1016/j.learninstruc.2025.102064, 176 effects, N = 5,924; foundational review: Kalyuga, Ayres, Chandler & Sweller 2003, https://doi.org/10.1207/S15326985EP3801_4). The asymmetry matters: under-helping novices costs more than over-helping experts, so err toward assistance under model uncertainty — but permanent scaffolding caps learners below independent mastery.

*How* you fade matters more than *that* you fade: fixed-schedule fading shows no meta-analytic advantage over never fading (Belland, Walker, Kim & Lefler 2017, https://doi.org/10.3102/0034654316670999 — the fading moderator was not significant across 144 studies; a pilot meta-analysis even found fixed fading *worse* than continuous support, Belland, Walker, Olsen & Leary 2015), whereas **adaptive** fading — driven by each learner's demonstrated understanding — beat both fixed fading and pure problem solving, especially on delayed transfer (Salden, Aleven, Schwonke & Renkl 2010, https://doi.org/10.1007/s11251-009-9107-8; small number of experiments, moderate confidence). Never fade on a timer, session count, or curriculum position; fade per-skill on evidence, and make fading reversible.

#### The assistance dilemma, worked examples, and productive failure

Free access to help gets systematically abused: in the original classroom study, 24% of students gamed the tutoring system at least once and 11% gamed frequently; frequent gamers averaged 44% on the post-test vs. 68% for prior-knowledge-matched non-gamers (Baker, Corbett, Koedinger & Wagner 2004, http://pact.cs.cmu.edu/pubs/Baker,%20Corbett,%20Koedinger%20Wagner_2004.pdf — small original sample, association since replicated across systems with automated detectors). Help-seeking is poorly calibrated in both directions (Aleven & Koedinger 2000), and the "assistance dilemma" — help reduces frustration but can suppress the processing that produces learning — is a central named problem of the field (Koedinger & Aleven 2007, https://doi.org/10.1007/s10648-007-9049-0). Design translation: make the learning path fast and the answer-fetching path slow — genuine attempt before any hint, hints as minimal next rungs, friction before bottom-out answers, and gaming signals treated as diagnosis triggers (sometimes the hint ladder, not the learner, is broken).

For novices on multi-step procedures, cognitive load theory holds: studying worked examples beats unsupported problem solving (g = 0.48 in math across 55 studies; Barbieri et al. 2023; Sweller 1988; Sweller, van Merriënboer & Paas 2019, https://doi.org/10.1007/s10648-019-09465-5), because problem-search consumes working memory without building schemas. Prefer correct examples, and be sparing with add-on prompts during example study (Barbieri's negative moderator).

Pulling the other way — for *conceptual* content with adolescent/adult learners — productive failure works: attempting problems before instruction, then teaching by explicitly comparing student solutions to the canonical one, yields g = 0.36 for conceptual knowledge and transfer, growing to 0.37–0.58 at high design fidelity (Sinha & Kapur 2021, https://doi.org/10.3102/00346543211019105; note co-authorship by the paradigm's originator). The boundaries are genuine reversals, not attenuations: procedural knowledge null (g = −0.03), young children negative (g = −0.09), domain-general skills negative (g = −0.17). The routing rule the platform adopts: **facts, concepts, prose → attempt-first (pretesting, productive failure); novel multi-step procedures → worked examples with faded completion problems, retrieval ramped in as competence grows.** This also respects the contested element-interactivity boundary from §2.1.

#### Multimedia structure: lean, signaled, segmented

Adding interesting-but-irrelevant content to lessons *hurts* learning — the seductive-details effect. Direction is robust across three generations of meta-analysis; magnitude is small (g = −0.33 in Sundararajan & Adesope 2020, https://doi.org/10.1007/s10648-020-09522-4; g = −0.16 in the 2025 multi-level MASEM, https://doi.org/10.1007/s10648-025-10099-z, operating via extraneous cognitive load). A small negative at zero benefit is strictly dominated by omission: no decorative anecdotes, imagery, or humor in lesson bodies; enrichment quarantined outside the core flow. The two structuring principles with the strongest support: **signaling** the material's organization (retention g = 0.53, transfer 0.33, load reduced; 103 studies, N = 12,201; Schneider, Beege, Nebel & Rey 2018, https://doi.org/10.1016/j.edurev.2017.11.001) and **segmenting** into learner-paced chunks with explicit continue actions (small-to-medium retention/transfer gains; Rey et al. 2019, https://doi.org/10.1007/s10648-018-9456-4 — notably a scaffold that does *not* reverse with expertise). The existing lesson format (short, signaled, working-memory-bounded, one consistent stylesheet) already complies; what is missing is the effortful interaction inside it.

### 2.5 What the 2023–2026 AI-learning empirical work adds

This is the platform's most direct evidence base, and it is young: mostly single-site studies, immediate outcomes, and fast-moving models. Its through-line, though, is remarkably consistent — and it is the platform's founding observation.

**Unrestricted AI help inflates practice performance and can damage learning.** In the largest randomized test to date (~1,000 students, Turkish high school math, four sessions), unrestricted GPT-4 access raised assisted practice performance 48% but *lowered* subsequent closed-book exam scores 17% versus never-assisted controls; a guardrailed tutor (teacher-grounded hints, answer-withholding) raised practice 127% and eliminated the harm — but produced no positive exam effect either (Bastani, Bastani, Sungu, Ge, Kabakcı & Mariman 2025, https://www.pnas.org/doi/10.1073/pnas.2422633122). Mechanism: answer-fetching, not misinformation — the model was right 51% of the time and its errors did not predict the decline. And the miscalibration compounds: unassisted-harm students did not perceive worse performance; guardrailed students believed they had done *better* than they had. Two conclusions the platform inherits: guardrails are necessary but only protective — **the durable gains must come from the learner's own generative and retrieval work** — and assisted performance is a vanity metric.

**The performance-vs-learning dissociation recurs across settings.** In a semester-long CS1 RCT (N = 275), both a guarded hint tutor and unrestricted ChatGPT raised exercise scores and lowered frustration and cognitive load, but neither raised conceptual understanding; only the guarded tutor increased intrinsic motivation, while unrestricted AI fostered what the authors call a "comfort trap" (Bassner, Lenk-Ostendorf, Beinstingel, Wasner & Krusche 2026, https://www.sciencedirect.com/science/article/pii/S2666920X25001778). ChatGPT assistance on an essay task improved the essay but produced no knowledge gain or transfer advantage and reduced metacognitive engagement — learners offloaded evaluation and monitoring to the AI ("metacognitive laziness"; Fan et al. & Gašević 2025, https://doi.org/10.1111/bjet.13544). Using an LLM instead of a search engine for inquiry lowered all three kinds of cognitive load and produced measurably weaker scientific reasoning in the resulting arguments (Stadler, Bannert & Sailer 2024, https://doi.org/10.1016/j.chb.2024.108386). AI scaffolding's quality gains vanished when the AI was withdrawn, with explicit self-monitoring checklists only partially sustaining them (N = 1,625; Darvishi, Khosravi, Sadiq, Gašević & Siemens 2024, https://doi.org/10.1016/j.compedu.2023.104967) — so the platform's success criterion is whether quality *survives AI withdrawal*, verified by periodic AI-off checkpoints.

**What prevents the harm is architecture, not abstinence.** Novice programmers (ages 10–17) using an AI code generator during practice structured as alternating generate-then-modify-manually tasks performed better during training with *no* decrement on manual tasks or ~1-week retention tests (Kazemitabaar et al. 2023, https://doi.org/10.1145/3544548.3580919) — the mandatory manual engagement over the same content, not an AI ban, is what protected learning. Converging from the other direction: pedagogy encoded in the prompt (attempt-before-answer, one step at a time, no full solutions, load management) produced roughly double the learning gains of a well-run active-learning physics classroom at Harvard, in less time (0.63 SD by the conservative estimate; N = 194; Kestin, Miller, Klales, Milbourne & Ponti 2025, https://www.nature.com/articles/s41598-025-97652-6) — with the essential caveat that outcomes were *immediate* post-tests, so it demonstrates the lever (encoded pedagogy plus self-pacing and immediate feedback), not durability. LLM-generated hints matched human-tutor-authored hints for immediate learning gains (both significantly beat no-help; no significant difference between sources), but raw generations failed quality checks on 32% of problems before a self-consistency pipeline (Pardos & Bhandari 2024, https://doi.org/10.1371/journal.pone.0304013 — ChatGPT-3.5-era, adult crowdworkers; the AI advantage is authoring cost, not efficacy). And AI amplifying expert pedagogy through humans — Tutor CoPilot suggesting expert moves to live tutors — raised mastery 4pp overall and 9pp for students of the weakest tutors, by shifting interactions toward probing questions and away from answer-giving (Wang, Ribeiro, Robinson, Loeb & Demszky 2024, https://arxiv.org/abs/2410.03017 **[working paper]**).

**Population-scale signals urge caution about availability itself.** Merely offering an LLM assistant in a large online course *reduced* overall exam participation by 4.3pp even though adopters scored higher, with strongly heterogeneous effects across countries (Nie et al. 2025, https://doi.org/10.1145/3698205.3733960). A decade of ALEKS math-practice data shows post-ChatGPT study time on AI-susceptible problem formats fell ~27% among college students while proctored retention-item performance fell ~25% cumulatively (Rismanchian et al. 2026, https://arxiv.org/abs/2605.21629 **[preprint; most authors are ALEKS/McGraw Hill-affiliated — vendor analysis of vendor data]**). Time-on-task compression is a warning signal, not a success metric — which is the empirical footing under the platform's anti-acceleration stance.

**The evidence base itself requires skepticism.** The most-cited "ChatGPT improves learning" meta-analysis (g = 0.867) was retracted in April 2026 over discrepancies including pooling of incomparable studies (Retraction Note: https://www.nature.com/articles/s41599-026-07310-z). The surviving meta-analyses report moderate pooled effects (g = 0.577 across 37 studies, Liu, Zuo & Lu, *JCAL*, https://doi.org/10.1111/jcal.70096; g = 0.670 across 35 studies, *HSSC* 2026, https://www.nature.com/articles/s41599-026-07019-z) on **immediate post-intervention performance in mostly short interventions** — neither reports pooled evidence on delayed retention or transfer, and the primary studies rarely separate assisted from unassisted outcomes. No meta-analytic evidence currently speaks to durable learning from AI assistance. The widely publicized MIT EEG study ("Your Brain on ChatGPT": weakest connectivity, lowest essay ownership, impaired self-quoting in the LLM group) remains a non-peer-reviewed preprint with a small sample and no learning-outcome measure (Kosmyna et al. 2025, https://arxiv.org/abs/2506.08872 **[preprint; contested]**) — usable only as convergent support for learner-drafts-first sequencing, never as proof of harm.

Finally, the field has begun operationalizing pedagogy as an engineering artifact: Google DeepMind's LearnLM program translates learning science into trainable/promptable behaviors (active engagement, productive struggle, no answer dumps, load management, metacognitive deepening) with a seven-benchmark pedagogy evaluation framework rated by expert educators (Jurenka, Kunesch, McKee et al. 2024, v4 2025, https://arxiv.org/abs/2407.12687 **[technical report; preference-based evaluation, no learner-outcome RCT]**). The transferable practice: define the AI's required pedagogical behaviors as a rubric and continuously evaluate against it like a test suite — because generically instruction-tuned models optimize for helpfulness, and in learning contexts helpfulness means answer-giving.

**Synthesis of §2.5 for the platform.** The 2023–2026 work adds four things the classic literature could not: (1) direct causal evidence that the fluent-answer default of modern LLMs damages learning through answer-fetching; (2) evidence that attempt-first guardrails and alternating-manual architectures prevent the damage; (3) evidence that AI assistance systematically corrupts self-assessment, making an independent calibration loop mandatory; and (4) the humbling observation that *nobody yet has evidence about durable retention under AI assistance* — which means a platform that instruments delayed, unassisted retrieval is not just protecting its learner, it is generating evidence the field lacks.

---

## 3. Design principles

The science above, translated into commitments. These are opinionated on purpose; each cites its warrant. They are referred to elsewhere in the project by their **P-numbers**, which are stable.

**P1. The learner performs the operations of learning; the platform performs the logistics.** Retrieval, generation, explanation, evaluation, and monitoring are never offloaded to the AI — the memory trace forms in whoever does the work (Bertsch 2007; Risko & Gilbert 2016; Fan 2025). Schedules, records, source-tracking, and canonical references *are* offloaded onto a store the learner can trust, because reliable saving frees capacity for the next thing (Storm & Stone 2015).

**P2. Retrieval before re-exposure, always.** Any return to previously seen material begins with a closed-book retrieval attempt; only then is the content re-displayed (test-potentiated restudy: Arnold & McDermott 2013; Chan 2018). "Study it again right now" is an anti-pattern, not a feature (Cepeda 2006).

**P3. Answers are gated behind an attempt.** No answer, hint bottom, or solution is ever visible at zero cost — and not merely in the interface: the copy of a lesson a browser receives carries the questions and none of the answers, which the server reads from the package and returns only with a graded verdict. A committed response (typed answer or committed guess, with confidence) precedes every reveal (Bastani 2025; Kornell 2009; Baker 2004). A `<details>` toggle is not a quiz.

**P4. Every attempt gets corrective feedback, and feedback demands a response.** Correct-answer feedback follows every retrieval attempt — this is what makes errors safe and hard items productive (Kang 2007; Butler 2007; Pan & Carpenter 2023). Feedback on misses is re-presented later as a spaced retrieval event requiring a re-answer, never as a dismissible banner (Smith & Kimball 2010).

**P5. Spacing is a first-class scheduler, not a suggestion.** Every item carries per-learner practice state; review timing derives from the retention horizon ("when must you still know this?" — the exam this term, the professional practice years out, indefinitely), with first gaps at roughly 10–30% of that horizon and errors resolved toward the longer gap (Cepeda 2008). Missed sessions reschedule forward; there is no catch-up mode that stacks reviews into one sitting (Smolen 2016; behavioral spacing corpus).

**P6. Nothing is "mastered" after one success.** Criterion is ~3 successful spaced recalls plus relearning to criterion in ~3 later widely spaced sessions; graduated items decay back into the queue (Karpicke & Roediger 2008; Rawson & Dunlosky 2011). Mastery gates use a high bar (≥90%) with re-testing (Kulik 1990).

**P7. Two dashboards, never conflated: "accessible now" vs. "durable."** In-session performance and streaks are displayed as exactly that; the primary progress signal is the delayed-retrieval trajectory (Soderstrom & Bjork 2015). The platform pre-commits learners to the fluency dip of interleaved and spaced practice by showing the delayed curve, not session accuracy (Rohrer 2020).

**P8. The learner writes the glossary entry; the AI critiques it.** All learning artifacts — glossary definitions, summaries, concept maps, notes, teach-backs — are drafted by the learner first, closed-book where feasible (making them retrieval events: Karpicke & Blunt 2011), then diffed against the AI's privately held version, with discrepancies converted into questions (Schroeder 2018; generation effect d = 0.40). An artifact the AI wrote is documentation, not evidence of learning.

**P9. Elicit before explain.** The AI's default response to a question in scope of current material is a calibrated prompt for an attempt, prediction, or self-explanation; every AI explanation ends in a prompt for the learner to generate something from it (Chi 2001; Bisra 2018). Interactive dialogue is spent where material is above the learner's current level; within-reach content gets clean exposition plus retrieval (VanLehn 2007).

**P10. Attempt-first lesson openings.** Every lesson and section opens with pretest questions targeting the specific content it teaches, answered with a committed guess before the content appears, always followed by the answer (Kornell 2009; King-Shepard 2025).

**P11. Route by material type.** Facts, concepts, and prose: quiz from the start, attempt-first throughout. Novel multi-step procedures: worked examples and completion problems first, retrieval ramped in with competence (Barbieri 2023; Sinha & Kapur 2021; the contested element-interactivity boundary is handled by instrumenting our own outcomes by content type).

**P12. Interleave confusable neighbors; block the unrelated.** Practice sets mix current material with related older material so consecutive items force discrimination between confusable framings (traditions, vocabularies, theorists); arbitrary unrelated mixing is avoided (Brunmair & Richter 2019). In meaning-heavy subjects the highest-value items are those that force a choice between neighboring framings — which tradition, school, or theorist treats X this way — because that discrimination is the learning.

**P13. Calibration is captured, closed-loop, and shown.** Confidence is elicited before every reveal (never with the answer visible; Koriat & Bjork 2005), predicted-vs-actual is fed back to the learner (prediction without feedback does not improve calibration: Ngai & Gilbert 2026), and high-confidence errors trigger immediate feedback plus an accelerated re-test schedule (Metcalfe 2009).

**P14. Assistance is contingent, faded on evidence, and reversible.** Help arrives as the minimal next rung of a graded ladder — up a rung after failure, down after success (Wood & Wood 1999) — pitched to measured (never self-reported) topic-specific competence, with worked examples early and bare problems late (Tetzlaff 2025), faded per-skill on demonstrated understanding rather than on any schedule (Salden 2010; Belland 2017), restored when performance degrades, and proactively offered on repeated failure because weak learners under-seek help.

**P15. The fast path to an answer is slow; the learning path is fast.** Attempt-gating, minimal-rung hints, and friction before bottom-out answers, with gaming detection treated as a diagnostic signal about learner *and* content (Baker 2004; Koedinger & Aleven 2007).

**P16. Feedback follows the grammar: criterion, task, process, self-regulation — never the person.** Every evaluation states where the learner is going, how the attempt relates to the criterion, what strategy to try next, and a self-monitoring prompt; praise and person-level comments are excluded in both directions (Hattie & Timperley 2007; Wisniewski 2020).

**P17. Beautiful finished lessons are a fluency-illusion risk — build effortful interaction into them.** Lessons stay lean (no seductive details: Sundararajan & Adesope 2020), signaled and segmented (Schneider 2018; Rey 2019), but every lesson embeds attempt-gated retrieval, and polish is never allowed to substitute for measured retention. Friction is cognitive, never cosmetic (Xie 2018; the disfluent-font literature's failed replications).

**P18. Frequent low-stakes checks are sensors, not scores.** Formative checks exist to change what happens next — reteach, adjust difficulty, schedule review (Black & Wiliam 1998, at the modest magnitude the evidence supports); their results feed the scheduler and the ZPD model, not a grade.

**P19. The canonical measure of learning is delayed, unassisted performance.** Assisted performance, artifact quality under assistance, session accuracy, and time-to-completion are all vanity metrics (Bastani 2025; Fan 2025; surviving ChatGPT metas measure only immediate performance). The platform runs periodic AI-off checkpoints — the weekly check puts the teaching agent away for its duration, and the attempt records that it did — and reports the assisted-vs-unassisted gap over items answered both ways (Darvishi 2024). Availability is what is recorded, not inferred use: a gap built on guesses about whether help was consulted would be one more vanity number. Falling time-on-task is a warning signal, not a win (Rismanchian 2026, with its vendor caveat).

**P20. Deepening, not accelerating — structurally.** At least one night of sleep between first exposure and first verification ("learned today, verified tomorrow"; Newbury 2021). Goals early in a topic are process goals, not outcome goals (Winters & Latham 1996). Retention horizons come from the learner's mission, which routinely outruns the course calendar; the scheduler honors the mission's horizon, not the term's end.

**P21. The learner's self-regulation is trained, not replaced.** The platform runs the plan–do–review loop *with* the learner — weekly mission review against the "Success looks like" bullets, strategy feedback, reflection prompts (Zimmerman 2002; Theobald 2021) — and requires the learner's own evaluation step before the AI critiques (Yan 2023; Fan 2025). Self-assessment is a learning activity, never ground truth.

**P22. The wisdom loop closes.** What happened in the seminar, in office hours, in the practice community — disagreements, surprises, feedback — is prompted for and captured back into learning records, because real-world signal about understanding must re-enter the system that computes what to teach next (communities of practice; an always-available, never-uncomfortable AI must not be allowed to outcompete the community tier).

**P23. Pedagogy is a tested engineering artifact.** The AI's required behaviors (attempt-first, minimal rungs, no answer dumps, feedback grammar, elicit-before-explain) live in a rubric run against real turns with a real model, asserting what the reply does rather than what the prompt says (Jurenka 2024; Kestin 2025 shows the prompt is the lever). It is opt-in rather than continuous, because it spends money: run it when the prompt or the policy changes, which is when the behavior can regress with nothing else failing. Its checks are structural, not judged — a judge model would add a second non-determinism to grade the first — and a single failure is a transcript to read rather than a proven regression. AI-authored items pass a structural quality check before learners see them: it runs when a lesson is written and reports back to the author in the same breath, and it is exposed as a gate an operator can run over a whole course (Pardos & Bhandari 2024, whose pipeline found a third of raw generations failing). What it checks is whether an item is *gradeable* — a unique id, an answer, a rubric long enough to name variants and misconceptions — not whether it is good; judging that is the rubric evaluation this principle also asks for, and that is not built.

**P24. Claims stay inside the evidence.** No 2-sigma marketing (VanLehn 2011), no memory-rewriting features (the reconsolidation record), no mindset modules (Sisk 2018; Macnamara & Burgoyne 2023), no "AI improves learning" citations from a literature that measures only immediate performance — and the platform's own instrumented outcomes are the evidence base for its next design decision.

**P25. The record is the learner's, and it is never a scoreboard or a monitor.** Two prohibitions, both absolute, both binding on any multi-learner build:

*No leaderboards, cohorts, streaks, or comparative scoring* — in any surface, including opt-in and "just for motivation" forms. Ranking learners against each other rewards exactly the signal P7 establishes as invalid: in-session performance, which dissociates from durable learning and inflates precisely when learning is worst (Soderstrom & Bjork 2015; Roediger & Karpicke 2006, where the condition predicting best retention performed worst). A visible score also converts a record of struggle into something to protect, and the learner's optimal move becomes managing the number rather than attempting the hard item.

*Instructor visibility is a surveillance decision, not a feature.* The practice log records what the learner did not know and when, and every mechanism in this document depends on that record being honest: the scheduler selects from it (P5), the mastery criterion reads it (P6), the ZPD estimate is computed from it (P18), and learning records are gated on it as citable evidence (P1, P21). A learner who believes the log is watched has an incentive to attempt only what they can already do, to prefer the give-up path over a visible wrong answer, and to inflate confidence ratings — which corrupts the calibration loop (P13) at its source. The degradation is silent: the log still fills, the dashboards still render, and every downstream inference is quietly wrong. If instructor visibility is built at all it must be learner-initiated with explicit per-share consent, aggregate rather than per-attempt, never real-time, and revocable with the learner able to see exactly what was shared. Real-time observation of a learner's attempts is out of scope for this platform, not a later phase.

This principle is a design constraint rather than an empirical finding: it follows from the validity conditions the rest of the charter establishes, not from a study measuring surveillance. It is recorded here because a multi-learner build invites both features by reflex, and because a rule that lives only in an issue is a rule that expires when the issue closes.

---

## 4. Sources

Peer-reviewed unless flagged. **[Preprint]** = not peer-reviewed; **[Contested]** = interpretation disputed in the literature; **[Retracted]** noted where applicable.

### Retrieval practice, testing effect, and desirable difficulties

- Adesope, O. O., Trevisan, D. A., & Sundararajan, N. (2017). *Review of Educational Research*, 87(3), 659–701. https://doi.org/10.3102/0034654316689306
- Agarwal, P. K., Nunes, L. D., & Blunt, J. R. (2021). *Educational Psychology Review*, 33, 1409–1453. https://doi.org/10.1007/s10648-021-09595-9
- Arnold, K. M., & McDermott, K. B. (2013). *JEP:LMC*, 39(3), 940–945.
- Bjork, R. A., & Bjork, E. L. (1992). A new theory of disuse. In *From Learning Processes to Cognitive Processes* (Vol. 2, pp. 35–67). Erlbaum.
- Bjork, E. L., & Bjork, R. A. (2011). Making things hard on yourself, but in a good way. In *Psychology and the Real World* (pp. 56–64). Worth.
- Butler, A. C., Karpicke, J. D., & Roediger, H. L. (2007). *JEP: Applied*, 13(4), 273–281. https://learninglab.psych.purdue.edu/downloads/2007/2007_Butler_Karpicke_Roediger_JEPA.pdf
- Butler, A. C., & Roediger, H. L. (2008). *Memory & Cognition*, 36(3), 604–616. https://doi.org/10.3758/MC.36.3.604
- Chan, J. C. K., Meissner, C. A., & Davis, S. D. (2018). *Psychological Bulletin*, 144(11), 1111–1146. https://doi.org/10.1037/bul0000166
- Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013). *Psychological Science in the Public Interest*, 14(1), 4–58. https://doi.org/10.1177/1529100612453266
- Kang, S. H. K., McDermott, K. B., & Roediger, H. L. (2007). *European Journal of Cognitive Psychology*, 19(4–5), 528–558. https://doi.org/10.1080/09541440601056620
- Karpicke, J. D., & Aue, W. R. (2015). *Educational Psychology Review*, 27(2), 317–326. https://doi.org/10.1007/s10648-015-9309-3 **[Contested — one side of the element-interactivity dispute]**
- Karpicke, J. D., & Blunt, J. R. (2011). *Science*, 331(6018), 772–775. https://doi.org/10.1126/science.1199327
- Karpicke, J. D., & Roediger, H. L. (2007). *JEP:LMC*, 33(4), 704–719. https://learninglab.psych.purdue.edu/downloads/2007/2007_Karpicke_Roediger_JEPLMC.pdf
- Karpicke, J. D., & Roediger, H. L. (2008). *Science*, 319(5865), 966–968. https://doi.org/10.1126/science.1152408
- King-Shepard, Q., et al. (2025). *Educational Psychology Review*, 37. https://doi.org/10.1007/s10648-025-10075-7
- Koriat, A., & Bjork, R. A. (2005). *JEP:LMC*, 31(2), 187–194. https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Koriat_RBjork_2005.pdf
- Kornell, N., Hays, M. J., & Bjork, R. A. (2009). *JEP:LMC*, 35(4), 989–998. https://web.williams.edu/Psychology/Faculty/Kornell/Publications/Kornell.Hays.Bjork.2009.pdf
- Lechuga, M. T., Ortega-Tudela, J. M., & Gómez-Ariza, C. J. (2015). *Learning and Instruction*, 40, 61–68. https://doi.org/10.1016/j.learninstruc.2015.08.002
- McDermott, K. B., et al. (2014). *JEP: Applied*, 20(1), 3–21. https://pdf.retrievalpractice.org/guide/McDermott_etal_2014_JEPA.pdf
- Metcalfe, J., Kornell, N., & Finn, B. (2009). *Memory & Cognition*, 37(8), 1077–1087. https://doi.org/10.3758/MC.37.8.1077
- Pan, S. C., & Carpenter, S. K. (2023). *Educational Psychology Review*, 35, 97. https://doi.org/10.1007/s10648-023-09814-5
- Pan, S. C., & Rickard, T. C. (2018). *Psychological Bulletin*, 144(7), 710–756. https://pdf.retrievalpractice.org/transfer/Pan_Rickard_2018.pdf
- Rhodes, M. G., & Castel, A. D. (2008). *JEP: General*, 137(4), 615–625. https://doi.org/10.1037/a0013684
- Richland, L. E., Kornell, N., & Kao, L. S. (2009). *JEP: Applied*, 15(3), 243–257. https://doi.org/10.1037/a0016496
- Roediger, H. L., & Karpicke, J. D. (2006). *Psychological Science*, 17(3), 249–255. https://doi.org/10.1111/j.1467-9280.2006.01693.x
- Rowland, C. A. (2014). *Psychological Bulletin*, 140(6), 1432–1463. https://doi.org/10.1037/a0037559 (success-band moderator values are correlational and were not table-verified — treat as descriptive)
- Slamecka, N. J., & Graf, P. (1978). *JEP: Human Learning and Memory*, 4(6), 592–604.
- Smith, T. A., & Kimball, D. R. (2010). *JEP:LMC*, 36(1), 80–95.
- Soderstrom, N. C., & Bjork, R. A. (2015). *Perspectives on Psychological Science*, 10(2), 176–199. https://doi.org/10.1177/1745691615569000
- Szpunar, K. K., Khan, N. Y., & Schacter, D. L. (2013). *PNAS*, 110(16), 6313–6317. https://doi.org/10.1073/pnas.1221764110
- van Gog, T., & Sweller, J. (2015). *Educational Psychology Review*, 27(2), 247–264. https://doi.org/10.1007/s10648-015-9310-x **[Contested — the other side of the element-interactivity dispute]**
- Yang, C., Luo, L., Vadillo, M. A., Yu, R., & Shanks, D. R. (2021). *Psychological Bulletin*, 147(4), 399–435. https://doi.org/10.1037/bul0000309

### Spacing, consolidation, and interleaving

- Brunmair, M., & Richter, T. (2019). *Psychological Bulletin*, 145(11), 1029–1052. https://doi.org/10.1037/bul0000209
- Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T., & Rohrer, D. (2006). *Psychological Bulletin*, 132(3), 354–380. https://augmentingcognition.com/assets/Cepeda2006.pdf
- Cepeda, N. J., Vul, E., Rohrer, D., Wixted, J. T., & Pashler, H. (2008). *Psychological Science*, 19(11), 1095–1102. https://files.eric.ed.gov/fulltext/ED505660.pdf
- Chalkia, A., et al. (2020). *Cortex*, 129, 496–509 (verification report) and 129, 510–525 (registered replication). **[Contested — human reconsolidation-update record roughly split]**
- Diekelmann, S., & Born, J. (2010). *Nature Reviews Neuroscience*, 11, 114–126. https://www.nature.com/articles/nrn2762
- Feng, K., et al. (2019). *Journal of Neuroscience*, 39(27), 5351–5360. https://www.jneurosci.org/content/39/27/5351
- Janes, J. L., Dunlosky, J., Rawson, K. A., & Jasnow, A. (2020). *Applied Cognitive Psychology*, 34(5), 1118–1125. https://doi.org/10.1002/acp.3699
- Latimier, A., Peyre, H., & Ramus, F. (2021). *Educational Psychology Review*, 33, 959–987. https://link.springer.com/article/10.1007/s10648-020-09572-8
- Lindsey, R. V., Shroyer, J. D., Pashler, H., & Mozer, M. C. (2014). *Psychological Science*, 25(3), 639–647. https://journals.sagepub.com/doi/abs/10.1177/0956797613504302
- Nader, K., Schafe, G. E., & LeDoux, J. E. (2000). *Nature*, 406, 722–726. https://www.nature.com/articles/35021052
- Newbury, C. R., Crowley, R., Rastle, K., & Tamminen, J. (2021). *Psychological Bulletin*, 147(11), 1215–1240. https://pmc.ncbi.nlm.nih.gov/articles/PMC8893218/ (significant publication bias reported in both of its meta-analyses)
- Open Spaced Repetition SRS Benchmark (Anki dataset, ~10k users, ~350M reviews). https://github.com/open-spaced-repetition/srs-benchmark **[engineering benchmark, not peer-reviewed; measures predictive calibration, not learning outcomes]**
- Raykov, P. P., et al. (2026). *Philosophical Transactions of the Royal Society B*, 381(1954), 20250250. https://royalsocietypublishing.org/rstb/article/381/1954/20250250/482484/
- Rawson, K. A., & Dunlosky, J. (2011). *JEP: General*, 140(3), 283–302. https://doi.org/10.1037/a0023956
- Rawson, K. A., & Dunlosky, J. (2022). *Current Directions in Psychological Science*, 31(4), 362–368. https://dx.doi.org/10.1177/09637214221100484
- Rohrer, D., & Taylor, K. (2007). *Instructional Science*, 35, 481–498. https://link.springer.com/article/10.1007/s11251-007-9015-8
- Rohrer, D., Dedrick, R. F., Hartwig, M. K., & Cheung, C.-N. (2020). *Journal of Educational Psychology*, 112(1), 40–52. https://gwern.net/doc/psychology/spaced-repetition/2019-rohrer.pdf
- Sevenster, D., Beckers, T., & Kindt, M. (2013). Prediction error as boundary condition for destabilization (original claim; replication attempts mixed — see *Scientific Reports*, 12, 2652, 2022, https://www.nature.com/articles/s41598-022-06119-5). **[Contested]**
- Smolen, P., Zhang, Y., & Byrne, J. H. (2016). *Nature Reviews Neuroscience*, 17(2), 77–88. https://www.nature.com/articles/nrn.2015.18
- Tse, D., et al. (2007). *Science*, 316(5821), 76–82. https://www.science.org/doi/10.1126/science.1135935
- van Kesteren, M. T. R., et al. (2012). *Trends in Neurosciences*, 35(4), 211–219. **[Contested — SLIMM's neural predictions failed a 2026 confirmatory fMRI test; behavioral schema effects robust]**
- Wilhelm, I., et al. (2011). *Journal of Neuroscience*, 31(5), 1563–1569. https://www.jneurosci.org/content/31/5/1563
- Ye, J., Su, J., & Cao, Y. (2022). *Proceedings of ACM SIGKDD 2022*, 4381–4390. https://dl.acm.org/doi/10.1145/3534678.3539081

### Generative learning, cognitive load, and multimedia

- Barbieri, C. A., et al. (2023). *Educational Psychology Review*, 35:11. https://doi.org/10.1007/s10648-023-09745-1
- Bertsch, S., Pesta, B. J., Wiscott, R., & McDaniel, M. A. (2007). *Memory & Cognition*, 35(2), 201–210. https://doi.org/10.3758/BF03193441
- Bisra, K., Liu, Q., Nesbit, J. C., Salimi, F., & Winne, P. H. (2018). *Educational Psychology Review*, 30(3), 703–725. https://doi.org/10.1007/s10648-018-9434-x
- Chase, C. C., Chin, D. B., Oppezzo, M. A., & Schwartz, D. L. (2009). *Journal of Science Education and Technology*, 18, 334–352. https://doi.org/10.1007/s10956-009-9180-4
- Chi, M. T. H., et al. (1989). *Cognitive Science*, 13(2), 145–182.
- Chi, M. T. H., & Wylie, R. (2014). *Educational Psychologist*, 49(4), 219–243. https://doi.org/10.1080/00461520.2014.965823 **[Contested — Interactive > Constructive step and behavior-as-proxy assumption have failed direct tests]**
- Donoghue, G. M., & Hattie, J. A. C. (2021). *Frontiers in Education*, 6:581216. https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2021.581216/full
- Fiorella, L., & Mayer, R. E. (2015). *Learning as a Generative Activity*. Cambridge University Press.
- Fiorella, L., & Mayer, R. E. (2016). *Educational Psychology Review*, 28, 717–741. https://doi.org/10.1007/s10648-015-9348-9
- Kalyuga, S. (2011). *Educational Psychology Review*, 23, 1–19. https://doi.org/10.1007/s10648-010-9150-7
- Kiewra, K. A. (1985). *Contemporary Educational Psychology*, 10(4), 378–386 (n = 23; lean on Kiewra's broader program, e.g., Kiewra et al. 1991).
- Kobayashi, K. (2005). *Contemporary Educational Psychology*, 30(2), 242–262. https://doi.org/10.1016/j.cedpsych.2004.10.001
- Kobayashi, K. (2006). *Educational Psychology*, 26(3), 459–477. https://www.tandfonline.com/doi/abs/10.1080/01443410500342070
- Kobayashi, K. (2019). *Japanese Psychological Research*, 61(3), 192–203. https://doi.org/10.1111/jpr.12221
- Mayer, R. E. (2021). *Multimedia Learning* (3rd ed.). Cambridge University Press.
- Morehead, K., Dunlosky, J., & Rawson, K. A. (2019). *Educational Psychology Review*, 31, 753–780. https://doi.org/10.1007/s10648-019-09468-2
- Mueller, P. A., & Oppenheimer, D. M. (2014). *Psychological Science*, 25(6), 1159–1168. **[Did not survive replication — cite only alongside Urry et al. 2021]**
- Rey, G. D., et al. (2019). *Educational Psychology Review*, 31, 389–419. https://doi.org/10.1007/s10648-018-9456-4
- Schneider, S., Beege, M., Nebel, S., & Rey, G. D. (2018). *Educational Research Review*, 23, 1–24. https://doi.org/10.1016/j.edurev.2017.11.001
- Schroeder, N. L., Nesbit, J. C., Anguiano, C. J., & Adesope, O. O. (2018). *Educational Psychology Review*, 30, 431–455. https://doi.org/10.1007/s10648-017-9403-9
- Seductive Details, Cognitive Load, and Learning Outcomes: A Multi-level Meta-analysis and MASEM (2025). *Educational Psychology Review*. https://doi.org/10.1007/s10648-025-10099-z
- Sundararajan, N., & Adesope, O. (2020). *Educational Psychology Review*, 32, 707–734. https://doi.org/10.1007/s10648-020-09522-4
- Sweller, J. (1988). *Cognitive Science*, 12(2), 257–285.
- Sweller, J., van Merriënboer, J. J. G., & Paas, F. (2019). *Educational Psychology Review*, 31, 261–292. https://doi.org/10.1007/s10648-019-09465-5
- Tan, L. P., Gong, S. Y., Wang, Y. J., et al. (2025). *Educational Psychology Review*, 37:20. https://doi.org/10.1007/s10648-025-10001-x
- Thurn, C. M., Edelsbrunner, P. A., Berkowitz, M., Deiglmayr, A., & Schalk, L. (2023). *npj Science of Learning*, 8:49. https://www.nature.com/articles/s41539-023-00197-4
- Urry, H. L., et al. (2021). *Psychological Science*, 32(3), 326–339. https://doi.org/10.1177/0956797620965541
- Wiggins, B. L., Eddy, S. L., Grunspan, D. Z., & Crowe, A. J. (2017). *AERA Open*, 3(2). https://doi.org/10.1177/2332858417708567

### Metacognition, self-regulation, and cognitive offloading

- Boldt, A., & Gilbert, S. J. (2019). *Cognitive Research: Principles and Implications*, 4, 45. https://doi.org/10.1186/s41235-019-0195-y
- Camerer, C. F., et al. (2018). *Nature Human Behaviour*, 2, 637–644. https://www.nature.com/articles/s41562-018-0399-z
- Dignath, C., & Büttner, G. (2008). *Metacognition and Learning*, 3, 231–264. https://doi.org/10.1007/s11409-008-9029-x
- Donker, A. S., et al. (2014). *Educational Research Review*, 11, 1–26. https://doi.org/10.1016/j.edurev.2013.11.002 (g = 0.66 is the mathematics-domain effect, not overall)
- Dunlosky, J., & Rawson, K. A. (2012). *Learning and Instruction*, 22(4), 271–280. https://doi.org/10.1016/j.learninstruc.2011.08.003
- Grinschgl, S., Papenmeier, F., & Meyerhoff, H. S. (2021). *QJEP*, 74(9), 1477–1496. https://doi.org/10.1177/17470218211008060
- Henkel, L. A. (2014). *Psychological Science*, 25(2), 396–402. https://doi.org/10.1177/0956797613504438
- Hulleman, C. S., et al. (2010). *Psychological Bulletin*, 136(3), 422–449. https://doi.org/10.1037/a0018947
- Locke, E. A., & Latham, G. P. (2002). *American Psychologist*, 57(9), 705–717. https://med.stanford.edu/content/dam/sm/s-spire/documents/PD.locke-and-latham-retrospective_Paper.pdf
- Macnamara, B. N., & Burgoyne, A. P. (2023). *Psychological Bulletin*, 149(3–4), 133–173. **[Contested field — growth-mindset intervention effects weak to null]**
- Metcalfe, J., & Finn, B. (2008). *Psychonomic Bulletin & Review*, 15(1), 174–179. https://doi.org/10.3758/PBR.15.1.174
- Nelson, T. O., & Dunlosky, J. (1991). *Psychological Science*, 2(4), 267–270.
- Ngai, C., & Gilbert, S. J. (2026). *Cognitive Research: Principles and Implications*. https://pmc.ncbi.nlm.nih.gov/articles/PMC12982714/
- Panadero, E. (2017). *Frontiers in Psychology*, 8, 422. https://doi.org/10.3389/fpsyg.2017.00422
- Rhodes, M. G., & Tauber, S. K. (2011). *Psychological Bulletin*, 137(1), 131–148. https://doi.org/10.1037/a0021705
- Risko, E. F., & Gilbert, S. J. (2016). *Trends in Cognitive Sciences*, 20(9), 676–688. https://doi.org/10.1016/j.tics.2016.07.002
- Sachdeva, C., & Gilbert, S. J. (2020). *Consciousness and Cognition*, 85, 103024. https://doi.org/10.1016/j.concog.2020.103024
- Sanchez, C. E., et al. (2017). *Journal of Educational Psychology*, 109(8), 1049–1066. https://doi.org/10.1037/edu0000190
- Sisk, V. F., et al. (2018). *Psychological Science*, 29(4), 549–571. https://doi.org/10.1177/0956797617739704
- Sitzmann, T., & Ely, K. (2011). *Psychological Bulletin*, 137(3), 421–442. https://doi.org/10.1037/a0022777
- Soares, J. S., & Storm, B. C. (2018). *JARMAC*, 7(1), 154–160.
- Sparrow, B., Liu, J., & Wegner, D. M. (2011). *Science*, 333(6043), 776–778. **[Contested — Experiment 1 failed preregistered replication (Camerer 2018) and a corrected-protocol replication; saved/erased paradigm replicates only under demonstrated store reliability. Do not build on this.]**
- Storm, B. C., & Stone, S. M. (2015). *Psychological Science*, 26(2), 182–188. https://doi.org/10.1177/0956797614559285
- Theobald, M. (2021). *Contemporary Educational Psychology*, 66, 101976. https://doi.org/10.1016/j.cedpsych.2021.101976
- Weissgerber, S. C., Brunmair, M., & Rummer, R. (2021). Null and Void? *Educational Psychology Review* (corrective commentary on Xie et al. 2018).
- Winters, D., & Latham, G. P. (1996). *Group & Organization Management*, 21(2), 236–250. https://doi.org/10.1177/1059601196212007
- Xie, H., Zhou, Z., & Liu, Q. (2018). *Educational Psychology Review*, 30, 745–771. https://doi.org/10.1007/s10648-018-9442-x (transfer null robust; recall coefficients unreliable per Weissgerber et al.)
- Yan, Z., Wang, X., Boud, D., & Lao, H. (2023). *Assessment & Evaluation in Higher Education*, 48(1), 1–15. https://doi.org/10.1080/02602938.2021.2012644
- Zimmerman, B. J. (2002). *Theory Into Practice*, 41(2), 64–70. https://doi.org/10.1207/s15430421tip4102_2
- Winne, P. H., & Hadwin, A. F. (1998). In *Metacognition in Educational Theory and Practice* (pp. 277–304). Erlbaum.

### Scaffolding, tutoring, mastery, and feedback

- Aleven, V., & Koedinger, K. R. (2000). *ITS 2000*, 292–303. https://link.springer.com/chapter/10.1007/3-540-45108-0_33
- Baker, R. S., Corbett, A. T., Koedinger, K. R., & Wagner, A. Z. (2004). *ACM CHI 2004*, 383–390. http://pact.cs.cmu.edu/pubs/Baker,%20Corbett,%20Koedinger%20Wagner_2004.pdf
- Belland, B. R., Walker, A. E., Kim, N. J., & Lefler, M. (2017). *Review of Educational Research*, 87, 309–344. https://doi.org/10.3102/0034654316670999
- Belland, B. R., Walker, A. E., Olsen, M. W., & Leary, H. (2015). *Educational Technology & Society*, 18(1). https://eric.ed.gov/?id=EJ1062484
- Black, P., & Wiliam, D. (1998). *Assessment in Education*, 5, 7–74. **[Contested magnitude — narrative synthesis; see Kingston & Nash and Briggs et al.]**
- Bloom, B. S. (1968). Learning for mastery. *Evaluation Comment*, 1(2). https://eric.ed.gov/?id=ED053419
- Bloom, B. S. (1984). *Educational Researcher*, 13(6), 4–16. **[The 2-sigma figure reflects tutoring confounded with mastery learning on narrow short-duration tests — not a benchmark]**
- Briggs, D. C., Ruiz-Primo, M. A., Furtak, E., Shepard, L., & Yin, Y. (2012). *Educational Measurement: Issues and Practice*, 31(4), 13–17. https://eric.ed.gov/?id=EJ988828
- Chi, M. T. H., Siler, S., Jeong, H., Yamauchi, T., & Hausmann, R. (2001). *Cognitive Science*, 25, 471–533. https://doi.org/10.1207/s15516709cog2504_1
- Graesser, A. C., Person, N. K., & Magliano, J. P. (1995). *Applied Cognitive Psychology*, 9, 495–522. https://doi.org/10.1002/acp.2350090604
- Hattie, J., & Timperley, H. (2007). *Review of Educational Research*, 77, 81–112. https://doi.org/10.3102/003465430298487
- Kalyuga, S. (2007). *Educational Psychology Review*, 19, 509–539. https://doi.org/10.1007/s10648-007-9054-3
- Kalyuga, S., Ayres, P., Chandler, P., & Sweller, J. (2003). *Educational Psychologist*, 38(1), 23–31. https://doi.org/10.1207/S15326985EP3801_4
- Kapur, M. (2008). *Cognition and Instruction*, 26, 379–424. https://doi.org/10.1080/07370000802212669
- Kingston, N., & Nash, B. (2011). *Educational Measurement: Issues and Practice*, 30(4), 28–37. **[Contested — its own methodology criticized by Briggs et al. 2012]**
- Koedinger, K. R., & Aleven, V. (2007). *Educational Psychology Review*, 19, 239–264. https://doi.org/10.1007/s10648-007-9049-0
- Kulik, C.-L. C., Kulik, J. A., & Bangert-Drowns, R. L. (1990). *Review of Educational Research*, 60, 265–299. https://doi.org/10.3102/00346543060002265
- Kulik, J. A., & Fletcher, J. D. (2016). *Review of Educational Research*, 86, 42–78. https://doi.org/10.3102/0034654315581420
- Ma, W., Adesope, O. O., Nesbit, J. C., & Liu, Q. (2014). *Journal of Educational Psychology*, 106, 901–918. https://www.apa.org/pubs/journals/features/edu-a0037123.pdf
- Nickow, A., Oreopoulos, P., & Quan, V. (2024). *American Educational Research Journal* (NBER WP 27476). https://doi.org/10.3102/00028312231208687
- Pratt, M. W., & Savoy-Levine, K. M. (1998). *Journal of Applied Developmental Psychology*, 19(2), 287–304.
- Salden, R. J. C. M., Aleven, V., Schwonke, R., & Renkl, A. (2010). *Instructional Science*, 38, 289–307. https://doi.org/10.1007/s11251-009-9107-8
- Sinha, T., & Kapur, M. (2021). *Review of Educational Research*, 91, 761–798. https://doi.org/10.3102/00346543211019105 (co-authored by the paradigm originator; independent replications exist)
- Tetzlaff, L., Simonsmeier, B., Peters, T., & Brod, G. (2025). *Learning and Instruction*. https://doi.org/10.1016/j.learninstruc.2025.102064
- van de Pol, J., Volman, M., & Beishuizen, J. (2010). *Educational Psychology Review*, 22, 271–296. https://doi.org/10.1007/s10648-010-9127-6
- VanLehn, K. (2011). *Educational Psychologist*, 46, 197–221. https://doi.org/10.1080/00461520.2011.611369
- VanLehn, K., Graesser, A. C., et al. (2007). *Cognitive Science*, 31, 3–62. https://doi.org/10.1080/03640210709336984
- Vygotsky, L. S. (1978). *Mind in Society*. Harvard University Press.
- Wisniewski, B., Zierer, K., & Hattie, J. (2020). *Frontiers in Psychology*, 10:3087. https://doi.org/10.3389/fpsyg.2019.03087
- Wood, D., Bruner, J. S., & Ross, G. (1976). *Journal of Child Psychology and Psychiatry*, 17, 89–100. https://doi.org/10.1111/j.1469-7610.1976.tb00381.x
- Wood, D., & Wood, H. (1999). *Computers & Education*, 33, 153–169. https://doi.org/10.1016/S0360-1315(99)00030-5
- Wood, D., Wood, H., & Middleton, D. (1978). *International Journal of Behavioral Development*, 1, 131–147. https://doi.org/10.1177/016502547800100203

### AI-assisted learning (2023–2026)

- Bassner, P., Lenk-Ostendorf, B., Beinstingel, R., Wasner, T., & Krusche, S. (2026). *Computers and Education: Artificial Intelligence*, 10. https://www.sciencedirect.com/science/article/pii/S2666920X25001778
- Bastani, H., Bastani, O., Sungu, A., Ge, H., Kabakcı, Ö., & Mariman, R. (2025). Generative AI without guardrails can harm learning. *PNAS*, 122(26), e2422633122. https://www.pnas.org/doi/10.1073/pnas.2422633122
- Darvishi, A., Khosravi, H., Sadiq, S., Gašević, D., & Siemens, G. (2024). *Computers & Education*, 210, 104967. https://doi.org/10.1016/j.compedu.2023.104967
- Fan, Y., et al., & Gašević, D. (2025). Beware of metacognitive laziness. *British Journal of Educational Technology*, 56(2), 489–530. https://doi.org/10.1111/bjet.13544
- HSSC (2026). ChatGPT's impact on student learning outcomes: a meta-analysis of 35 experimental studies. https://www.nature.com/articles/s41599-026-07019-z (immediate performance only)
- Jurenka, I., Kunesch, M., McKee, K. R., et al. (2024; v4 2025). Towards Responsible Development of Generative AI for Education. https://arxiv.org/abs/2407.12687 **[Technical report — preference-based evaluation, no learner-outcome RCT]**
- Kazemitabaar, M., Chow, J., Ma, C. K. T., Ericson, B. J., Weintrop, D., & Grossman, T. (2023). *CHI 2023*. https://doi.org/10.1145/3544548.3580919
- Kestin, G., Miller, K., Klales, A., Milbourne, T., & Ponti, G. (2025). *Scientific Reports*, 15, 17458. https://www.nature.com/articles/s41598-025-97652-6 (immediate post-tests only)
- Kosmyna, N., et al., & Maes, P. (2025). Your Brain on ChatGPT. https://arxiv.org/abs/2506.08872 **[Preprint; contested; no learning-outcome measure — convergent support only]**
- Liu, Z., Zuo, H., & Lu, Y. (2025). *Journal of Computer Assisted Learning*. https://doi.org/10.1111/jcal.70096 (immediate performance only)
- Nie, A., Chandak, Y., Suzara, M., et al., & Piech, C. (2025). The GPT Surprise. *ACM Learning @ Scale 2025*. https://doi.org/10.1145/3698205.3733960
- Pardos, Z. A., & Bhandari, S. (2024). *PLOS ONE*, 19(5), e0304013. https://doi.org/10.1371/journal.pone.0304013 (both ChatGPT-3.5 and human hints beat control; no significant difference between sources)
- Rismanchian, S., Uzun, H., Matayoshi, J., Cosyn, E., & Kurd-Misto, E. (2026). Faster Completion, Less Learning. https://arxiv.org/abs/2605.21629 **[Preprint; most authors ALEKS/McGraw Hill-affiliated; correlational DiD]**
- Stadler, M., Bannert, M., & Sailer, M. (2024). *Computers in Human Behavior*, 160, 108386. https://doi.org/10.1016/j.chb.2024.108386
- Wang, J., & Fan, W. (2025). *HSSC*, 12, 621. **[RETRACTED April 2026 — do not cite; Retraction Note: https://www.nature.com/articles/s41599-026-07310-z]**
- Wang, R. E., Ribeiro, A. T., Robinson, C. D., Loeb, S., & Demszky, D. (2024). Tutor CoPilot. https://arxiv.org/abs/2410.03017 **[Working paper]**

---

*Design changes that contradict a principle in §3 must either cite newer evidence or amend this charter first (§1.2).*
