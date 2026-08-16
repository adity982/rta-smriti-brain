import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { chooseProject, isExactProjectIdentity } from "../dashboard-src/src/project-selection.js";
import { shellPathArg, shellQuote } from "../dashboard-src/src/shell-command.js";

const posixShell = process.platform === "win32"
  ? path.join(process.env.ProgramFiles || "C:\\Program Files", "Git", "bin", "sh.exe")
  : "/bin/sh";

test("PowerShell path arguments keep active syntax literal", { skip: process.platform !== "win32" }, () => {
  const separator = String.fromCharCode(92);
  const suffix = [
    "",
    "project",
    "$(Write-Output RTA_INJECTION_PROOF)",
    "$env:RTA_INJECTION_PROOF",
    "`whoami`",
    "\"double\" and quo'te\nnext",
  ].join(separator);
  const fixtureHome = ["C:", "Users", "fixture"].join(separator);
  const quoted = shellPathArg(`${fixtureHome}${suffix}`, "powershell");
  const result = spawnSync(
    "powershell",
    ["-NoProfile", "-NonInteractive", "-Command", `[Console]::Write(${quoted})`],
    {
      encoding: "utf8",
      env: { ...process.env, RTA_INJECTION_PROOF: "EXPANDED" },
      windowsHide: true,
    },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, `${process.env.USERPROFILE}${suffix}`);
  assert.match(result.stdout, /\$\(Write-Output RTA_INJECTION_PROOF\)/);
  assert.match(result.stdout, /\$env:RTA_INJECTION_PROOF/);
  assert.match(result.stdout, /`whoami`/);
  assert.doesNotMatch(result.stdout, /EXPANDED/);
});

test("POSIX path arguments keep active syntax literal", { skip: !existsSync(posixShell) }, () => {
  const suffix = "/project/$(printf RTA_INJECTION_PROOF)/$RTA_INJECTION_PROOF/`whoami`/\"double\" and quo'te\nnext";
  const quoted = shellPathArg(`/home/fixture${suffix}`, "posix");
  const environment = { ...process.env, RTA_INJECTION_PROOF: "EXPANDED" };
  const homeResult = spawnSync(posixShell, ["-c", 'printf %s "$HOME"'], {
    encoding: "utf8",
    env: environment,
    windowsHide: true,
  });
  assert.equal(homeResult.status, 0, homeResult.stderr);
  const result = spawnSync(posixShell, ["-c", `printf %s ${quoted}`], {
    encoding: "utf8",
    env: environment,
    windowsHide: true,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, `${homeResult.stdout}${suffix}`);
  assert.match(result.stdout, /\$\(printf RTA_INJECTION_PROOF\)/);
  assert.match(result.stdout, /\$RTA_INJECTION_PROOF/);
  assert.match(result.stdout, /`whoami`/);
  assert.doesNotMatch(result.stdout, /EXPANDED/);
});

test("generic arguments use literal shell quoting", () => {
  assert.equal(shellQuote("a'b", "powershell"), "'a''b'");
  assert.equal(shellQuote("a'b", "posix"), "'a'\"'\"'b'");
  assert.equal(shellPathArg("relative/$(unsafe)", "posix"), "'relative/$(unsafe)'");
});

test("project selection fails closed for missing or ambiguous identities", () => {
  const canonical = { project: "same-name", db_path: "C:/brains/canonical.sqlite", status: "ok" };
  const duplicate = { project: "same-name", db_path: "C:/brains/duplicate.sqlite", status: "ok" };
  const projects = [duplicate, canonical];

  assert.deepEqual(
    chooseProject(projects, null, { project: canonical.project, db_path: canonical.db_path }),
    { selected: canonical, reason: null },
  );
  assert.deepEqual(
    chooseProject(projects, canonical, { project: "same-name", db_path: "C:/brains/missing.sqlite" }),
    { selected: null, reason: "preferred_identity_missing" },
  );
  assert.deepEqual(
    chooseProject(projects, canonical, "same-name"),
    { selected: null, reason: "preferred_name_ambiguous" },
  );
  assert.equal(isExactProjectIdentity(canonical), true);
  assert.equal(isExactProjectIdentity({ project: "same-name" }), false);
  assert.equal(isExactProjectIdentity(null), false);
});
