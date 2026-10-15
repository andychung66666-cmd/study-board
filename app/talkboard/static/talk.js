(() => {
  const ACTIVE = ['recording', 'recorded', 'transcribing', 'summarising'];
  const QUIET_SECONDS = 60;
  const talkId = new URLSearchParams(location.search).get('id');
  const $ = (id) => document.getElementById(id);
  let shownLines = -1;
  let timer = null;

  function renderLines(segments) {
    if (segments.length === shownLines) return;
    shownLines = segments.length;
    $('transcript').replaceChildren(...segments.map((segment) => {
      const line = document.createElement('p');
      line.className = 'line';
      const time = document.createElement('span');
      time.className = 'time';
      time.textContent = `[${formatClock(segment.start)}] `;
      line.append(time, document.createTextNode(segment.text));
      return line;
    }));
  }

  async function load() {
    clearTimeout(timer);
    const response = await fetch(`/api/talks/${talkId}`);
    if (!response.ok) {
      $('status').textContent = 'not found';
      return;
    }
    const talk = await response.json();
    $('title').textContent = talk.title;
    document.title = `${talk.title} · Talk Summary`;
    $('meta').textContent = `${new Date(talk.created_at).toLocaleString()} · ${talk.source} · ${talk.language}`;
    $('status').textContent = talk.status;

    $('error').hidden = !(talk.status === 'failed' && talk.error);
    if (talk.error) $('error').textContent = talk.error;
    $('retry').hidden = talk.status !== 'failed';
    $('recover').hidden = !(talk.status === 'recording' && talk.idle_s !== null && talk.idle_s > QUIET_SECONDS);

    if (talk.audio_url && $('player').getAttribute('src') !== talk.audio_url) {
      $('player').setAttribute('src', talk.audio_url);
    }
    $('player').hidden = !talk.audio_url;
    renderLines(talk.segments);

    if (ACTIVE.includes(talk.status)) timer = setTimeout(load, pollInterval(3000));
  }

  async function act(path) {
    const response = await fetch(`/api/talks/${talkId}/${path}`, { method: 'POST' });
    if (!response.ok) {
      $('error').textContent = (await response.json()).detail;
      $('error').hidden = false;
      return;
    }
    load();
  }

  $('retry').addEventListener('click', () => act('retry'));
  $('recover').addEventListener('click', () => act('recover'));
  load();
})();
