// "Recent work" editor tab: every agent session in the project, grouped by day.
(function () {
  const vscode = acquireVsCodeApi();
  const app = document.getElementById('app');
  const FALLBACK = ['#1baf7a', '#eda100', '#e87ba4', '#6250d6'];
  const view = { agent: 'all', query: '', expanded: new Set() };
  let data = null;

  const send = (cmd, extra) => vscode.postMessage({ cmd, ...extra });

  // Summaries are Markdown from the agents; show them as plain text.
  const plain = (text) => String(text || '')
    .replace(/```[a-z]*\n?/g, '')
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, '$1$2')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/(^|\s)#{1,6}\s+/gm, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');

  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (key === 'class') el.className = value;
      else if (key === 'style') Object.assign(el.style, value);
      else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
      else if (value !== undefined && value !== null && value !== false) el.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child !== null && child !== undefined && child !== false) el.append(child.nodeType ? child : String(child));
    }
    return el;
  }

  function color(id) {
    if (id === 'claude' || id === 'codex') return getComputedStyle(document.body).getPropertyValue(`--series-${id}`).trim();
    const index = data.agents.findIndex((a) => a.id === id);
    return FALLBACK[Math.max(0, index) % FALLBACK.length];
  }

  const time = (iso) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const day = (iso) => new Date(iso).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

  function matches(e) {
    const q = view.query.trim().toLowerCase();
    return (view.agent === 'all' || e.agent === view.agent) && (!q || (e.summary || '').toLowerCase().includes(q));
  }

  function entry(e) {
    const key = e.agent + e.started;
    const open = view.expanded.has(key);
    const label = (data.agents.find((a) => a.id === e.agent) || {}).label || e.agent;
    const agent = data.agents.find((a) => a.id === e.agent && a.shown);
    const flip = () => { open ? view.expanded.delete(key) : view.expanded.add(key); render(); };
    return h('li', { class: 'session' },
      h('button', { class: 'entry', 'aria-expanded': String(open), onclick: flip },
        h('span', { class: 'dot', style: { background: color(e.agent) } }),
        h('span', { class: 'who' }, label),
        h('span', { class: 'small muted' },
          `${e.started && e.started !== e.saved_at ? time(e.started) + '–' : ''}${time(e.saved_at)} · ${e.turns} ${e.turns === 1 ? 'reply' : 'replies'}` +
          `${e.commit ? ' · @ ' + e.commit : ''}`),
        e.handoff_updated && h('span', { class: 'badge' }, 'handoff')),
      h('div', { class: open ? 'text' : 'text clamp' }, plain(e.summary) || '(no summary)'),
      open && h('div', { class: 'row' },
        agent && (agent.sessions && e.session_id
          ? h('button', { class: 'primary', onclick: () => send('session', { agent: e.agent, session: e.session_id }), title: 'Reopen this conversation' }, 'Open session')
          : h('button', { onclick: () => send('open', { agent: e.agent }) }, `Open ${label}`)),
        data.canReview && h('button', { onclick: () => send('review', { entry: e }),
          title: 'Another agent reviews the current changes, with this conversation\'s summary as context; the review can be sent back here' }, 'Ask for review'),
        h('button', { onclick: () => send('copy', { text: e.summary }), title: 'Copy this summary, e.g. to ask another agent for a review' }, 'Copy summary')));
  }

  function render() {
    if (!data) return app.replaceChildren(h('p', { class: 'muted' }, 'Loading…'));
    if (data.error) return app.replaceChildren(h('p', { class: 'error' }, data.error));
    const sessions = data.sessions.filter(matches);
    const used = [...new Set(data.sessions.map((e) => e.agent))];
    const days = [];
    for (const e of sessions) {
      const d = day(e.saved_at);
      if (!days.length || days[days.length - 1][0] !== d) days.push([d, []]);
      days[days.length - 1][1].push(e);
    }
    const search = h('input', { type: 'search', placeholder: 'Search summaries', 'aria-label': 'Search summaries', value: view.query });
    search.addEventListener('input', (ev) => {
      view.query = ev.target.value;
      render();
      const again = app.querySelector('input[type=search]');
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    });
    // replaceChildren, unlike h(), would print `false` and stringify arrays, so flatten and filter first.
    app.replaceChildren(...[
      h('h1', null, 'Recent work', h('span', { class: 'muted small' }, ` · ${data.name} · ${data.sessions.length} sessions`)),
      h('div', { class: 'toolbar' },
        h('div', { class: 'tabs', role: 'group' },
          ['all', ...used].map((id) => h('button', { 'aria-pressed': String(view.agent === id), onclick: () => { view.agent = id; render(); } },
            id === 'all' ? 'All' : (data.agents.find((a) => a.id === id) || {}).label || id))),
        search),
      !sessions.length && h('p', { class: 'muted' }, 'No sessions match.'),
      days.map(([d, list]) => h('section', null, h('h2', null, d), h('ul', { class: 'sessions' }, list.map(entry)))),
    ].flat().filter(Boolean));
  }

  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'recent') {
      data = event.data.data;
      render();
    }
  });
  render();
  send('ready');
})();
