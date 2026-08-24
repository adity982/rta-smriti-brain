import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function startFixtureServer(tempRoot) {
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  const child = spawn(python, [path.join(root, "scripts", "operator_qa_server.py"), tempRoot], {
    cwd: root,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const ready = new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => reject(new Error(`operator fixture timed out: ${stderr}`)), 30_000);
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
      const line = stdout.split(/\r?\n/).find((value) => value.trim().startsWith("{"));
      if (!line) return;
      clearTimeout(timer);
      try { resolve(JSON.parse(line)); } catch (error) { reject(error); }
    });
  });
  return { child, ready };
}

async function stopProcess(child) {
  if (child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

test("fast project data renders while continuity diagnostics are slow", async ({ browser }) => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), "rta-progressive-load-"));
  const { child, ready } = startFixtureServer(tempRoot);
  let context;
  let releaseSlowRequests;
  const slowRequestsReleased = new Promise((resolve) => { releaseSlowRequests = resolve; });
  try {
    const fixture = await ready;
    context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await page.route(/\/api\/(?:continuity|checkpoint)\?/, async (route) => {
      await slowRequestsReleased;
      await route.continue();
    });
    const graphResponse = page.waitForResponse((response) => response.url().includes("/api/graph?"));
    await page.goto(fixture.url, { waitUntil: "domcontentloaded" });
    await graphResponse;

    await expect(page.getByRole("button", { name: /^Imports, \d+ nodes\./ })).toBeVisible({ timeout: 2_000 });
    await expect(page.locator("footer.statusBar").getByRole("status")).toContainText(/core data available; checking/);
  } finally {
    releaseSlowRequests?.();
    await context?.close();
    await stopProcess(child);
    await rm(tempRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});

test("project switch clears captured events before the next brain loads", async ({ browser }) => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), "rta-project-isolation-"));
  const { child, ready } = startFixtureServer(tempRoot);
  let context;
  let releaseSecond;
  const secondReleased = new Promise((resolve) => { releaseSecond = resolve; });
  try {
    const fixture = await ready;
    context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    const addSecondProject = async (route) => {
      const response = await route.fetch();
      const payload = await response.json();
      const first = payload.projects?.[0];
      const second = first ? { ...first, project: "second-demo", ready: true, scan_state: "ready" } : null;
      await route.fulfill({ response, json: { ...payload, projects: second ? [...payload.projects, second] : payload.projects } });
    };
    await page.route("**/api/bootstrap", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      return addSecondProject(route);
    });
    await page.route("**/api/projects", addSecondProject);
    await page.route(/\/api\/capture\?/, async (route) => {
      const requestUrl = new URL(route.request().url());
      const project = requestUrl.searchParams.get("project");
      const mode = requestUrl.searchParams.get("mode");
      if (project === "second-demo") {
        await secondReleased;
        const empty = mode === "overview"
          ? { status: "ok", state: "stopped", sources: [], counts: {} }
          : mode === "replay"
            ? { status: "ok", events: [], count: 0 }
            : { status: "ok", gaps: [], counts: {} };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(empty) });
        return;
      }
      const response = await route.fetch();
      const payload = await response.json();
      if (mode === "replay") {
        payload.events = [{
          event_id: "old-project-event",
          project_sequence: 1,
          event_name: "old.project.secret.v1",
          recorded_at: "2026-08-24T00:00:00Z",
          source_id: "old-project-only",
          verification_status: "unverified",
          privacy_class: "internal",
        }];
      }
      await route.fulfill({ response, json: payload });
    });

    await page.goto(fixture.url, { waitUntil: "domcontentloaded" });
    const navigation = page.getByRole("navigation", { name: "Operator console navigation" });
    await navigation.getByRole("button", { name: /^Capture(?:\s|$)/ }).click();
    await expect(page.getByRole("button", { name: /old project secret/ })).toBeVisible();

    await page.locator(".activeProjectButton").click();
    await page.locator(".compactProject").filter({ has: page.getByText("second-demo", { exact: true }) }).click();
    await expect(page.locator(".activeProjectCopy strong")).toHaveText("second-demo");
    await expect(page.getByRole("button", { name: /old project secret/ })).toHaveCount(0);
    await expect(page.getByText("Loading captured events...", { exact: true })).toBeVisible();
  } finally {
    releaseSecond?.();
    await context?.close();
    await stopProcess(child);
    await rm(tempRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});

