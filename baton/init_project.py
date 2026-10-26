"""`baton init`: set a project up for shared agent memory. Idempotent, never overwrites content."""
import re
from datetime import date
from pathlib import Path

from . import changes
from .project import (HOME, MARKER, MEMORY_DIR, agent_binary, baton_command, load_agents, memory_dir, read_json,
                      write_json)

TEMPLATES = HOME / 'baton' / 'templates'
BLOCK_RE = re.compile(r'<!-- BEGIN AI-BATON -->.*?<!-- END AI-BATON -->', re.S)
EVENTS = ('SessionStart', 'UserPromptSubmit', 'Stop')
LEGACY = 'agent-memory.py'
HOOK_FILES = {'claude': '.claude/settings.json', 'codex': '.codex/hooks.json'}


class InitError(Exception):
    pass


def template(filename, **values):
    text = (TEMPLATES / filename).read_text(encoding='utf-8')
    for key, value in values.items():
        text = text.replace('{' + key + '}', value)
    return text


def ensure_file(path, content, log):
    if path.exists():
        log.append(f'= {path.name} already exists (unchanged)')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    log.append(f'+ {path}')


def ensure_agents_md(root, block, log):
    path = root / 'AGENTS.md'
    if not path.exists():
        return ensure_file(path, template('AGENTS.md', name=root.name, block=block), log)
    text = path.read_text(encoding='utf-8')
    new = BLOCK_RE.sub(lambda _: block.strip(), text) if BLOCK_RE.search(text) else text.rstrip() + '\n\n' + block
    if new != text:
        path.write_text(new, encoding='utf-8')
        log.append('~ AGENTS.md: added/refreshed the AI Baton section')


def ensure_claude_md(root, log):
    path = root / 'CLAUDE.md'
    if not path.exists():
        return ensure_file(path, template('CLAUDE.md', name=root.name), log)
    text = path.read_text(encoding='utf-8')
    if '@AGENTS.md' not in text:
        path.write_text(text.rstrip() + '\n\nShared project rules:\n@AGENTS.md\n@docs/AGENT_HANDOFF.md\n', encoding='utf-8')
        log.append('~ CLAUDE.md: added @AGENTS.md import')


def check_hook_file(path, replace_legacy):
    config = read_json(path) if path.exists() else {}
    if not isinstance(config, dict):
        raise InitError(f'{path} is not valid JSON; fix it by hand.')
    groups = config.get('hooks', {}).values()
    if any(LEGACY in h.get('command', '') for gs in groups for g in gs for h in g.get('hooks', [])) \
            and not replace_legacy:
        raise InitError(f'{path} has legacy {LEGACY} hooks. Run with --replace-legacy to replace them.')
    return config


def hook_command(agent, user_level=False):
    return f'{baton_command()} hook {agent}' + (' --global' if user_level else '')


# Our hook commands: `<python> "<...>/bin/baton" hook <agent>` with an optional `--global`, the script path quoted with
# "..." or '...'. Only these (and the legacy agent-memory.py script) are ever replaced or removed.
BATON_HOOK_RE = re.compile(r"""/bin/baton["']?\s+hook\s+[\w-]+(\s+--global)?\s*$""")


def is_baton_hook(command, agent=None):
    if LEGACY in command:
        return agent is None
    match = BATON_HOOK_RE.search(command)
    return bool(match) and (agent is None or re.search(rf'\shook\s+{re.escape(agent)}(\s|$)', command) is not None)


