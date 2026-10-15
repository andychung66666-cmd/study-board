(() => {
  const ACTIVE = ['recording', 'recorded', 'transcribing', 'summarising'];
  const list = document.getElementById('talks');
  const empty = document.getElementById('empty');

  function row(talk) {
    const item = document.createElement('li');
    item.className = 'talk';
    const link = document.createElement('a');
    link.href = `/talk.html?id=${talk.id}`;
    link.textContent = talk.title;
    const meta = document.createElement('span');
    meta.className = 'meta';
    const when = new Date(talk.created_at).toLocaleString();
    const length = talk.duration_s ? ` · ${formatClock(talk.duration_s)}` : '';
    meta.textContent = ` ${when}${length} · `;
    const status = document.createElement('strong');
    status.className = `status-${talk.status}`;
    status.textContent = talk.status;
    item.append(link, meta, status);
    return item;
  }

  async function load() {
    const talks = await (await fetch('/api/talks')).json();
    list.replaceChildren(...talks.map(row));
    empty.hidden = talks.length > 0;
    if (talks.some((talk) => ACTIVE.includes(talk.status))) {
      setTimeout(load, pollInterval(3000));
    }
  }

  load();
})();