test("background registry completion preserves a newer operator project selection", async ({ browser }) => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), "rta-registry-race-"));
  const { child, ready } = startFixtureServer(tempRoot);
  let context;
  let releaseRegistry;
  const registryReleased = new Promise((resolve) => { releaseRegistry = resolve; });
  try {
    const fixture = await ready;
    context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const addSecondProject = async (route) => {
      const response = await route.fetch();
      const payload = await response.json();
      const first = payload.projects?.[0];
      const second = first ? { ...first, project: "second-demo", ready: true, scan_state: "ready" } : null;
      await route.fulfill({ response, json: { ...payload, projects: second ? [...payload.projects, second] : payload.projects } });
    };
    await page.route("**/api/bootstrap", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      return addSecondProject(route);
    });
    await page.route("**/api/projects", async (route) => {
      await registryReleased;
      await addSecondProject(route);
    });

    await page.goto(fixture.url, { waitUntil: "domcontentloaded" });
    await page.locator(".activeProjectButton").click();
    await page.locator(".compactProject").filter({ has: page.getByText("second-demo", { exact: true }) }).click();
    await expect(page.locator(".activeProjectCopy strong")).toHaveText("second-demo");

    releaseRegistry();
    await page.waitForResponse((response) => response.url().includes("/api/projects"));
    await expect(page.locator(".activeProjectCopy strong")).toHaveText("second-demo");
  } finally {
    releaseRegistry?.();
    await context?.close();
    await stopProcess(child);
    await rm(tempRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});

test("late file preview from the prior project is discarded", async ({ browser }) => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), "rta-preview-race-"));
  const { child, ready } = startFixtureServer(tempRoot);
  let context;
  let releasePreview;
  const previewReleased = new Promise((resolve) => { releasePreview = resolve; });
  try {
    const fixture = await ready;
    context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const addSecondProject = async (route) => {
      const response = await route.fetch();
      const payload = await response.json();
      const first = payload.projects?.[0];
      const second = first ? { ...first, project: "second-demo", ready: true, scan_state: "ready" } : null;
      await route.fulfill({ response, json: { ...payload, projects: second ? [...payload.projects, second] : payload.projects } });
    };
    await page.route("**/api/bootstrap", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      return addSecondProject(route);
    });
    await page.route("**/api/projects", addSecondProject);
    await page.route(/\/api\/file-preview\?/, async (route) => {
      const requestUrl = new URL(route.request().url());
      if (requestUrl.searchParams.get("project") !== "second-demo") {
        await previewReleased;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "ok", file: { name: "README.md", relative_path: "README.md", content: "PROJECT A PRIVATE PREVIEW" } }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(fixture.url, { waitUntil: "domcontentloaded" });
    const navigation = page.getByRole("navigation", { name: "Operator console navigation" });
    await navigation.getByRole("button", { name: "Files", exact: true }).click();
    await page.getByRole("button", { name: /README\.md/ }).first().click();
    await page.locator(".activeProjectButton").click();
    await page.locator(".compactProject").filter({ has: page.getByText("second-demo", { exact: true }) }).click();
    await expect(page.locator(".activeProjectCopy strong")).toHaveText("second-demo");

    releasePreview();
    await expect(page.getByText("PROJECT A PRIVATE PREVIEW", { exact: true })).toHaveCount(0);
  } finally {
    releasePreview?.();
    await context?.close();
    await stopProcess(child);
    await rm(tempRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});
