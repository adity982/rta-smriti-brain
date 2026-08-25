# Connect Rta-Smriti to Zed

This community recipe connects Rta-Smriti's local stdio MCP server to Zed. It
is not an official integration or partnership with Zed Industries.

The recipe was validated on Windows 11 with Zed 1.16.2. The generated command
was probed through MCP initialize, `tools/list`, and ping with `mcp-doctor`.
Zed's documented `context_servers` format and server-status screen were used as
the host-side contract.

## Before editing Zed settings

Generate the configuration from the installed Rta-Smriti command. Do not copy
paths from another machine or write the command by hand.

For one project:

```powershell
& $RtaBrain --db "$BrainDir\project-name.sqlite" --json mcp-config --project project-name --name rta-smriti-project
& $RtaBrain --db "$BrainDir\project-name.sqlite" --json mcp-doctor --project project-name
```

For a read-only gateway across the project databases in one brain directory:

```powershell
& $RtaBrain --json mcp-config --brain-dir $BrainDir --name rta-smriti
```

Both forms are read-only by default. Do not add any `--allow-*` capability
unless you have reviewed and intend to grant it. For the single-project form,
continue only when `mcp-doctor` returns `"ready": true`. The multi-project form
routes by project name and fails closed when a name is ambiguous.

## Add the local server

Open **Settings > AI > MCP Servers**, select **Add Server > Add Local Server**,
then open the settings file with `zed: open settings file`. Zed stores custom
local servers under `context_servers`, while Rta-Smriti emits the portable
`mcpServers` shape used by many hosts.

Copy only the generated server entry and place it under `context_servers`:

```json
{
  "context_servers": {
    "rta-smriti-project": {
      "command": "<copy the generated command exactly>",
      "args": ["<copy every generated argument in order>"],
      "env": {}
    }
  }
}
```

Do not commit generated absolute paths. If you put a single-project entry in
`.zed/settings.json`, keep that local file out of version control, inspect it
before trusting the worktree, and use Zed's worktree trust prompt deliberately.
Use the user settings file for a multi-project gateway that should be available
across trusted worktrees.

Fully restart Zed after saving the entry and create a new Agent task. Existing
tasks do not acquire newly registered MCP tools. Return to **Settings > AI > MCP
Servers** and confirm that the indicator beside the server is green with the
tooltip **Server is active**. In the new task, ask Zed to list the Rta-Smriti
tools or explicitly mention the configured server name.

If the server is not active:

1. Run `mcp-doctor` again and require `"ready": true`.
2. Compare Zed's `command` and `args` with the newly generated entry; preserve
   every absolute path and argument boundary.
3. Confirm that the selected database, project root, and checkout have not
   moved. Regenerate the entry after an intentional rebind.
4. Check that the worktree is trusted when using `.zed/settings.json`.
5. Restart Zed completely and open another new Agent task.

Zed's current MCP configuration and status guidance is maintained in the
[official Zed MCP documentation](https://zed.dev/docs/ai/mcp). Its
[worktree-trust documentation](https://zed.dev/docs/worktree-trust) explains
how project-local MCP settings are gated.

