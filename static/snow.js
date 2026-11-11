function isSnowSeason(date) {
  return date.getMonth() === 11;
}

if (typeof module !== "undefined") {
  module.exports = { isSnowSeason };
}

if (typeof document !== "undefined") {
  let snow = null;

  function updateSnow() {
    const now = new Date();
    if (isSnowSeason(now) && !snow) {
      snow = document.createElement("div");
      snow.className = "snowfall";
      snow.setAttribute("aria-hidden", "true");
      for (let i = 0; i < 56; i += 1) {
        const flake = document.createElement("span");
        flake.className = "snowflake";
        flake.textContent = "❄";
        flake.style.left = `${(i * 37) % 100}%`;
        flake.style.setProperty("--snow-duration", `${12 + (i % 7) * 2}s`);
        flake.style.setProperty("--snow-delay", `${-(i * 3) % 24}s`);
        flake.style.fontSize = `${8 + (i % 4) * 2}px`;
        snow.appendChild(flake);
      }
      document.body.prepend(snow);
    } else if (!isSnowSeason(now) && snow) {
      snow.remove();
      snow = null;
    }
    const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    window.setTimeout(updateSnow, tomorrow - now + 50);
  }

  updateSnow();
}
