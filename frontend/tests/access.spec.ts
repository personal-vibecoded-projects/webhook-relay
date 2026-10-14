import { randomBytes, randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

test.use({ trace: "off" }); // Auth cookies and passwords must not be saved in trace artifacts.
test.skip(
  process.env.RUN_AUTH_E2E !== "1",
  "Requires the migrated Compose database",
);

async function login(
  page: Page,
  username: string,
  password: string,
  register = false,
) {
  try {
    await page.goto("/");
    await expect(
      page.getByRole("button", { name: "New account", exact: true }),
    ).toBeVisible();
    if (register)
      await page
        .getByRole("button", { name: "New account", exact: true })
        .click();
    await page.getByLabel("Username", { exact: true }).fill(username);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page
      .getByRole("button", {
        name: register ? "Create account" : "Sign in",
        exact: true,
      })
      .click();
    await expect(page.getByText("Signed in as")).toBeVisible();
  } catch {
    await page
      .getByLabel("Password", { exact: true })
      .fill("", { timeout: 1000 })
      .catch(() => {});
    // Do not include Playwright action logs containing credential arguments.
    throw new Error("Account setup through the dashboard failed");
  }
}

test("signup, workspace, invitation, viewer restrictions, and ownership transfer", async ({
  page,
  browser,
}) => {
  const suffix = randomUUID().slice(0, 8);
  const ownerName = `owner-${suffix}`;
  const viewerName = `viewer-${suffix}`;
  const ownerPassword = randomBytes(24).toString("base64url");
  const viewerPassword = randomBytes(24).toString("base64url");
  const slug = `team-${suffix}`;
  const origin = process.env.E2E_BASE_URL!;

  // Register a recipient without any email integration or token-bearing URL.
  const recipient = await browser.newContext({ baseURL: origin });
  const viewer = await recipient.newPage();
  try {
    await login(viewer, viewerName, viewerPassword, true);
    await login(page, ownerName, ownerPassword, true);
    await page
      .getByLabel("Workspace name", { exact: true })
      .fill("Demo access team");
    await page.getByLabel("Workspace slug", { exact: true }).fill(slug);
    await page
      .getByRole("button", { name: "Create workspace", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Demo access team access" }),
    ).toBeVisible();
    await page.getByLabel("Invite by username").fill(viewerName);
    await page.getByLabel("Invitation role").selectOption("viewer");
    await page
      .getByRole("button", { name: "Send invitation", exact: true })
      .click();
    await expect(
      page.getByText(`${viewerName} · viewer · pending`, { exact: true }),
    ).toBeVisible();
    await viewer
      .getByRole("button", { name: "Refresh workspace access", exact: true })
      .click();
    await viewer
      .getByRole("button", {
        name: "Accept invitation to Demo access team",
        exact: true,
      })
      .click();
    await expect(
      viewer.getByRole("region", { name: "Demo access team access" }),
    ).toBeVisible();
    await expect(
      viewer.getByRole("button", { name: "Send invitation", exact: true }),
    ).toHaveCount(0);
    await expect(
      viewer.getByRole("button", { name: "Save name", exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "Refresh workspace access", exact: true })
      .click();
    await page
      .getByRole("button", {
        name: `Transfer ownership to ${viewerName}`,
        exact: true,
      })
      .click();
    await page
      .getByRole("button", {
        name: `Confirm Transfer ownership to ${viewerName}`,
        exact: true,
      })
      .click();
    await expect(
      page.getByText("workspace · ownership transferred", { exact: true }),
    ).toBeVisible();
    await viewer
      .getByRole("button", { name: "Refresh workspace access", exact: true })
      .click();
    await expect(
      viewer.getByRole("button", { name: "Save name", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Sign in", exact: true }),
    ).toBeVisible();
    await login(page, ownerName, ownerPassword);
    await expect(
      page.getByRole("region", { name: "Demo access team access" }),
    ).toBeVisible();
  } finally {
    await recipient.close();
  }
});
