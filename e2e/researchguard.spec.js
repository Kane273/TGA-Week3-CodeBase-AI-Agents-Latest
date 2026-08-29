const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("rg-onboarded", "true");
    localStorage.setItem("rg-view", "expert");
  });
  await page.goto("/");
});

test("core workspace is keyboard reachable and responsive", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "ResearchGuard" })).toBeVisible();
  await page.getByRole("button", { name: "Connection settings" }).click();
  await expect(page.getByLabel("User ID")).toBeVisible();
  await expect(page.getByText("Demonstration access control")).toBeVisible();
  await page.getByRole("button", { name: "Change color theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Privacy" }).click();
  await expect(page.getByRole("dialog", { name: "Privacy and data controls" })).toBeVisible();
  await expect(page.getByText("Do not submit sensitive participant data.")).toBeVisible();
  expect(await page.evaluate(() => safeExternalUrl("javascript:alert(1)"))).toBe("#");
  expect(await page.evaluate(() => safeExternalUrl("https://pubmed.ncbi.nlm.nih.gov/"))).toMatch(/^https:/);
});

test("home screen has no serious accessibility violations", async ({ page }) => {
  const results = await new AxeBuilder({ page }).analyze();
  const severe = results.violations.filter(v => ["serious", "critical"].includes(v.impact));
  expect(severe).toEqual([]);
});

test("guided workflow exposes live agent progress", async ({ page }) => {
  await page.getByRole("button", { name: "Guided showcase" }).click();
  await expect(page.getByRole("heading", { name: /Planning research|Collecting evidence|Designing study|Reviewing protocol|Awaiting human approval|Protocol complete/ })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Agent graph" })).toBeVisible();
});

test("workspace visual regression", async ({ page }) => {
  const isMobile = (page.viewportSize()?.width ?? Infinity) < 760;
  await page.addStyleTag({
    content:
      "#recent-runs{height:100px;overflow:hidden}.benchmark-proof{height:96px;overflow:hidden}",
  });
  await expect(page).toHaveScreenshot("workspace.png", {
    fullPage: true,
    animations: "disabled",
    mask: [page.locator("#recent-runs"), page.locator(".benchmark-proof")],
    // Mobile text wraps and rasterizes differently on macOS and Linux runners.
    maxDiffPixelRatio: isMobile ? 0.08 : 0.03
  });
});

test("command palette and high contrast visual regression", async ({ page }) => {
  await page.getByRole("button", { name: "Open command palette" }).click();
  await expect(page.getByRole("dialog", { name: "Command palette" })).toHaveScreenshot("commands.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.03
  });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /High contrast/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-contrast", "high");
});

test("completed protocol exposes trust views and presentation mode", async ({ page }) => {
  await page.getByRole("button", { name: "Convene council" }).click();
  await expect(page.getByRole("heading", { name: "Run scorecard" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Evidence-to-protocol traceability" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Agent disagreement" })).toBeVisible();
  await page.getByRole("button", { name: "Enter presentation mode" }).click();
  await expect(page.getByText("ResearchGuard presentation")).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("A council, not a chatbot")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("ResearchGuard presentation")).toBeHidden();
});

test("progressive disclosure, roles, and activity inbox are usable", async ({ page }) => {
  await page.locator("#view-mode").selectOption("simple");
  await expect(page.getByRole("heading", { name: "Agent graph" })).toBeHidden();
  await page.locator("#view-mode").selectOption("expert");
  await page.locator("#role-select").selectOption("ethics");
  await expect(page.locator(".eyebrow")).toHaveText("Ethics and safeguards workspace");
  await page.getByRole("button", { name: "Open activity inbox" }).click();
  await expect(page.getByRole("dialog", { name: "Activity inbox" })).toBeVisible();
});

test("completed protocol supports comments, readiness, and mobile workflow", async ({ page }) => {
  await page.getByRole("button", { name: "Convene council" }).click();
  await expect(page.getByRole("heading", { name: "Approval readiness" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("You remain the decision-maker.")).toBeVisible();
  await expect(page.locator("#progress-estimate")).toContainText("paused or complete");
  await page.getByLabel("Add comment").fill("Confirm the outcome assessor remains blinded.");
  await page.getByRole("button", { name: "Post comment" }).click();
  await expect(page.getByText("Confirm the outcome assessor remains blinded.", { exact: true })).toBeVisible();
  if ((await page.viewportSize()).width < 760) {
    await page.getByRole("button", { name: "Open full workflow timeline" }).click();
    await expect(page.getByRole("dialog", { name: "Workflow timeline" })).toBeVisible();
  }
});

test("evidence preferences and usability feedback persist locally", async ({ page }) => {
  await page.getByRole("button", { name: "Convene council" }).click();
  await expect(page.getByRole("heading", { name: "Claim-level evidence" })).toBeVisible({ timeout: 20_000 });
  await page.locator(".evidence-card summary").first().click();
  const bookmark = page.getByRole("button", { name: "Bookmark evidence" }).first();
  await bookmark.click();
  await expect(page.locator("[data-bookmark]").first()).toHaveAttribute("aria-pressed", "true");
  page.once("dialog", dialog => dialog.accept("Verified studies"));
  await page.getByRole("button", { name: "Save filter" }).click();
  await expect(page.locator("#saved-filters")).toContainText("Verified studies");
  await page.getByRole("button", { name: "Give usability feedback" }).click();
  await page.getByLabel("What was confusing?").fill("The score terminology took a moment to understand.");
  await page.getByRole("button", { name: "Save feedback" }).click();
  await expect(page.getByText("Usability feedback saved locally.")).toBeVisible();
});
