# Evaluation Design — ProbeAI




## Evaluation Questions

### 1. What makes a research report "good"?

- answers the original question directly
- It clearly distinguishes between extracted facts (e.g., "Revenue is $10M") and AI synthesis (e.g., "This suggests a strong product-market fit").
- cites sources for major claims
- includes multiple independent sources
- acknowledges uncertainty and conflicting evidence
- avoids overstating conclusions as a good report admits when it didn't find something. "I don't know" is a more valuable answer than a hallucinated guess.
- remains concise and readable


### 2. How would you detect hallucinated claims?

The current system uses lightweight heuristics to flag potentially unsupported claims.

Possible production improvements:

1. Verification agents  
A separate agent independently checks whether synthesized claims are actually supported by the collected evidence.

2. Claim-to-citation grounding  
Every major sentence in the report should map back to evidence items or source URLs.

3. Cross-source corroboration  
Claims become more trustworthy when multiple independent sources support the same conclusion.

4. Contradiction detection  
Compare evidence across sources to identify conflicting claims or inconsistent conclusions.

5. Confidence scoring  
Assign confidence levels based on:
- source authority
- number of supporting sources
- source independence
- evidence consistency
- recency of information


### 3. How would you measure source quality?

Possible production improvements:

1. Domain reputation systems  
Maintain continuously updated trust scores for domains, publishers, and authors.

2. For example i can categorize it like this:

High authority:
- .gov
- .edu
- research institutions
- established technical publications
- Established Company's & Valuable Startups
- Established Post , Tweets , Articles from Reputed Industry Experts 

Medium authority:
- major tech blogs
- GitHub repositories
- company engineering blogs
- industry publications

Low authority:
- social media posts
- forums
- anonymous blogs
- highly opinionated content


3. Source independence analysis  
Detect whether multiple articles repeat the same original source instead of providing independent evidence.

4. Citation graph analysis  
Measure how frequently a source is referenced by other trusted sources.

5. Bias and incentive  
Account for vendor-authored content, affiliate incentives, sponsored research, or promotional material.

6. Freshness  
For technical topics (like "browser agents"), a source from 2023 is often "low quality" compared to one from 2026, even if the domain is prestigious.


### 4. How would you test that the agent actually iterates instead of doing one shallow search?

1. Iteration usefulness scoring  
Measure whether later iterations improve report quality instead of only collecting more data.

2. Evidence gain analysis  
Track how much genuinely new information each iteration contributes.

3. Coverage tracking  
Measure whether additional iterations reduce unanswered subquestions or uncertainty gaps.

4. Query evolution analysis  
Evaluate whether follow-up queries become more targeted or exploratory over time.

5. Research trajectory analysis  
Check whether the agent adapts its strategy based on previous findings instead of repeating similar searches.


### 5. What would you log during a run?

- token usage and cost tracking
- latency tracking per agent step
- duplicate result detection
- claim-to-source provenance mapping
- parsing and validation failures
- observability dashboards for long-running agents


### 6. What are 3 failure cases you would test?

1. Entity ambiguity  
Example: “Clay” referring to either the GTM platform or the material.

2. Weak-source dominance  
The agent retrieves mostly social posts, blogs, or speculative content instead of reliable sources.

3. Shallow iteration behavior  
The agent stops after one search cycle despite unresolved gaps or weak evidence.

4. A research question about a breaking news event (e.g., "Who is currently winning the X tournament?"). Testing if the agent can prioritize timestamp-aware evidence over older, more authoritative-looking data.

5. A topic where many blog posts all quote the same incorrect original source. Testing if the agent can identify the lack of independent confirmation.




## How Evals Currently Work

The evaluation system lives in `services/evaluator.py`. It runs automatically after every research run (Phase 4) and writes `evals.json` to the run directory.

**The core principle: everything is heuristic-based and deterministic.** There's no LLM-as-judge, no external benchmarks, no embeddings. Just simple, inspectable scoring functions that anyone can read and understand.

Here's what it measures and how:

### Factuality Score

Each piece of extracted evidence has a strength rating (`strong`, `moderate`, `weak`, `speculative`). The factuality score is just a weighted average across all evidence:

- Strong = 1.0, Moderate = 0.7, Weak = 0.3, Speculative = 0.1

If most of your evidence is strong, the score is high. If it's mostly speculative, the score is low. Simple.

### Source Authority

Every source URL is scored by its domain using a hardcoded tier list:

- **High (1.0):** `.gov`, `.edu`, `arxiv.org`, `nature.com`, etc.
- **Medium (0.6):** `techcrunch.com`, `reuters.com`, `github.com`, etc.
- **Low (0.3):** `reddit.com`, `twitter.com`, `quora.com`, etc.
- **Unknown (0.5):** anything else gets a neutral score

The final score is the average across all evidence sources.

### Source Diversity

Counts unique domains and classifies them into categories (government, academic, news, tech, social, forum, blog, other). A good research run should pull from multiple categories, not just one.

### Uncertainty Calibration

Measures whether the report acknowledges uncertainty instead of presenting every conclusion as definitive.

This is implemented using lightweight heuristics:

1. Does the report contain hedging language? ("suggests", "may", "limited evidence", etc.)
2. Does a weak/limited evidence section exist?
3. Does an open questions or uncertainty section exist?

Each signal contributes equally to the final score.

This is not a true probabilistic confidence metric

### Freshness

Looks at dates mentioned in evidence (either from the `date_mentioned` field or year patterns in the claim text). Recent years score higher:

- Current year or newer = 1.0
- 1 year old = 0.8
- 2 years = 0.6
- 3–4 years = 0.3
- 5+ years = 0.1

If no dates are found anywhere, it returns 0.5 (neutral — we genuinely don't know).

### Redundancy Detection

Compares every pair of evidence claims using word overlap. If two claims from different sources share >70% of their words, they're flagged as redundant. This helps spot when the same fact is being extracted multiple times from different pages.

### Reflection Quality

Checks whether the reflector agent actually drove iterative behavior:

- How many reflections happened?
- How many triggered `CONTINUE` (meaning it found gaps)?
- How many new search queries were generated?
- How many gaps were identified?
- `iterative_behavior: true/false` — did the agent actually iterate at least once with new queries?

### Evidence Per Subquestion

Simple count: total evidence linked to subquestions ÷ number of subquestions. Tells you whether evidence is evenly distributed or if some questions got ignored.

### Execution Metrics

Basic operational numbers that come straight from the run state:

- `iteration_depth` — how many iterations ran
- `runtime_seconds` — total wall-clock time
- `sources_analyzed` — total search results collected
- `stop_reason` — why the run ended (`sufficient_evidence`, `iteration_limit`, `source_limit`, `runtime_limit`)

---



