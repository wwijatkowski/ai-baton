"""`baton install-mcp` / `uninstall-mcp`: add AI Baton's MCP server (`baton mcp`) to an agent's own MCP settings.

For agents without memory hooks. Each agent keeps MCP servers in its own file and format; only our entry
("ai-baton") is ever written or removed, everything else in the file stays.

copilot -> VS Code's user mcp.json ({"servers": {...}}, type stdio), used by Copilot Chat in every workspace
"""
import json
import os
import sys
from pathlib import Path

from .project import hook_argv, load_agents, read_json, valid_agent_id, write_json

SERVER_NAME = 'ai-baton'


class McpInstallError(Exception):
    pass


def vscode_user_dir():
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming') / 'Code' / 'User'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Code' / 'User'
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'Code' / 'User'


# Agent extension -> where its MCP servers live and under which key.
TARGETS = {
    'github.copilot-chat': {'label': 'Copilot', 'file': lambda: vscode_user_dir() / 'mcp.json', 'key': 'servers'},
}
DEFAULT_EXTENSIONS = {'copilot': 'github.copilot-chat'}  # For `--agent copilot` before it is added to the panel.


def target(agent_id, root=None):
    """The agent's MCP settings (file, key) by its extension, or None when AI Baton cannot set it up."""
    agent = next((a for a in load_agents(root) if a['id'] == agent_id), None)
    extension = ((agent or {}).get('extension') or DEFAULT_EXTENSIONS.get(agent_id) or '').lower()
    found = TARGETS.get(extension)
    return found and {**found, 'path': found['file']()}


def server_entry(agent_id):
    """`<python> <launcher> mcp --agent <id>`, without a shell (absolute paths: clients start it from anywhere)."""
    python, script = hook_argv()
    return {'type': 'stdio', 'command': python, 'args': [script, 'mcp', '--agent', agent_id]}


def is_ours(entry):
    args = entry.get('args') if isinstance(entry, dict) else None
    return isinstance(args, list) and len(args) >= 2 and str(args[1]) == 'mcp' and \
        str(args[0]).replace('\\', '/').endswith('bin/baton')


def load(path, key):
    """The settings file and its servers map; an unreadable file is never overwritten (VS Code allows comments)."""
    if not path.exists() or not path.read_text(encoding='utf-8').strip():
        return {}, {}
    config = read_json(path)
    if not isinstance(config, dict) or not isinstance(config.get(key, {}), dict):
        raise McpInstallError(f'{path} is not plain JSON with a "{key}" object (comments or another layout); '
                              f'add the server by hand: {SERVER_NAME}')
    return config, config.get(key, {})


def state(agent_id, root=None):
    """'installed', 'available' (AI Baton can set it up) or None (not for this agent)."""
    found = target(agent_id, root)
    if not found:
        return None
    try:
        _, servers = load(found['path'], found['key'])
    except (McpInstallError, OSError):
        return 'available'
    entry = servers.get(SERVER_NAME)
    return 'installed' if is_ours(entry) and entry['args'][2:] == ['--agent', agent_id] else 'available'


def install(agent_id, root=None):
    if not valid_agent_id(agent_id):
        raise McpInstallError(f'invalid agent id {agent_id!r}')
    found = target(agent_id, root)
    if not found:
        supported = ', '.join(sorted(DEFAULT_EXTENSIONS))
        raise McpInstallError(f'AI Baton cannot set up MCP for {agent_id} yet (supported: {supported}). Add this to '
                              f'its MCP settings by hand: {json.dumps(server_entry(agent_id))}')
    config, servers = load(found['path'], found['key'])
    if SERVER_NAME in servers and not is_ours(servers[SERVER_NAME]):
        raise McpInstallError(f'{found["path"]} already has a server named {SERVER_NAME} that AI Baton did not write.')
    servers[SERVER_NAME] = server_entry(agent_id)
    config[found['key']] = servers
    write_json(found['path'], config)
    return [f'~ {found["path"]}: MCP server {SERVER_NAME} for {agent_id}']


def uninstall(agent_ids=None, root=None):
    """Remove our server from the MCP settings of these agents (default: every agent AI Baton can set up)."""
    log, paths = [], {}
    ids = agent_ids or [a['id'] for a in load_agents(root)] + list(DEFAULT_EXTENSIONS)
    for agent_id in ids:
        found = target(agent_id, root)
        if found:
            paths[found['path']] = found['key']
    for path, key in paths.items():
        config, servers = load(path, key)
        if is_ours(servers.get(SERVER_NAME)):
            del servers[SERVER_NAME]
            write_json(path, config)
            log.append(f'- {path}: removed MCP server {SERVER_NAME}')
    return log
