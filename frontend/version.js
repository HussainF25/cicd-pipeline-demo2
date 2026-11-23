// Shows which release is running (version, build number, commit) using the open /health endpoint.
// The CI/CD pipeline writes these details at build time, so every deployment is visible in the app.
(async function showRelease() {
  try {
    const res = await fetch("/health", { cache: "no-store" });
    if (!res.ok) return;
    const info = await res.json();
    const commit = info.commit === "local" ? "local" : info.commit.slice(0, 7);
    document.querySelectorAll("[data-version]").forEach((el) => (el.textContent = `v${info.version}`));
    document.querySelectorAll("[data-release-note]").forEach((el) => (el.textContent = info.release_note));
    document.querySelectorAll("[data-build]").forEach((el) => (el.textContent = `build ${info.build_number} · ${commit}`));
    document.querySelectorAll("[data-release]").forEach((el) => (el.hidden = false));
  } catch (err) {
    console.warn("Could not load release info", err);
  }
})();
