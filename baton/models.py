"""Model and effort per agent, kept in each agent's own config so its extension uses them for new conversations.

Claude -> ~/.claude/settings.json (`model`, `effortLevel`)
Codex  -> ~/.codex/config.toml (top-level `model`, `model_reasoning_effort`)
An empty value means "the agent's default" and removes the key.
"""
import json
import re
from pathlib import Path

from .project import file_lock, load_agents, read_json, write_json, write_text

CLAUDE_SETTINGS = Path.home() / '.claude' / 'settings.json'
CLAUDE_STATE = Path.home() / '.claude.json'
CLAUDE_PROJECTS = Path.home() / '.claude' / 'projects'
# Session ids of `baton review` runs by Claude: their transcripts stay (usage counts their tokens) but are not the
# user's own conversations, so they never set the last used model.
REVIEW_SESSIONS = Path.home() / '.cache' / 'ai-baton' / 'review-sessions.json'
MAX_REVIEW_SESSIONS = 200
CLAUDE_MODELS = [('opus', 'Opus'), ('sonnet', 'Sonnet'), ('haiku', 'Haiku')]
CLAUDE_EFFORTS = ['low', 'medium', 'high', 'xhigh']
CODEX_CONFIG = Path.home() / '.codex' / 'config.toml'
CODEX_MODELS = Path.home() / '.codex' / 'models_cache.json'
EFFORT_ORDER = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra']
VALUE_RE = re.compile(r'^[\w.:\[\]-]{0,80}$')
TABLE_RE = re.compile(r'^\s*\[')


class ModelError(Exception):
    pass


def with_current(options, current):
    # A model set by hand elsewhere still shows up as selected.
    if current and current not in {o['value'] for o in options}:
        options.append({'value': current, 'label': current})
    return options


def model_name(model_id):
    """claude-opus-5-5 -> Opus 5.5"""
    match = re.match(r'claude-([a-z]+)-(\d+)(?:-(\d))?(?:\b|-)', model_id or '')
    return f'{match[1].title()} {match[2]}' + (f'.{match[3]}' if match[3] else '') if match else model_id


