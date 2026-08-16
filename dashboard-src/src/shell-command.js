export function shellQuote(value, shellKind) {
  const text = String(value ?? "");
  if (shellKind === "powershell") return `'${text.replaceAll("'", "''")}'`;
  return `'${text.replaceAll("'", `'"'"'`)}'`;
}

function portableHomeSuffix(text, shellKind) {
  if (shellKind === "powershell") {
    if (text.startsWith("$env:USERPROFILE")) return text.slice("$env:USERPROFILE".length);
    return text.match(/^[A-Za-z]:[\\/]Users[\\/][^\\/]+([\s\S]*)$/i)?.[1] ?? null;
  }
  if (text.startsWith("$HOME")) return text.slice("$HOME".length);
  return text.match(/^\/(?:Users|home)\/[^/]+([\s\S]*)$/i)?.[1] ?? null;
}

export function shellPathArg(value, shellKind) {
  const text = String(value ?? "");
  const suffix = portableHomeSuffix(text, shellKind);
  if (suffix === null) return shellQuote(text, shellKind);
  if (shellKind === "powershell") {
    return suffix ? `($env:USERPROFILE + ${shellQuote(suffix, shellKind)})` : "$env:USERPROFILE";
  }
  return suffix ? `"$HOME"${shellQuote(suffix, shellKind)}` : '"$HOME"';
}
