# Humanizer: AI Writing Patterns to Eliminate

Based on Wikipedia's "Signs of AI writing" guide (WikiProject AI Cleanup).

## Content Patterns

### Inflated Significance and Legacy
Words to watch: stands/serves as, is a testament/reminder, a vital/significant/crucial/pivotal/key role/moment, underscores/highlights its importance/significance, reflects broader, symbolizing its ongoing/enduring/lasting, contributing to the, setting the stage for, marking/shaping the, represents/marks a shift, key turning point, evolving landscape, focal point, indelible mark, deeply rooted

Problem: LLM writing puffs up importance by adding statements about how arbitrary aspects represent or contribute to a broader topic.

### Superficial -ing Analyses
Words to watch: highlighting/underscoring/emphasizing..., ensuring..., reflecting/symbolizing..., contributing to..., cultivating/fostering..., encompassing..., showcasing...

Problem: AI tacks present participle phrases onto sentences to add fake depth.

### Promotional Language
Words to watch: boasts a, vibrant, rich (figurative), profound, enhancing its, showcasing, exemplifies, commitment to, natural beauty, nestled, in the heart of, groundbreaking (figurative), renowned, breathtaking, must-visit, stunning

### Vague Attributions
Words to watch: Industry reports, Observers have cited, Experts argue, Some critics argue, several sources/publications

Problem: AI attributes opinions to vague authorities without specific sources.

### Formulaic "Challenges and Future Prospects"
Words to watch: Despite its... faces several challenges..., Despite these challenges, Future Outlook

Problem: Formulaic "Challenges" sections that hedge with optimism.

## Language and Grammar Patterns

### AI Vocabulary (High-Frequency Words)
Additionally, align with, crucial, delve, emphasizing, enduring, enhance, fostering, garner, highlight (verb), interplay, intricate/intricacies, key (adjective), landscape (abstract noun), pivotal, showcase, tapestry (abstract noun), testament, underscore (verb), valuable, vibrant

### Copula Avoidance
Words to watch: serves as/stands as/marks/represents [a], boasts/features/offers [a]

Problem: LLMs substitute elaborate constructions for simple "is"/"are"/"has".

Fix: Use "is", "are", "has" directly.

### Negative Parallelisms
Problem: "Not only...but..." or "It's not just about..., it's..." constructions are overused.

### Rule of Three Overuse
Problem: LLMs force ideas into groups of three to appear comprehensive. Use two items or one instead.

### Synonym Cycling (Elegant Variation)
Problem: AI has repetition-penalty code causing excessive synonym substitution. Use consistent terms.

### False Ranges
Problem: "from X to Y" constructions where X and Y aren't on a meaningful scale.

## Style Patterns

### Em Dash Overuse
Use commas, periods, or parentheses instead of em dashes.

### Excessive Boldface
Don't mechanically emphasize phrases in boldface.

### Curly Quotation Marks
Use straight quotes ("..."), not curly quotes.

### Hyphenated Word Pair Overuse
Words to watch when over-hyphenated: cross-functional, data-driven, decision-making, well-known, high-quality, real-time, long-term, end-to-end

## Communication Patterns

### Chatbot Artifacts
Remove: "I hope this helps", "Of course!", "Certainly!", "Would you like...", "let me know", "here is a..."

### Knowledge-Cutoff Disclaimers
Remove: "as of [date]", "While specific details are limited/scarce...", "based on available information..."

### Sycophantic Tone
Remove overly positive, people-pleasing language: "Great question!", "You're absolutely right!", "That's an excellent point"

## Filler and Hedging

### Filler Phrases to Cut
- "In order to" -> "To"
- "Due to the fact that" -> "Because"
- "At this point in time" -> "Now"
- "has the ability to" -> "can"
- "It is important to note that" -> cut entirely

### Excessive Hedging
Remove over-qualifying: "could potentially possibly be argued that... might have some effect"

### Generic Positive Conclusions
Remove vague upbeat endings: "The future looks bright", "Exciting times lie ahead", "a major step in the right direction"
