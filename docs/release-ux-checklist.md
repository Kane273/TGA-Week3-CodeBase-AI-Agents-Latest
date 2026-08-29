# ResearchGuard UX release checklist

Use this checklist after the feature freeze. Record the tester, device, browser, assistive
technology, date, and result for every manual session.

## Usability and language

- Complete the moderated test with three to five participants.
- Fix problems repeated by at least two participants before considering isolated requests.
- Confirm users distinguish automated screening from expert evidence validation.
- Confirm every button starts with a clear action and unexplained technical terms are absent
  from simple view.
- Verify approval is not possible without seeing the responsibility notice and readiness list.

## Assistive technology

- Complete a run using only the keyboard; verify logical focus order and visible focus.
- Complete question entry, evidence review, comments, and approval with VoiceOver on Safari.
- Repeat the critical path with NVDA on Firefox or Chrome.
- Test at 200% browser zoom without lost content or two-dimensional page scrolling.
- Enable reduced motion, high contrast, and operating-system forced colors.
- Confirm progress announcements describe meaningful state changes without repeated speech.

## Physical mobile devices

- Test current iPhone/Safari and Android/Chrome devices in portrait and landscape.
- Confirm all touch targets are comfortably tappable and dialogs fit above the virtual keyboard.
- Confirm safe-area spacing, page restoration, graph timeline scrolling, and external source links.
- Test slow-network, offline, interrupted SSE, denied microphone, and background-tab recovery.

## Performance calibration

- Run at least five deterministic and five live workflows.
- Compare displayed estimates with observed completion times and investigate large outliers.
- Confirm skeletons and status language appear immediately and never imply a stalled run failed.

## Privacy and release freeze

- Verify the privacy center accurately matches enabled providers and deployment configuration.
- Export browser data, clear it, delete a server run, and confirm each outcome.
- Confirm no sensitive participant data appears in screenshots, fixtures, traces, or logs.
- After freeze, accept only defect, accessibility, security, copy-consistency, and performance fixes.
- Run Python tests, Ruff, Playwright/Axe, visual regression, and wheel-content verification.
