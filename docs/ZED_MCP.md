# Use Rta-Smriti Brain with Zed

This recipe configures Rta-Smriti as a custom local MCP server in Zed. Zed's
official [MCP documentation](https://zed.dev/docs/ai/mcp) calls these
`context_servers`. Rta-Smriti is an independent project and is not affiliated
with or endorsed by Zed.

## Generate the server entry

Generate the configuration instead of writing command paths by hand. The output
contains an absolute `command` and `args` under
`config.mcpServers.<name>`.

For one project:

```powershell
& $RtaBrain --db "$BrainDir\project-name.sqlite" --json mcp-config --project project-name --name rta-smriti-project
```

```bash
"$RtaBrain" --db "$BrainDir/project-name.sqlite" --json mcp-config --project project-name --name rta-smriti-project
```

For a read-only gateway across every project in one brain directory:

```powershell
& $RtaBrain --json mcp-config --brain-dir $BrainDir --name rta-smriti
```

```bash
"$RtaBrain" --json mcp-config --brain-dir "$BrainDir" --name rta-smriti
```

The multi-project gateway exposes project-scoped read tools and requires the
project name on every call. Mutation, ingestion, governance, continuity, and
other capability-gated operations require a separately configured
single-project server with explicit startup grants.

## Add it to Zed

In Zed, open **Settings > AI > MCP Servers**, choose **Add Server > Add Local
Server**, or run `zed: open settings file`. Copy the generated server object
under Zed's `context_servers` key, preserving the generated command and every
argument:

```json
{
  "context_servers": {
    "rta-smriti-project": {
      "command": "<generated command>",
      "args": ["<generated argument 1>", "<generated argument 2>"],
      "env": {}
    }
  }
}
```

Do not commit user-level settings or replace the generated absolute paths with
paths from another machine. For project settings, review Zed's worktree trust
prompt before allowing the local server to start.

## Verify

Before registering the server, probe the exact single-project command:

```powershell
& $RtaBrain --db "$BrainDir\project-name.sqlite" --json mcp-doctor --project project-name
```

```bash
"$RtaBrain" --db "$BrainDir/project-name.sqlite" --json mcp-doctor --project project-name
```

For a multi-project gateway, run this probe for each project database you plan
to access. A passing probe verifies MCP initialization, tool listing, and ping;
it does not register the server in Zed.

Fully quit and restart Zed after saving the settings, then open a new Agent
Panel task. In **Settings > AI > MCP Servers**, confirm the server indicator is
green and reports **Server is active**. Existing tasks cannot acquire newly
registered tools dynamically.

**Verification scope:** The instructions were checked against Zed 1.16.2's
official MCP documentation on Windows 11, and the generated server command was
validated with `mcp-doctor`. Zed itself was not installed in the verification
environment, so the settings UI and live Agent Panel connection were not tested.
The generated command is OS-specific; the same placement steps apply on macOS
and Linux, but those platforms were not tested for this recipe.
