# Construction Scheme Audit Method Figure Design

## Purpose

Create a publication-ready, schematic-led method figure for the proposed
graph-retrieval-augmented construction-scheme audit method.

The figure must communicate one central conclusion:

> Separating historical-case graph retrieval from authoritative normative
> clause retrieval, then constraining semantic judgement with document and
> normative evidence, produces an auditable draft that remains subject to
> human review.

## Figure contract

- **Archetype:** schematic-led composite.
- **Backend:** Python with Matplotlib only.
- **Target:** a Nature-style, two-column-width method overview.
- **Final size:** approximately 180 mm × 115 mm.
- **Primary export:** editable SVG with text retained as text.
- **Secondary exports:** PDF and 600 dpi PNG.
- **Background:** white.
- **Reading direction:** left to right.

## Panel map

### a. Input and task definition

Show the construction-scheme Word document entering a structure-preserving
parser. Represent paragraphs, tables, images, and source locations as evidence
blocks. Human-confirmed audit year and work type instantiate a versioned audit
task set.

### b. Hybrid audit routing

Split the task set into three routes:

1. deterministic template checks;
2. the dedicated JSA rule engine;
3. semantic audit tasks.

The semantic route is visually dominant because it contains the proposed
method.

### c. Dual-source graph-vector retrieval

Show two deliberately separated knowledge sources:

- a normative-clause vector index supplying authoritative compliance evidence,
  filtered by declared standards, year, version, and applicability;
- a historical-case knowledge graph supplying query expansion and engineering
  reasonableness clues.

Graph-expanded concepts feed a second normative retrieval step. Historical
case relations must not visually enter the authoritative-evidence channel.

### d. Evidence-constrained judgement

Show the language model receiving document evidence, applicable normative
clauses, and graph-derived clues. A dual-evidence gate permits a definite
non-compliance finding only when both document evidence and applicable
normative text are present. Reasonableness findings remain labelled as
graph-supported clues rather than legal evidence.

### e. Traceable output and human review

Merge deterministic, JSA, compliance, and reasonableness findings into an
intelligent audit draft. Show evidence IDs being resolved back to immutable
source excerpts, followed by human confirmation, modification, or rejection,
and then the final audit report.

## Visual language

- **Primary blue:** document flow and the proposed method.
- **Teal/green:** normative clauses and authoritative evidence.
- **Muted violet:** historical cases, knowledge graph, and engineering clues.
- **Warm orange/red:** evidence gates, validation, and reviewer attention.
- **Neutral grey:** deterministic support components and metadata.

Use rounded rectangles, thin directional arrows, direct labels, and whitespace
instead of decorative panel borders. Keep saturation low and reserve the warm
accent for the evidence gate and human decision.

## Integrity and reviewer-risk controls

- Do not imply that knowledge-graph triples are normative evidence.
- Do not imply that the model makes the final decision.
- Make time/version applicability visible before normative retrieval.
- Distinguish deterministic, JSA, compliance, and reasonableness routes.
- Preserve the fallback path from unavailable graph retrieval to normative
  vector retrieval.
- Avoid quantitative performance claims because no experimental results are
  supplied for this figure.
- Keep every output traceable to document, normative, or graph source IDs.

## Acceptance criteria

The figure is acceptable when:

1. the dual-source division is understandable without reading the manuscript;
2. the evidence gate is the strongest visual emphasis;
3. normative evidence and graph clues cannot be confused;
4. human final review is explicit;
5. all Chinese labels remain legible at final publication width;
6. SVG text remains editable and the PDF/PNG exports render consistently.