def merge_hooks(root, agent, replace_legacy, log, user_level=False):
    """Replace AI Baton's hooks in `root`'s hook file for `agent`; user_level means `root` is the home folder."""
    path = root / HOOK_FILES[agent]
    config = check_hook_file(path, replace_legacy)
    hooks = config.setdefault('hooks', {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get('hooks', [])
                    if not is_baton_hook(h.get('command', ''))]
            if kept:
                groups.append({**group, 'hooks': kept})
        hooks[event] = groups
    for event in EVENTS:
        hooks.setdefault(event, []).append(
            {'hooks': [{'type': 'command', 'command': hook_command(agent, user_level), 'timeout': 10}]})
    write_json(path, config)
    log.append(f'~ {"~/" if user_level else ""}{HOOK_FILES[agent]}: memory hooks {", ".join(EVENTS)}')


def baton_events(base, agent):
    """Events that have an AI Baton hook in `base`'s hook file for `agent`."""
    config = read_json(base / HOOK_FILES[agent], {}) if (base / HOOK_FILES[agent]).exists() else {}
    hooks = (config.get('hooks') or {}) if isinstance(config, dict) else {}
    return {event for event, groups in hooks.items()
            if any(is_baton_hook(h.get('command', '')) for g in groups for h in g.get('hooks', []))}


def has_baton_hooks(base, agent):
    """All of SessionStart, UserPromptSubmit and Stop are hooked; a partial set does not count."""
    return set(EVENTS) <= baton_events(base, agent)


def user_home():
    return Path.home()


def hook_config(path):
    """A hook file's content after checking its shape ({"hooks": {event: [{"hooks": [{...}]}]}}); None if absent."""
    if not path.exists():
        return None
    config = read_json(path)
    hooks = config.get('hooks', {}) if isinstance(config, dict) else None
    ok = isinstance(hooks, dict) and all(
        isinstance(groups, list) and all(
            isinstance(group, dict) and isinstance(group.get('hooks', []), list)
            and all(isinstance(h, dict) for h in group.get('hooks', [])) for group in groups)
        for groups in hooks.values())
    if not ok:
        raise InitError(f'{path} does not have the expected hooks layout; fix it by hand, nothing was changed.')
    return config


def remove_hooks(base, agent, log, label):
    """Take AI Baton's hooks out of `base`'s hook file for `agent`, keeping every other hook and setting."""
    path = base / HOOK_FILES[agent]
    config = hook_config(path)
    if config is None:
        return
    hooks = config.get('hooks') or {}
    removed = 0
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get('hooks', []) if not is_baton_hook(h.get('command', ''))]
            removed += len(group.get('hooks', [])) - len(kept)
            if kept:
                groups.append({**group, 'hooks': kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not removed:
        return
    if hooks:
        config['hooks'] = hooks
    else:
        config.pop('hooks', None)
    write_json(path, config)
    log.append(f'- {label}{HOOK_FILES[agent]}: removed {removed} AI Baton hook(s)')


def uninstall_hooks(only=None, project=None):
    """Remove AI Baton's hooks from user settings (and from `project`, if given). Other hooks and settings stay."""
    log = []
    kinds = {a['hooks'] for a in load_agents() + load_agents(hidden=True)
             if a.get('hooks') in HOOK_FILES and (only is None or a['id'] in only)}
    targets = [(user_home(), kind, '~/') for kind in sorted(kinds)]
    if project:
        targets += [(Path(project).expanduser().resolve(), kind, '') for kind in sorted(kinds)]
    for base, kind, _ in targets:  # Check every file first: a bad one stops the run before anything changes.
        hook_config(base / HOOK_FILES[kind])
    for base, kind, label in targets:
        remove_hooks(base, kind, log, label)
    return log


def install_user_hooks(only=None):
    """Install the hooks once for every project (they do nothing outside initialized projects)."""
    log = []
    for agent in [a for a in load_agents() if a.get('hooks') in HOOK_FILES and (only is None or a['id'] in only)
                  and (only is not None or agent_binary(a['hooks']))]:
        merge_hooks(user_home(), agent['hooks'], False, log, user_level=True)
    return log


def ensure_gitignore(root, log):
    path = root / '.gitignore'
    lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    if not any(l.strip().rstrip('/') == MEMORY_DIR for l in lines):
        path.write_text('\n'.join(lines + [f'{MEMORY_DIR}/']).lstrip('\n') + '\n', encoding='utf-8')
        log.append(f'~ .gitignore: {MEMORY_DIR}/')


def init(root, replace_legacy=False, only=None):
    """Set up `root`. `only` limits memory hooks to these agent ids (the ones the user actually has)."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise InitError(f'Folder {root} does not exist.')
    log, today = [], date.today().isoformat()
    agents = [a for a in load_agents(root) if a.get('hooks') in HOOK_FILES and (only is None or a['id'] in only)]
    # Unless agents are named, only those whose program is on this computer get hooks: no `.codex/` for Claude-only users.
    if only is None:
        for agent in [a for a in agents if not agent_binary(a['hooks'])]:
            log.append(f'= {agent["id"]}: not found on this computer, so no memory hooks (install it, then run init again)')
        agents = [a for a in agents if agent_binary(a['hooks'])]
    # Agents with user-level hooks need nothing in the project (and the repo stays free of local paths).
    agents = [a for a in agents if not has_baton_hooks(user_home(), a['hooks'])]

    # Validate every hook file before touching anything.
    for agent in agents:
        check_hook_file(root / HOOK_FILES[agent['hooks']], replace_legacy)

    marker = root / MARKER
    if not marker.exists():
        write_json(marker, {'name': root.name, 'created': today, 'extraAgents': []})
        log.append(f'+ {marker}')
    block = (TEMPLATES / 'agents_block.md').read_text(encoding='utf-8')
    ensure_agents_md(root, block, log)
    ensure_claude_md(root, log)
    ensure_file(root / 'docs' / 'AGENT_HANDOFF.md', template('AGENT_HANDOFF.md', date=today), log)
    ensure_file(root / 'docs' / 'STATUS.md', template('STATUS.md'), log)
    ensure_file(root / 'docs' / 'knowledge' / 'DECISIONS.md', template('DECISIONS.md', date=today), log)
    for agent in agents:
        merge_hooks(root, agent['hooks'], replace_legacy, log)
    ensure_gitignore(root, log)
    # No repository: a first snapshot now, so the first conversation's changes can be reviewed (review.py).
    if changes.baseline(root, memory_dir(root)):
        log.append(f'+ {MEMORY_DIR}/{changes.SHADOW_DIR}: first snapshot of the files (no git repository)')
    return log
