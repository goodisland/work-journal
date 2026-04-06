# Project defaults

## Language
- Reply in Japanese unless the user explicitly requests another language.

## Working style
- Before making large changes, summarize the plan briefly.
- Prefer small, reversible changes.
- Do not perform destructive actions unless explicitly requested.
- State assumptions clearly when logs or requirements are incomplete.

## Validation
- After code changes, run the smallest relevant verification possible.
- Do not claim completion until the relevant checks pass or the remaining gap is stated clearly.

## Skills
- Use task-specific Skills for repeated workflows.
- For Python service failures, use `debugging-python-services`.
- For AWS S3 image retrieval or sync workflows, use `aws-s3-image-sync`.
- For paper figures, maps, and export preparation, use `paper-figure-export`.
- For Japanese business email/message drafting, use `writing-japanese-work-replies`.