// Sidebar panel. Receives state from extension.js and posts user actions back.
(function () {
  const vscode = acquireVsCodeApi();
  const app = document.getElementById('app');
  const tip = document.getElementById('tip');
  const SVG = 'http://www.w3.org/2000/svg';
  const DOCS = [['handoff', 'Handoff'], ['status', 'Status'], ['decisions', 'Decisions'], ['agents', 'AGENTS.md']];
  // Categorical slots in fixed order; agents added later take the next free one.
  const FALLBACK = ['#1baf7a', '#eda100', '#e87ba4', '#6250d6'];

  const STALE_MINUTES = 60;
  // Kept across re-renders; Recent work starts collapsed.
  const view = { recentOpen: false, expanded: new Set(), dismissed: new Set() };
  let last = null;
  const rerender = () => last && render(last.state, last.root);

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

  function s(tag, attrs) {
    const el = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attrs || {})) el.setAttribute(key, value);
    return el;
  }

  function fmt(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return Math.round(n / 1e3) + 'k';
    return String(n || 0);
  }

  function ago(iso) {
    if (!iso) return 'never';
    const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes} min ago`;
    if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
    return `${Math.round(minutes / 1440)} d ago`;
  }

  function isWorking(agent) {
    const act = agent.activity;
    return act && act.state === 'working' && Date.now() - new Date(act.at).getTime() < 45 * 60000;
  }

  function color(id, index) {
    if (id === 'claude' || id === 'codex') return getComputedStyle(document.body).getPropertyValue(`--series-${id}`).trim();
    return FALLBACK[index % FALLBACK.length];
  }

  // Cache reads are cheap and dwarf everything else, so the headline counts only new tokens.
  const active = (t) => (t ? t.input + t.cache_write + t.output : 0);

  // ---------- sections ----------

  function header(st, root) {
    if (!st) return h('p', { class: 'muted' }, root ? 'Loading…' : 'Open a project folder.');
    if (!st.initialized) {
      return h('div', null,
        h('p', { class: 'project' }, st.path.split('/').pop()),
        h('p', { class: 'muted' }, 'This folder is not connected yet. Initializing adds AGENTS.md, CLAUDE.md, docs/ and memory hooks. Existing files stay unchanged.'),
        h('button', { class: 'primary', onclick: () => send('init') }, 'Initialize project'));
    }
    return h('p', { class: 'project', title: st.root }, st.name);
  }

  // Effort choices for a model: its own list when the agent reports one, else the agent-wide list.
  function effortsFor(info, model) {
    const option = info.options.find((o) => o.value === model);
    return (option && option.efforts) || info.efforts;
  }

  function select(label, value, options, onchange) {
    return h('select', { 'aria-label': label, title: label, onchange: (e) => onchange(e.target.value) },
      options.map(([v, text, tip]) => h('option', { value: v, title: tip, selected: v === value }, text)));
  }

  function modelPicker(id, models) {
    const info = models && models[id];
    if (!info || info.error) return null;
    const efforts = effortsFor(info, info.model);
    // What "default" means right now, so the choice is not a blind one.
    const effective = info.options.find((o) => o.value === (info.model || info.defaultModel));
    const defaultEffort = (effective && effective.defaultEffort) || info.defaultEffort;
    const choose = (model, effort) => send('model', { agent: id, model, effort });
    return h('div', { class: 'row model' },
      select('Model for new conversations', info.model,
        [['', info.defaultLabel ? `Default (${info.defaultLabel})` : 'Default model'], ...info.options.map((o) => [o.value, o.label, o.description])],
        (model) => choose(model, effortsFor(info, model).includes(info.effort) ? info.effort : '')),
      select('Effort for new conversations', info.effort,
        [['', defaultEffort ? `Default (${defaultEffort})` : 'Default effort'], ...efforts.map((e) => [e, e])],
        (effort) => choose(info.model, effort)));
  }

  // Shown only when shared memory will not work for this agent, with the one-click fix.
  function hookWarning(agent, info, mcp) {
    if (!info || info.state === 'ok') return null;
    const tools = mcp && mcp.agents.includes(agent.id);  // Copilot: memory tools as well as hooks.
    if (info.state === 'missing' && tools) {
      const text = mcp.connected === agent.id ? 'Memory tools are on. Install hooks so it also gets the shared context at the start and its turns are saved by themselves.'
        : 'Memory hooks are not installed, so this agent does not share memory.';
      return h('div', { class: 'warning small' }, h('span', null, text),
        h('button', { onclick: () => send('installHooks', { agent: agent.id }),
          title: 'Hooks in your Copilot settings, for every project (also Copilot in a terminal)' }, 'Install hooks'),
        mcp.connected !== agent.id && h('button', { onclick: () => send('connectMemory', { agent: agent.id }),
          title: 'Only AI Baton\'s memory tools (an MCP server run by this extension); it decides when to call them' }, 'Connect memory'));
    }
    const text = {
      missing: 'Memory hooks are not installed, so this agent does not share memory.',
      untrusted: `${agent.label} has not approved the memory hooks yet, so it does not share memory.`,
      unknown: `Could not check the memory hooks: ${info.detail || 'unknown'}.`,
    }[info.state] || info.detail;
    const fix = info.state === 'missing' ? ['installHooks', 'Install hooks'] : info.state === 'untrusted' ? ['approveHooks', `Approve in ${agent.label}`] : null;
    return h('div', { class: 'warning small' }, h('span', null, text),
      fix && h('button', { onclick: () => send(fix[0], { agent: agent.id }) }, fix[1]));
  }

  // Agents whose chat uses VS Code's MCP servers (Copilot): AI Baton's memory tools, called by the agent. With its
  // hooks too, the tools are optional (searching older checkpoints); hookWarning covers missing hooks.
  function mcpNote(agent, mcp, info) {
    if (!mcp || !mcp.agents.includes(agent.id)) return null;
    if (mcp.connected === agent.id) {
      const text = !mcp.available ? 'Memory tools on, but unavailable until AI Baton works again (see above).'
        : info && info.state === 'ok' ? 'Memory hooks and tools on. The hooks run in Copilot CLI chats, not in Local ones.'
          : 'Memory tools on: it decides when to call them (agent mode).';
      return h('div', { class: 'small muted row' }, h('span', null, text),
        h('button', { class: 'link', onclick: () => send('disconnectMemory', { agent: agent.id }),
          title: 'Stop offering AI Baton\'s MCP server to this agent' }, 'Disconnect'));
    }
    if (agent.hooks) {
      // Hooks only (or not installed yet, which hookWarning covers): the tools stay one quiet click away. Copilot runs
      // hooks only in its Copilot CLI chats (seen live, tests/live); a Local chat gets no memory from them.
      return info && info.state === 'ok' ? h('div', { class: 'small muted row' },
        h('span', null, 'Memory hooks on, in Copilot CLI chats (Local chats get none).'),
        h('button', { class: 'link', onclick: () => send('connectMemory', { agent: agent.id }),
          title: 'Also give it AI Baton\'s memory tools (an MCP server run by this extension), e.g. to search older checkpoints' },
        'Connect memory tools')) : null;
    }
    return h('div', { class: 'warning small' }, h('span', null, 'No memory hooks, so this agent does not share memory yet.'),
      h('button', { onclick: () => send('connectMemory', { agent: agent.id }),
        title: 'Give this agent AI Baton\'s memory tools (an MCP server run by this extension), in every workspace' },
      'Connect memory'));
  }

  // How each agent starts over or shrinks a conversation; others get the general advice.
  const SHRINK = {
    claude: 'save state (checkpoint or handoff), then /clear, or /compact with a focus on what to keep',
    codex: 'save state (checkpoint or handoff), then /new, or /compact',
  };
  const MAX_CONTEXTS = 3;
  // Agents whose earlier messages `baton continue` reads into a fresh conversation.
  const CONTINUABLE = new Set(['claude', 'codex']);

  // Context size of this agent's conversations in the project: the input of each one's last request. Each one is
  // named as in the agent's own chat list, and Open goes to exactly that chat.
  function contexts(agent, state) {
    const scoped = state.projectUsage || state.usage;
    const limit = Number(state.contextWarning) || 0;
    const share = (c) => (c.window ? Math.round(100 * c.tokens / c.window) : null);
    const key = (c) => `${c.agent}:${c.session}`;
    const warns = (c) => !!limit && !c.compacted && share(c) !== null && share(c) >= limit && !view.dismissed.has(key(c));
    // Newest first, but a conversation to warn about never hides behind "+N more".
    const list = ((scoped && scoped.contexts) || []).filter((c) => c.agent === agent.id);
    const all = list.filter(warns).concat(list.filter((c) => !warns(c)));
    const rows = all.slice(0, MAX_CONTEXTS).map((c) => {
      const pct = share(c);
      const meta = [c.model, ago(c.at), c.compactions && `compacted ${c.compactions}×`].filter(Boolean).join(' · ');
      const fill = pct >= 90 ? 'var(--bad)' : warns(c) || (limit && pct >= limit) ? 'var(--warn)' : 'var(--ok)';
      const name = chatName(c.title, c.session);
      return h('div', { class: 'chat', title: [c.title, c.session && `Conversation ${c.session}`, c.cwd].filter(Boolean).join('\n') },
        h('div', { class: 'chat-head' },
          h('span', { class: 'chat-title' }, name),
          agent.sessionUri && c.session && h('button', { class: 'link', onclick: () => send('session', { agent: agent.id, session: c.session }),
            title: `Open this conversation in ${agent.label}`, 'aria-label': `Open conversation: ${name}` }, 'Open'),
          CONTINUABLE.has(agent.id) && c.session && h('button', { class: 'link', onclick: () => send('continue', { agent: agent.id, session: c.session }),
            title: `Start a new ${agent.label} conversation that reads the messages you typed in this one (not tool output)`,
            'aria-label': `Continue fresh from: ${name}` }, 'Continue fresh')),
        c.compacted
          ? h('div', { class: 'small muted' }, 'Context just compacted; its size shows after the next request.')
          : h('div', { class: 'meter', title: 'Input of the last request: what the model re-reads every turn' },
            h('div', { class: 'top' }, h('span', null, `Context ${fmt(c.tokens)}${c.window ? ` of ${fmt(c.window)}` : ''}`), h('span', null, pct === null ? '' : `${pct}%`)),
            pct !== null && h('div', { class: 'track' }, h('div', { class: 'fill', style: { width: Math.min(100, pct) + '%', background: fill } }))),
        h('div', { class: 'small muted' }, meta),
        warns(c) && h('div', { class: 'warning small' },
          h('span', null, `Every turn re-reads all ${fmt(c.tokens)} tokens, which costs tokens and time. ` +
            `At a good stopping point, ${SHRINK[c.agent] || 'save state and start a fresh conversation'}` +
            (CONTINUABLE.has(agent.id) && c.session ? ', or use Continue fresh: a new conversation that reads what you typed here.' : '.')),
          h('button', { class: 'link', onclick: () => { view.dismissed.add(key(c)); rerender(); }, title: 'Hide this warning until the panel reloads' }, 'Dismiss')));
    });
    const more = all.length - MAX_CONTEXTS;
    return more > 0 ? rows.concat(h('div', { class: 'small muted' }, `+${more} more ${more === 1 ? 'conversation' : 'conversations'} in the last 24 h`)) : rows;
  }

  // The chat's title as the agent lists it, else a short id (the full one is in the tooltip).
  function chatName(title, session) {
    return title || (session ? `Chat ${String(session).slice(0, 8)}` : 'Chat');
  }

  function agents(st, models, hooks, mcp, state) {
    if (!st || !st.agents) return null;
    return h('div', null,
      h('h2', null, 'Agents'),
      st.agents.map((a, i) => {
        const working = isWorking(a);
        const cp = a.checkpoint;
        return h('div', { class: 'card' },
          h('div', { class: 'agent-head' },
            h('span', { class: 'dot', style: { background: color(a.id, i) } }),
            h('span', { class: 'name' }, a.label),
            working && h('span', { class: 'badge working' }, 'working'),
            // A review (read-only, saves nothing to the project's memory) by this agent is running now.
            a.reviewing && h('span', { class: 'badge reviewing', title: `Reviewing (read-only), started ${ago(a.reviewing.started)}` +
              ([a.reviewing.model, a.reviewing.effort].filter(Boolean).length ? ` · ${[a.reviewing.model, a.reviewing.effort].filter(Boolean).join(' · ')}` : '') }, 'reviewing'),
            !working && !a.reviewing && st.last_agent === a.id && h('span', { class: 'badge last' }, 'last')),
          st.initialized && h('div', { class: 'small muted' },
            cp ? `Checkpoint ${ago(cp.saved_at)}${cp.branch ? ' · ' + cp.branch : ''}${cp.commit ? ' @ ' + cp.commit.slice(0, 7) : ''}` : 'No checkpoint'),
          cp && cp.summary && h('p', { class: 'summary', title: plain(cp.summary) }, plain(cp.summary)),
          contexts(a, state),
          st.initialized && hookWarning(a, hooks && hooks[a.id], mcp),
          st.initialized && mcpNote(a, mcp, hooks && hooks[a.id]),
          modelPicker(a.id, models),
          h('div', { class: 'row' },
            h('button', { class: 'primary', onclick: () => send('open', { agent: a.id }) }, 'Open'),
            a.newCommand && h('button', { onclick: () => send('new', { agent: a.id }), title: a.hooks ? 'New conversation; project memory loads automatically' : 'New conversation' }, 'New chat'),
            h('button', { class: 'link', onclick: () => send('removeAgent', { agent: a.id }), title: 'Remove from AI Baton; the extension stays installed' }, 'Remove')));
      }),
      !st.agents.length && h('p', { class: 'muted' }, 'No coding agent found. Add one you have installed, or find one in the Marketplace.'),
      models && h('p', { class: 'small muted' }, 'Model and effort apply to new conversations in every project.'),
      h('div', { class: 'row' },
        h('button', { class: st.agents.length ? '' : 'primary', onclick: () => send('addAgent'), title: 'Add an installed agent extension (Copilot, Gemini, Cline, …)' }, 'Add agent'),
        h('button', { onclick: () => send('findAgents'), title: 'Popular coding agents you do not have yet, or a Marketplace search' }, 'Find agents')),
      st.initialized && h('div', { class: 'row' },
        st.agents.some((a) => a.review && a.installed) && h('button', { class: 'primary', onclick: () => send('review'),
          title: 'Another agent critiques the current changes (read-only) and you get its ranked points' }, 'Ask for review'),
        h('button', { onclick: () => send('handoff'), title: 'Copies a request asking the current agent to update docs/AGENT_HANDOFF.md' }, 'Request handoff'),
        h('button', { onclick: () => send('decision') }, 'Add decision')));
  }

  // Resumes the exact conversation when the agent supports it, else just opens the agent.
  function sessionButton(agent, e) {
    return agent.sessionUri && e.session_id
      ? h('button', { class: 'primary', onclick: () => send('session', { agent: agent.id, session: e.session_id }), title: 'Reopen this conversation' }, 'Open session')
      : h('button', { onclick: () => send('open', { agent: agent.id }) }, `Open ${agent.label}`);
  }

  function recent(st, usage) {
    const items = (st && st.recent) || [];
    const titles = (usage && usage.titles) || {};
    if (!items.length) return null;
    const labels = Object.fromEntries((st.agents.concat(st.hidden_agents || [])).map((a) => [a.id, a.label]));
    const index = Object.fromEntries(st.agents.map((a, i) => [a.id, i]));
    const toggle = () => { view.recentOpen = !view.recentOpen; rerender(); };
    return h('div', null,
      h('h2', null, h('button', { class: 'fold', 'aria-expanded': String(view.recentOpen), onclick: toggle },
        `${view.recentOpen ? '▾' : '▸'} Recent work (${st.recent_total || items.length})`)),
      view.recentOpen && h('ul', { class: 'recent' }, items.map((e) => {
        const key = e.agent + e.started;
        const open = view.expanded.has(key);
        const flip = () => { open ? view.expanded.delete(key) : view.expanded.add(key); rerender(); };
        return h('li', null,
          h('button', { class: 'entry', 'aria-expanded': String(open), onclick: flip },
            h('span', { class: 'dot', style: { background: color(e.agent, index[e.agent] || 0) } }),
            h('span', { class: 'who' }, labels[e.agent] || e.agent),
            h('span', { class: 'small muted when' }, ago(e.saved_at)),
            titles[e.session_id] && h('span', { class: 'chat-title', title: titles[e.session_id] }, titles[e.session_id]),
            h('span', { class: open ? 'text' : 'text clamp' }, plain(e.summary) || '(no summary)')),
          open && h('div', { class: 'row detail small muted' },
            `${e.turns} ${e.turns === 1 ? 'reply' : 'replies'}${e.commit ? ' · @ ' + e.commit : ''}${e.handoff_updated ? ' · updated handoff' : ''}`),
          open && h('div', { class: 'row' },
            index[e.agent] !== undefined && sessionButton(st.agents[index[e.agent]], e),
            st.agents.some((a) => a.review && a.installed) && h('button', { onclick: () => send('review', { entry: e }),
              title: 'Another agent reviews the current changes, with this conversation\'s summary as context; the review can be sent back here' }, 'Ask for review'),
            h('button', { onclick: () => send('copy', { text: e.summary }), title: 'Copy this summary, e.g. to ask another agent for a review' }, 'Copy summary')));
      })),
      view.recentOpen && h('div', { class: 'row more' },
        h('button', { onclick: () => send('recent'), title: 'Every session with full summaries, search and agent filter, in an editor tab' },
          st.recent_total > items.length ? `Show all ${st.recent_total}…` : 'Open in editor…')));
  }

  function docs(st) {
    if (!st || !st.initialized) return null;
    return h('div', null,
      h('h2', null, 'Project knowledge'),
      h('ul', { class: 'docs' }, DOCS.map(([key, label]) => {
        const doc = st.docs[key];
        return h('li', null,
          h('a', { onclick: () => send('doc', { key }), title: doc.path }, label),
          h('span', { class: 'small muted' }, doc.updated ? ago(doc.updated) : 'missing'));
      })));
  }

  function usage(state) {
    const scoped = state.scope === 'project' && state.projectUsage ? state.projectUsage : state.usage;
    if (!scoped) return h('div', null, h('h2', null, 'Usage'), h('p', { class: 'muted small' }, state.loading ? 'Calculating usage… (the first run can take a few seconds)' : 'No usage data.'));
    const ids = Object.keys(scoped.agents);
    const known = state.status ? [...(state.status.agents || []), ...(state.status.hidden_agents || [])] : [];
    const labels = Object.fromEntries(known.map((a) => [a.id, a.label]));  // Hidden agents keep their name in usage.
    const label = (id) => labels[id] || id;
    return h('div', null,
      h('h2', null, 'Usage'),
      state.projectUsage && h('div', { class: 'tabs', role: 'group' },
        h('button', { 'aria-pressed': String(state.scope === 'project'), onclick: () => send('scope', { scope: 'project' }) }, 'This project'),
        h('button', { 'aria-pressed': String(state.scope !== 'project'), onclick: () => send('scope', { scope: 'all' }) }, 'All')),
      h('div', { class: 'tiles' }, ids.map((id, i) => {
        const a = scoped.agents[id];
        return h('div', { class: 'tile' },
          h('div', { class: 'label' }, h('span', { class: 'dot', style: { background: color(id, i) } }), label(id)),
          h('div', { class: 'value', title: 'New tokens today: input + cache writes + output' }, fmt(active(a.today))),
          h('div', { class: 'sub' }, `today · ${fmt(active(a.week))} in 7 days`));
      })),
      chart(scoped, ids, label),
      h('p', { class: 'small muted' }, `New tokens per day, last ${scoped.days} days. Cache reads are shown in the tooltip.`),
      limits(state.usage, label, state.status && state.status.agents));
  }

  function chart(data, ids, label) {
    const days = [];
    const today = new Date();
    for (let i = data.days - 1; i >= 0; i--) {
      const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
      days.push(d.toLocaleDateString('sv-SE'));
    }
    const byDay = ids.map((id) => Object.fromEntries(data.agents[id].by_day.map((r) => [r.day, r])));
    const max = Math.max(1, ...days.map((d) => Math.max(...byDay.map((m) => active(m[d])))));
    const W = 280, H = 110, left = 30, bottom = 16, plotH = H - bottom - 4;
    const step = (W - left) / days.length;
    const barW = Math.max(2, Math.min(10, (step - 3) / ids.length));
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Daily token usage chart' });
    const y = (v) => 4 + plotH - (v / max) * plotH;
    for (const v of [0, max / 2, max]) {
      svg.append(s('line', { class: 'grid', x1: left, x2: W, y1: y(v), y2: y(v) }));
      const t = s('text', { class: 'axis', x: left - 4, y: y(v) + 3, 'text-anchor': 'end' });
      t.textContent = fmt(v);
      svg.append(t);
    }
    days.forEach((day, di) => {
      const x0 = left + di * step + (step - barW * ids.length) / 2;
      ids.forEach((id, ai) => {
        const v = active(byDay[ai][day]);
        if (!v) return;
        const hgt = Math.max(1.5, (v / max) * plotH);
        svg.append(s('rect', { class: 'bar', x: x0 + ai * barW, y: 4 + plotH - hgt, width: barW, height: hgt, rx: Math.min(2, barW / 2), fill: color(id, ai) }));
      });
      const every = Math.ceil(days.length / 7);  // The last day always gets a label, so skip a regular one too close to it.
      if (di === days.length - 1 || (di % every === 0 && days.length - 1 - di >= every)) {
        const t = s('text', { class: 'axis', x: left + di * step + step / 2, y: H - 4, 'text-anchor': 'middle' });
        t.textContent = day.slice(8) + '.' + day.slice(5, 7);
        svg.append(t);
      }
      const hit = s('rect', { class: 'hit', x: left + di * step, y: 0, width: step, height: H - bottom });
      hit.addEventListener('mousemove', (e) => showTip(e, day, ids.map((id, ai) => [label(id), byDay[ai][day]])));
      hit.addEventListener('mouseleave', hideTip);
      svg.append(hit);
    });
    return h('div', { class: 'chart' },
      h('div', { class: 'legend' }, ids.map((id, i) => h('span', null, h('span', { class: 'dot', style: { background: color(id, i) } }), label(id)))),
      svg);
  }

  function showTip(event, day, rows) {
    tip.replaceChildren(h('div', null, h('strong', null, new Date(day).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' }))),
      rows.map(([name, t]) => h('div', null, `${name}: ${fmt(active(t))}`, t && t.cache_read ? h('span', { class: 'muted' }, ` (+${fmt(t.cache_read)} from cache)`) : '')));
    tip.style.display = 'block';
    const x = Math.min(event.clientX + 12, window.innerWidth - tip.offsetWidth - 4);
    tip.style.left = Math.max(4, x) + 'px';
    tip.style.top = event.clientY + 14 + 'px';
  }

  function hideTip() {
    tip.style.display = 'none';
  }

  function limits(all, label, agentList) {
    const rows = [];
    const liveView = Object.fromEntries((agentList || []).filter((a) => a.usageView).map((a) => [a.id, a]));
    const live = new Set();
    for (const [id, byLimit] of Object.entries((all && all.limits) || {})) {
      const info = byLimit && (byLimit[id] || Object.values(byLimit)[0]);
      if (!info) continue;
      const stale = !info.at || Date.now() - new Date(info.at).getTime() > STALE_MINUTES * 60000;
      if (stale && liveView[id]) live.add(id);
      for (const [key, name] of [['primary', '5-hour limit'], ['secondary', 'weekly limit']]) {
        if (info[key]) rows.push([`${label(id)}: ${name}`, info[key], info.at, stale]);
      }
    }
    const plan = all && all.limits && all.limits.codex && Object.values(all.limits.codex)[0];
    return h('div', null,
      h('h2', null, 'Plan limits'),
      rows.map(([name, w, at, stale]) => {
        const pct = w.expired ? 0 : Math.round(w.used_percent);
        const fill = stale ? 'var(--muted)' : pct >= 90 ? 'var(--bad)' : pct >= 70 ? 'var(--warn)' : 'var(--ok)';
        const reset = w.resets_at && new Date(w.resets_at * 1000);
        return h('div', { class: 'meter' + (stale ? ' stale' : ''), title: stale ? 'Old reading: the real value may differ' : undefined },
          h('div', { class: 'top' }, h('span', null, name), h('strong', null, stale ? `~${pct}%` : `${pct}%`)),
          h('div', { class: 'track' }, h('div', { class: 'fill', style: { width: pct + '%', background: fill } })),
          h('div', { class: 'small muted' }, (w.expired
            ? 'Window has already reset'
            : reset  // Claude saves no reset time for a window that has not started yet.
              ? `Resets ${reset.toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`
              : 'No reset time yet') +
            (at ? ` · ${stale ? 'stale, ' : ''}read ${ago(at)}` : '')));
      }),
      live.size > 0 && h('div', { class: 'row' }, [...live].map((id) =>
        h('button', { onclick: () => send('liveUsage', { agent: id }), title: `Opens ${label(id)}'s own usage view, which is always current` }, `Live in ${label(id)}`))),
      !rows.length && h('p', { class: 'small muted' }, 'No limit data.'),
      h('p', { class: 'small muted' }, 'Percentages are the last reading saved by the agent extensions; they refresh while an agent is working.' +
        (plan && plan.plan_type ? ` Codex plan: ${plan.plan_type}.` : '')));
  }

  function render(state, root) {
    hideTip();
    app.replaceChildren(...[
      section(() => header(state.status, root)),
      state.error && h('p', { class: 'error' }, state.error),
      section(() => agents(state.status, state.models, state.hooks, state.mcp, state)),
      section(() => recent(state.status, state.projectUsage || state.usage)),
      section(() => docs(state.status)),
      section(() => usage(state)),
    ].filter(Boolean));
  }

  // One section with unexpected data must not freeze the whole panel: a throw would stop every later render.
  function section(build) {
    try {
      return build();
    } catch (error) {
      console.error(error);
      return h('p', { class: 'error' }, `Could not show this section: ${error.message}`);
    }
  }

  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'state') {
      last = event.data;
      render(last.state, last.root);
    }
  });
  send('ready');
})();
