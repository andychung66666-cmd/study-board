const pad = (n) => String(n).padStart(2, '0');

function formatClock(totalSeconds) {
  const seconds = Math.floor(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${pad(minutes)}:${pad(rest)}`;
}

function pollInterval(fallback) {
  return Number(new URLSearchParams(location.search).get('poll_ms') || fallback);
}
