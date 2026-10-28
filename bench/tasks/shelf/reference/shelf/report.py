def by_location(items):
    """Text report: items grouped by location (unplaced last), sorted by name, with totals."""
    groups = {}
    for item in items:
        groups.setdefault(item.location or '(no location)', []).append(item)
    order = sorted(k for k in groups if k != '(no location)') + (['(no location)'] if '(no location)' in groups else [])
    lines = []
    for location in order:
        group = sorted(groups[location], key=lambda i: i.name.lower())
        lines.append(f'{location} ({sum(i.quantity for i in group)})')
        lines.extend(f'  {i.name} x{i.quantity}' for i in group)
    return '\n'.join(lines)


def by_tag(items):
    groups = {}
    for item in items:
        for tag in item.tags or ['(untagged)']:
            groups.setdefault(tag, []).append(item)
    order = sorted(k for k in groups if k != '(untagged)') + (['(untagged)'] if '(untagged)' in groups else [])
    lines = []
    for tag in order:
        group = sorted(groups[tag], key=lambda i: i.name.lower())
        lines.append(f'{tag} ({sum(i.quantity for i in group)})')
        lines.extend(f'  {i.name} x{i.quantity}' for i in group)
    return '\n'.join(lines)
