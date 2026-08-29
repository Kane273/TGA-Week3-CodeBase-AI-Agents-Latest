# ResearchGuard moderated usability test

## Goal

Determine whether a first-time user can understand the multi-agent workflow, assess evidence,
identify unresolved concerns, request a revision, and make an informed approval decision.

## Participants

Recruit three to five people. Include at least one researcher or student, one quantitatively
oriented reviewer, and one participant unfamiliar with agent systems. Do not train them on the
interface before the session.

## Session script

1. Ask the participant to submit a research question and explain what they expect to happen.
2. Ask them to determine whether the collected evidence is trustworthy.
3. Ask them to find one point where agents disagreed and explain how it was resolved.
4. Ask them to identify anything preventing approval.
5. Ask them to leave a comment, request one protocol change, and find the resulting revision.
6. Ask them to export the final protocol and explain who remains responsible for the decision.

Do not provide interface hints. Ask the participant to think aloud. Record task completion,
wrong turns, points of hesitation, and the participant's own words.

## Success criteria

- At least 80% of tasks completed without moderator intervention.
- Evidence verification and model-generated confidence are not mistaken for expert validation.
- Participants find unresolved risks and the approval-readiness checklist before approving.
- Median time to locate agent disagreement is under 60 seconds.
- Median ease score is at least 4 out of 5.

## Capture and analysis

Use **Give usability feedback** after each session. Feedback is retained only in browser local
storage. Select **Export study data** to download the JSON file, then remove names or sensitive
research content before sharing it. Group observations by navigation, terminology, trust,
decision confidence, accessibility, and perceived performance. Prioritize repeated problems
over feature requests from a single participant.
