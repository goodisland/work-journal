---
name: aws-s3-image-sync
description: Use when working with AWS S3 image collections, date-partitioned camera folders, selective sync, prefix design, CLI retrieval, or scripts that download only specific time ranges. Trigger for aws s3 ls, aws s3 sync, prefix filtering, camera image retrieval, and date/hour-based collection. Do not use for generic AWS architecture design or IAM policy review unless directly tied to the retrieval workflow.
---

# aws-s3-image-sync

## Purpose
Handle efficient retrieval and selective sync of camera images stored in structured S3 paths.

## Typical path pattern
- bucket/prefix/yyyyMMdd/HH/camXX/filename.jpg
- Example: 46001-harada/images/20260322/10/cam01/20260322-100011.0780.jpg

## When to use
- download only one week of images
- sync date range only
- retrieve by hour or camera
- generate Python scripts for selective download
- optimize prefix traversal instead of checking every file

## Do not use
- broad AWS cost optimization
- VPC design
- IAM least-privilege design not tied to this task

## Workflow
1. Confirm the path structure.
2. Derive the narrowest possible prefixes from:
   - start date
   - end date
   - hours
   - camera ids
3. Prefer prefix-based listing over per-file brute force.
4. Generate either:
   - direct CLI commands
   - a Python script using prefix iteration
5. Add retry/error handling only where useful.
6. Keep output paths deterministic.

## Retrieval rules
- Prefer directory-level traversal when the partition pattern is stable.
- Skip clearly absent hour directories instead of forcing empty scans.
- Keep workers aligned to date/hour groups when parallelism is requested.
- Avoid full-bucket scans unless there is no reliable partition pattern.

## Verification
- sampled files exist locally
- expected date/hour/camera coverage matches the request
- no obviously missing prefix in the requested range
- script logs skipped empty prefixes clearly

## Output format
- Assumed path pattern
- Retrieval strategy
- Command or script
- Verification notes
- Known limitations