def claude_last_model():
    """Model of the latest Claude reply on this machine; Claude's default depends on the plan and is not stored."""
    reviews = set(review_sessions())
    try:
        logs = sorted((p for p in CLAUDE_PROJECTS.glob('*/*.jsonl') if p.stem not in reviews),
                      key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    except OSError:
        return ''
    for log in logs:
        with open(log, 'rb') as stream:
            stream.seek(max(0, log.stat().st_size - 256 * 1024))
            lines = stream.read().decode('utf-8', 'replace').splitlines()
        for line in reversed(lines):
            match = re.search(r'"model":"(claude-[^"]+)"', line)
            if match:
                return model_name(match[1])
    return ''


def review_sessions():
    found = read_json(REVIEW_SESSIONS, []) if REVIEW_SESSIONS.exists() else []
    return [s for s in found if isinstance(s, str)] if isinstance(found, list) else []


def add_review_session(session_id):
    # Locked: two reviews starting together would otherwise drop one id.
    REVIEW_SESSIONS.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(REVIEW_SESSIONS.with_name(REVIEW_SESSIONS.name + '.lock')):
        write_json(REVIEW_SESSIONS, (review_sessions() + [session_id])[-MAX_REVIEW_SESSIONS:], private=True)


def load_claude_settings():
    if not CLAUDE_SETTINGS.exists():
        return {}
    settings = read_json(CLAUDE_SETTINGS)
    if not isinstance(settings, dict):
        raise ModelError(f'{CLAUDE_SETTINGS} is not valid JSON; fix it by hand.')
    return settings


def claude():
    settings = load_claude_settings()
    extra = (read_json(CLAUDE_STATE, {}) or {}).get('additionalModelOptionsCache') or []
    options = [{'value': value, 'label': label} for value, label in CLAUDE_MODELS]
    options += [{'value': o['value'], 'label': o.get('label') or o['value'], 'description': o.get('description')}
                for o in extra if isinstance(o, dict) and o.get('value')]
    model = settings.get('model', '')
    last = claude_last_model()
    return {'model': model, 'effort': settings.get('effortLevel', ''), 'efforts': CLAUDE_EFFORTS,
            'options': with_current(options, model),
            'defaultLabel': f'last used: {last}' if last else 'set by your plan', 'defaultEffort': ''}


def set_claude(model, effort):
    settings = load_claude_settings()
    for key, value in (('model', model), ('effortLevel', effort)):
        if value:
            settings[key] = value
        else:
            settings.pop(key, None)
    write_json(CLAUDE_SETTINGS, settings)


def toml_top_level(text):
    """Simple `key = "value"` pairs before the first [table]; enough for the keys we own."""
    values = {}
    for line in text.splitlines():
        if TABLE_RE.match(line):
            break
        match = re.match(r'^\s*([\w-]+)\s*=\s*"([^"]*)"', line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def toml_set_top_level(text, key, value):
    lines = text.splitlines()
    end = next((i for i, line in enumerate(lines) if TABLE_RE.match(line)), len(lines))
    at = next((i for i in range(end) if re.match(rf'^\s*{re.escape(key)}\s*=', lines[i])), None)
    new = f'{key} = {json.dumps(value)}' if value else None
    if at is not None and new:
        lines[at] = new
    elif at is not None:
        del lines[at]
    elif new:
        lines.insert(0, new)
    return '\n'.join(lines) + '\n'


def codex():
    top = toml_top_level(CODEX_CONFIG.read_text(encoding='utf-8') if CODEX_CONFIG.exists() else '')
    listed = [m for m in (read_json(CODEX_MODELS, {}) or {}).get('models', [])
              if isinstance(m, dict) and m.get('slug') and m.get('visibility') == 'list']
    options = [{'value': m['slug'], 'label': m.get('display_name') or m['slug'], 'description': m.get('description'),
                'efforts': [r.get('effort') for r in m.get('supported_reasoning_levels') or [] if r.get('effort')],
                'defaultEffort': m.get('default_reasoning_level') or ''}
               for m in sorted(listed, key=lambda m: m.get('priority', 99))]
    seen = {e for o in options for e in o['efforts']}
    model = top.get('model', '')
    # Codex starts with its highest-priority listed model.
    first = options[0] if options else None
    return {'model': model, 'effort': top.get('model_reasoning_effort', ''),
            'efforts': [e for e in EFFORT_ORDER if e in seen] or EFFORT_ORDER[1:4],
            'options': with_current(options, model),
            'defaultLabel': first['label'] if first else '', 'defaultModel': first['value'] if first else '',
            'defaultEffort': first['defaultEffort'] if first else ''}


def set_codex(model, effort):
    text = CODEX_CONFIG.read_text(encoding='utf-8') if CODEX_CONFIG.exists() else ''
    text = toml_set_top_level(text, 'model', model)
    text = toml_set_top_level(text, 'model_reasoning_effort', effort)
    try:
        import tomllib
        tomllib.loads(text)
    except ImportError:
        pass  # Python < 3.11: the edit only touches lines we wrote ourselves.
    except ValueError as error:
        raise ModelError(f'{CODEX_CONFIG} would become invalid TOML ({error}); left unchanged.')
    write_text(CODEX_CONFIG, text)


PROVIDERS = {'claude': (claude, set_claude), 'codex': (codex, set_codex)}


def report(root=None):
    result = {}
    for agent in load_agents(root):
        provider = PROVIDERS.get(agent.get('models'))
        if provider:
            try:
                result[agent['id']] = provider[0]()
            except (ModelError, OSError) as error:
                result[agent['id']] = {'error': str(error)}
    return result


def set_model(agent_id, model=None, effort=None, root=None):
    """Change model and/or effort; None keeps the current value, '' or 'default' resets it."""
    agent = next((a for a in load_agents(root) if a['id'] == agent_id), None)
    provider = agent and PROVIDERS.get(agent.get('models'))
    if not provider:
        raise ModelError(f'{agent_id} has no model settings AI Baton can change.')
    current = provider[0]()
    model = current['model'] if model is None else ('' if model == 'default' else model)
    effort = current['effort'] if effort is None else ('' if effort == 'default' else effort)
    for value in (model, effort):
        if not VALUE_RE.match(value):
            raise ModelError(f'Invalid value: {value!r}')
    if effort and effort not in current['efforts']:
        raise ModelError(f'{agent_id} does not support effort {effort!r}.')
    provider[1](model, effort)
    return provider[0]()
