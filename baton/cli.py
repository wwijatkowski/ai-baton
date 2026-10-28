"""Command line entry point: `baton hook|init|status|usage|...`."""
import argparse
import json
import sys

from . import hook, hookcheck, init_project, mcp, metrics, models, project, recall, review, status, usage


def fmt(n):
    return f'{n / 1e6:.1f}M' if n >= 1e6 else f'{n / 1e3:.0f}k' if n >= 1e3 else str(n)


def print_usage(report):
    print(f'Usage: last {report["days"]} days' + (f', project {report["project"]}' if report['project'] else ''))
    for agent, data in report['agents'].items():
        print(f'\n{agent.upper()}')
        for label, key in (('today', 'today'), ('7 days', 'week'), (f'{report["days"]} days', 'period')):
            t = data[key]
            print(f'  {label:>8}: input {fmt(t["input"] + t["cache_write"]):>7}  output {fmt(t["output"]):>7}'
                  f'  cached {fmt(t["cache_read"]):>7}')
        for row in data['by_project'][:5]:
            print(f'    {fmt(row["input"] + row["cache_write"] + row["output"]):>7}  {row["name"]}')
    for limit_id, limits in report['limits']['codex'].items():
        for window, label in (('primary', '5 h'), ('secondary', 'week')):
            info = limits.get(window)
            if info:
                state = 'reset' if info.get('expired') else f'{info["used_percent"]:.0f}%'
                print(f'\nLimit {limit_id} ({label}): {state}')


def print_metrics(result):
    print(f'{result["conversations"]} conversations ({result["reviews_left_out"]} review and {result["bench_left_out"]} '
          'benchmark runs left out). Descriptive only: '
          'the groups differ in project and task, so this is not a measured saving (see docs/knowledge/SAVINGS_PLAN.md).\n')
    print(f'{"agent":8}{"group":28}{"n":>5}{"unknown":>9}{"edited":>8}{"tokens":>12}{"calls<edit":>12}{"tokens<edit":>13}'
          f'{"injected":>10}')
    for g in result['groups']:
        cell = lambda v: '-' if v is None else f'{v:,}'
        print(f'{g["agent"]:8}{g["group"]:28}{g["conversations"]:>5}{g["usage_unknown"]:>9}{g["with_edit_attempt"]:>8}'
              f'{cell(g["median_tokens"]):>12}'
              f'{cell(g["median_tool_calls_before_first_edit"]):>12}{cell(g["median_tokens_before_first_edit"]):>13}'
              f'{cell(g["median_injected_chars"]):>10}')
    print('\nMedians. unknown: conversations whose transcript held no usage (left out of the token medians); tokens: '
          'uncached input + cache writes + output (cache reads left out); calls<edit, tokens<edit: before the first '
          'attempted file change (the handoff and AI Baton memory left out); injected: characters of AI Baton context.')


def reviewer_name(result):
    """codex, or codex (gpt-5.5, high) when the review ran with its own model or effort."""
    choice = ', '.join(v for v in (result.get('model'), result.get('effort')) if v)
    return result['agent'] + (f' ({choice})' if choice else '')


