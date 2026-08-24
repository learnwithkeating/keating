# Keating

<p align="center"><strong>AI-assisted learning that keeps the learning yours.</strong></p>

---

Keating is not an AI tutor. Getting a language model to explain something well is a solved
problem and it is not what this is for. Keating is a platform for **learning with** an AI that
is deliberately constrained: you do the retrieving, the generating, the explaining and the
judging, because that is where memory is actually built. The software does the bookkeeping.

The goal is **depth, not speed**. Nothing here is designed to get you through material faster.

![The Keating interface](docs/screenshots/hero.png)

## Why constrain the AI at all

In the largest randomised trial of AI assistance in learning to date, roughly a thousand
students given unrestricted GPT-4 during practice scored **48% better while they had it** and
**17% worse than the no-AI control** on a later closed-book exam. The mechanism was not bad
information; the model was right about half the time and its errors did not predict the decline.
The mechanism was answer-fetching. A guardrailed version, which withheld answers and gave hints,
eliminated the harm entirely.
([Bastani et al. 2025, *PNAS*](https://www.pnas.org/doi/10.1073/pnas.2422633122))

That result is the reason this software exists in the shape it does.

## What the AI does, and what it refuses to do

| It does | It will not |
|---|---|
| Grade a committed attempt against a rubric written alongside the question | Answer a question about material you are studying before you have attempted it |
| Critique a draft **after** you have written it, and show its version as a comparison | Write your glossary entries, summaries, free recalls, or learning records |
| Keep the practice log, compute what is due, and schedule review | Present a streak or a session score as evidence that you learned something |
| Build lessons, quiz items and rubrics from your syllabus and sources | Touch graded coursework, unless an assignment explicitly permits it |
| Ask for your attempt, then respond to what you actually wrote | Tell you that you are doing great. Feedback evaluates the response, never the person |
| Record what you know, when the evidence supports it | Claim you understand something without a graded attempt, an artifact you wrote, or a real-world report to cite |

The refusals are very the product.

## The evidence underneath

Every design rule traces back to our 
[`Scientific Charter`](docs/learning-science-foundations.md):

- **Retrieval beats review.** Practicing recall outperforms restudying the same material for the
  same time at *g* ≈ 0.50, across four independent meta-analyses and 222 classroom studies.
  ([Rowland 2014](https://doi.org/10.1037/a0037559);
  [Yang et al. 2021](https://doi.org/10.1037/bul0000309))
  So every quiz item requires a typed answer before it will show you anything.
- **The ranking of study methods flips with time.** Rereading beat testing 83% to 71% five
  minutes after study, and lost 40% to 61% a week later.
  ([Roediger & Karpicke 2006](https://doi.org/10.1111/j.1467-9280.2006.01693.x))
  So the platform measures delayed, unassisted recall and treats session performance as a
  vanity metric.
- **Spacing won 259 of 271 direct comparisons.**
  ([Cepeda et al. 2006](https://augmentingcognition.com/assets/Cepeda2006.pdf))
  So material you answered correctly today comes back tomorrow, and a night's sleep sits between
  first exposure and first verification.
- **You cannot feel your own learning.** Predictions of later recall are near-uncorrelated with
  actual recall, and they drive study decisions anyway. Judgments made *after* a retrieval
  attempt are dramatically better calibrated (*g* = 0.93).
  ([Rhodes & Tauber 2011](https://doi.org/10.1037/a0021705))
  So Keating asks how sure you are **before** it reveals anything, then shows you the gap.
- **Generating beats reading** at *d* = 0.40.
  ([Bertsch et al. 2007](https://doi.org/10.3758/BF03193441))
  So you draft the definition and the AI critiques it, never the reverse.
- **Interleaving helps for confusable material and reverses for unrelated material**
  (*g* = 0.67 vs *g* = −0.39).
  ([Brunmair & Richter 2019](https://doi.org/10.1037/bul0000209))
  So practice mixes across a unit's neighbouring concepts, not across arbitrary content.

## How it works

### Attempts are gated, graded, and recorded

No answer is ever one click away. You commit a response and a confidence rating first.

![A quiz item before the attempt](docs/screenshots/quiz-gated.png)

The grade comes back as four fixed parts, never a compliment: the criterion for mastery, how
this attempt relates to it **citing your own words**, one strategy to try next, and a question
to ask yourself. Every attempt lands in an append-only practice log.

![The same item, graded](docs/screenshots/quiz-answered.png)

That screenshot is a real attempt, graded live. The answer given was accurate as far as it went
and the response says so, then names exactly what was missing (the comparison is matched for
total time) and why the omission matters (without it, the effect could be dismissed as extra
exposure rather than a benefit of retrieval). Partially correct is reported as partially
correct.

### Your record is evidence, not vibes

![The practice page](docs/screenshots/practice.png)

Each square is one attempt: filled for correct, half for partial, hollow for wrong, grey for a
skip. Fill state carries the meaning, so the display works without colour. The calibration table
compares what you predicted against what happened, and high-confidence errors are flagged
because they are the most valuable thing in the system to re-test.

### You write; the AI critiques

![The compose surface](docs/screenshots/compose.png)

Free recall and glossary entries are drafted from memory, then diffed against the AI's version:
what you had, what you missed, what is subtly off. Free recall is logged as a retrieval event,
so it feeds scheduling like any other attempt.

## Course packages

A course is a directory that can be handed to anyone. Learner state lives in one subdirectory
and never travels with it:

```
why-you-forget/
  course.json          manifest: title, units, and their order
  lessons/*.html       numbered lessons, each declaring the unit it belongs to
  assets/              shared stylesheet
  materials/           source material the course is taught from
  RESOURCES.md         curated, annotated sources
```

[`examples/why-you-forget/`](examples/why-you-forget/) is a complete five-lesson course on the
memory research this platform is built on. Copy it into your workspace and you have something
real to try in about a minute.

## The name

John Keating is the teacher in [Dead Poets Society](https://en.wikipedia.org/wiki/Dead_Poets_Society) who stands on his desk to remember to look
at things another way, and who refuses to hand Todd Anderson a poem, pushing until Todd produces
one himself. That refusal is the whole idea.

## License

MIT. See [LICENSE](LICENSE).
