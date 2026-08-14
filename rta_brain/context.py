from .db import search, stale_check


def build_context_pack(conn, task: str, project: str = "default", limit: int = 8) -> str:
    results = search(conn, task, project=project, limit=limit)
    stale = stale_check(conn, project=project)
    stale_status = "fresh" if stale["changed"] == 0 and stale["missing"] == 0 else "stale"

    lines = [
        "# Rta-Smriti Context Pack",
        "",
        f"Project: {project}",
        f"Task: {task}",
        f"stale status: {stale_status}",
        "",
        "## Must-Know Memories",
    ]
    if results["memories"]:
        for memory in results["memories"]:
            lines.extend(
                [
                    f"- [{memory['type']}] {memory['text']}",
                    f"  Pramana: {memory['pramana']} | confidence: {memory['confidence']:.2f} | priority: {memory['priority']} | status: {memory['status']}",
                ]
            )
    else:
        lines.append("- None retrieved.")

    lines.extend(["", "## Relevant Files And Chunks"])
    if results["chunks"]:
        for chunk in results["chunks"]:
            excerpt = " ".join(chunk["text"].split())
            if len(excerpt) > 240:
                excerpt = excerpt[:237] + "..."
            lines.extend([f"- {chunk['path']}", f"  Evidence: {excerpt}"])
    else:
        lines.append("- None retrieved.")

    lines.extend(["", "## Freshness"])
    lines.append(f"- fresh: {stale['fresh']} | changed: {stale['changed']} | missing: {stale['missing']}")
    for detail in stale["details"][:10]:
        if detail["status"] != "fresh":
            lines.append(f"- {detail['status']}: {detail['title']}")

    lines.extend(
        [
            "",
            "## Operating Policy",
            "- Treat pratyaksha as direct evidence, sabda as trusted instruction/documentation, anumana as inference, smriti as prior memory, and kalpana as hypothesis.",
            "- Re-read changed or missing evidence before acting on memory-derived claims.",
            "- Prefer narrow file reads guided by this pack instead of broad repository scans.",
        ]
    )
    return "\n".join(lines) + "\n"