def main(argv=None):
    # Agents and the extension talk UTF-8 JSON; Windows would otherwise use its ANSI code page for the pipes.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(prog='baton', description='AI Baton')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('hook', help='lifecycle hook (called by agents)')
    p.add_argument('agent')
    p.add_argument('--global', dest='user_level', action='store_true', help='installed in user settings, not the project')
    p = sub.add_parser('install-hooks', help='install memory hooks once for all projects (user settings)')
    p.add_argument('--agents', help='comma-separated agent ids (default: all agents with hooks; Copilot only when named)')
    p = sub.add_parser('uninstall-hooks', help='remove the memory hooks from user settings (and optionally a project)')
    p.add_argument('--agents', help='comma-separated agent ids (default: all)')
    p.add_argument('--project', help='also remove project hooks from this folder')
    p = sub.add_parser('hook-status', help='whether memory hooks are installed and approved')
    p.add_argument('path', nargs='?', default='.')
    p.add_argument('--user', action='store_true', help='only check the user-level (global) hooks')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('init', help='set up a project')
    p.add_argument('path', nargs='?', default='.')
    p.add_argument('--replace-legacy', action='store_true', help='replace legacy agent-memory.py hooks')
    p.add_argument('--agents', help='comma-separated agent ids to install hooks for (default: all shown agents)')
    p = sub.add_parser('status', help='agent state in a project')
    p.add_argument('path', nargs='?', default='.')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('recent', help='every agent session in a project, newest first')
    p.add_argument('path', nargs='?', default='.')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('recall', help='search past checkpoints of all agents')
    p.add_argument('words', nargs='*')
    p.add_argument('--agent')
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--full', action='store_true', help='print whole replies instead of snippets')
    p.add_argument('--path', default='.')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('models', help='model and effort each agent starts with')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('set-model', help='choose the model and effort for new conversations')
    p.add_argument('agent')
    p.add_argument('--model', help='model id, or "default"')
    p.add_argument('--effort', help='effort level, or "default"')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('add-agent', help='add an agent, or show a hidden built-in one again')
    p.add_argument('agent', help='built-in id, or JSON object: id, label, extension, openCommand, newCommand')
    p = sub.add_parser('remove-agent', help='remove an added agent or hide a built-in one')
    p.add_argument('id')
    p = sub.add_parser('review', help='second opinion from any agent, optionally another model or effort, on recent work: changes (git or not) or replies (read-only)')
    p.add_argument('goal', nargs='?', help='what the change is meant to do')
    p.add_argument('--agent', required=True, help='reviewer, e.g. codex or claude')
    p.add_argument('--commit', help='review this commit instead of the uncommitted changes')
    p.add_argument('--base', help='review the commits of this branch since it left BASE (e.g. main), as a pull request')
    p.add_argument('--focus', help='what the reviewer should pay special attention to')
    p.add_argument('--session', help='session whose work this is (its summary tells the reviewer the goal)')
    p.add_argument('--model', help='reviewer model for this review only (default: as configured for the agent)')
    p.add_argument('--effort', help='reviewer effort for this review only, e.g. low or high')
    p.add_argument('--path', default='.')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('mcp', help='MCP server (stdio) with AI Baton memory for agents without hooks')
    p.add_argument('--agent', required=True, help='the agent this server serves, e.g. copilot or gemini')
    p.add_argument('--project', help='serve only this project (default: the project path each tool call names)')
    p = sub.add_parser('metrics', help='one summary per conversation (counts only, kept on this machine), and a descriptive report')
    p.add_argument('action', choices=('collect', 'report'))
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('usage', help='token usage and limits')
    p.add_argument('--days', type=int, default=30)
    p.add_argument('--project')
    p.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    if args.command == 'hook':
        try:
            print(json.dumps(hook.run(args.agent, json.load(sys.stdin), args.user_level), ensure_ascii=False))
        except Exception as error:
            # Never block the agent, and never echo payloads (they may hold secrets).
            print('baton hook: ' + type(error).__name__, file=sys.stderr)
            print('{}')
    elif args.command == 'install-hooks':
        only = None if args.agents is None else {a.strip() for a in args.agents.split(',') if a.strip()}
        try:
            log = init_project.install_user_hooks(only)
        except init_project.InitError as error:
            sys.exit(f'Error: {error}')
        print('\n'.join(log))
        print('\nDone.' + (' Codex: approve the hooks once (the hooks button next to the model picker, "Review hooks", then '
                            'Allow all; in the terminal: /hooks).' if any('.codex' in line for line in log) else ''))
    elif args.command == 'uninstall-hooks':
        only = None if args.agents is None else {a.strip() for a in args.agents.split(',') if a.strip()}
        try:
            log = init_project.uninstall_hooks(only, args.project)
        except init_project.InitError as error:
            sys.exit(f'Error: {error}')
        print('\n'.join(log) or 'No AI Baton hooks found.')
    elif args.command == 'hook-status':
        result = hookcheck.user_status() if args.user else hookcheck.status(args.path)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            for agent, info in result.items():
                print(f'{agent:<8} {info["state"]:<10} {info.get("detail", "")}')
    elif args.command == 'init':
        try:
            only = None if args.agents is None else {a.strip() for a in args.agents.split(',') if a.strip()}
            log = init_project.init(args.path, args.replace_legacy, only)
        except init_project.InitError as error:
            sys.exit(f'Error: {error}')
        print('\n'.join(log))
        print('\nDone. Restart agent sessions in this folder.' +
              (' Codex: approve the 3 hooks once (the hooks button next to the model picker (Review hooks), then Allow all).' if any('.codex' in line for line in log) else ''))
    elif args.command == 'status':
        result = status.project_status(args.path)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif not result['initialized']:
            print('Project is not initialized. Run: baton init')
        else:
            print(result['name'], result['root'])
            for agent in result['agents']:
                cp = agent['checkpoint'] or {}
                act = agent['activity'] or {}
                print(f'  {agent["label"]:<8} {act.get("state", "-"):<8} last checkpoint: {cp.get("saved_at", "none")}')
    elif args.command == 'recent':
        try:
            result = status.project_recent(args.path)
        except LookupError as error:
            sys.exit(str(error))
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        for entry in [] if args.json else result['sessions']:
            print(f'{(entry["saved_at"] or "")[:16].replace("T", " ")}  {entry["agent"]:<8} {entry["turns"]:>3} replies  '
                  + ' '.join(entry['summary'].split())[:90])
    elif args.command == 'recall':
        try:
            hits = recall.search(args.path, args.words, args.agent, args.limit)
        except LookupError as error:
            sys.exit(str(error))
        if args.json:
            print(json.dumps(hits, ensure_ascii=False))
        else:
            print('\n\n'.join(recall.render(s, args.words, args.full) for s in hits) or 'No matching checkpoints.')
    elif args.command in ('models', 'set-model'):
        try:
            result = models.report() if args.command == 'models' else \
                {args.agent: models.set_model(args.agent, args.model, args.effort)}
        except models.ModelError as error:
            sys.exit(f'Error: {error}')
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            for agent, info in result.items():
                print(f'{agent:<8} model: {info.get("model") or "default":<22} effort: {info.get("effort") or "default"}'
                      if 'error' not in info else f'{agent:<8} {info["error"]}')
    elif args.command in ('add-agent', 'remove-agent'):
        try:
            if args.command == 'add-agent':
                agent = json.loads(args.agent) if args.agent.lstrip().startswith('{') else {'id': args.agent}
                print(json.dumps(project.add_agent(agent), ensure_ascii=False))
            else:
                project.remove_agent(args.id)
        except (project.AgentError, ValueError, AttributeError) as error:
            sys.exit(f'Error: {error}')
    elif args.command == 'review':
        try:
            result = review.review(args.path, args.agent, args.goal, args.commit, args.focus, args.session,
                                   args.model, args.effort, args.base)
        except review.ReviewError as error:
            sys.exit(f'Error: {error}')
        print(json.dumps(result, ensure_ascii=False) if args.json
              else f'Review by {reviewer_name(result)} of {result["reviewed"]}:\n\n{result["review"]}')
    elif args.command == 'mcp':
        try:
            mcp.serve(args.agent, args.project)
        except ValueError as error:
            sys.exit(f'Error: {error}')
        except KeyboardInterrupt:
            pass
    elif args.command == 'metrics':
        if args.action == 'collect':
            result = metrics.collect()
            print(json.dumps(result) if args.json else
                  f'{result["updated"]} conversations summarized; {result["conversations"]} kept in {metrics.STORE}' +
                  (f'; {result["errors"]} could not be read' if result['errors'] else ''))
        else:
            result = metrics.report()
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print_metrics(result)
    elif args.command == 'usage':
        report = usage.summarize(args.days, args.project)
        print(json.dumps(report, ensure_ascii=False) if args.json else '', end='')
        if not args.json:
            print_usage(report)
