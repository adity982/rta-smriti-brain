export function isExactProjectIdentity(value) {
  return Boolean(
    value
    && typeof value === "object"
    && typeof value.project === "string"
    && typeof value.db_path === "string",
  );
}

export function chooseProject(availableProjects, currentProject = null, preferredProject = null) {
  const available = Array.isArray(availableProjects) ? availableProjects : [];
  const preferredIdentity = isExactProjectIdentity(preferredProject)
    ? { project: preferredProject.project, db_path: preferredProject.db_path }
    : null;

  if (preferredIdentity) {
    const selected = available.find((project) => (
      project.db_path === preferredIdentity.db_path && project.project === preferredIdentity.project
    )) || null;
    return { selected, reason: selected ? null : "preferred_identity_missing" };
  }

  if (typeof preferredProject === "string") {
    const matches = available.filter((project) => project.project === preferredProject);
    if (matches.length === 1) return { selected: matches[0], reason: null };
    if (matches.length > 1) return { selected: null, reason: "preferred_name_ambiguous" };
  }

  const current = available.find((project) => (
    currentProject && project.db_path === currentProject.db_path && project.project === currentProject.project
  ));
  return {
    selected: current || available.find((project) => project.status === "ok") || available[0] || null,
    reason: null,
  };
}
