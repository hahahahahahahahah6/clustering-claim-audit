"""Offline documentation and Python syntax audit."""
import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

from . import __version__
from .phrases import CLUSTERING, NOCLUSTERING


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def matches(text, phrases):
    pattern = r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=lambda p: (-len(p), p))) + r')\b'
    return list(re.finditer(pattern, text))


def claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            lines.append('')
        elif marker:
            fence = marker[1]
            lines.append('')
        else:
            lines.append(line)
    positive, negative = [], []
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        text = normalize(paragraph)
        spans = matches(text, NOCLUSTERING)
        negative.extend(m.group() for m in spans)
        for m in reversed(spans):
            text = text[:m.start()] + ' ' * (m.end()-m.start()) + text[m.end():]
        positive.extend(m.group() for m in matches(text, CLUSTERING))
    return positive, negative


TARGETS = {'sklearn.cluster.' + name for name in (
    'KMeans', 'MiniBatchKMeans', 'DBSCAN', 'OPTICS', 'AgglomerativeClustering',
    'Birch', 'SpectralClustering', 'AffinityPropagation', 'MeanShift')}
TARGETS.update(('sklearn.mixture.GaussianMixture', 'scipy.cluster.hierarchy.linkage',
                'scipy.cluster.hierarchy.fcluster', 'hdbscan.HDBSCAN'))


def evidence(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    aliases = {}
    shadows = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            for item in node.names:
                aliases[item.asname or item.name] = (node.module or '') + '.' + item.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadows.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadows.add(node.id)
        elif isinstance(node, ast.arg):
            shadows.add(node.arg)
    def resolve(node):
        if isinstance(node, ast.Name):
            return '' if node.id in shadows else aliases.get(node.id, '')
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        return ''
    return any(isinstance(node, ast.Call) and resolve(node.func) in TARGETS for node in ast.walk(tree))


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OSError('root must be a readable directory')
    positives, negatives, production, tests = [], [], [], []
    def ignored(relative):
        return any(relative == p.strip('/') or relative.startswith(p.strip('/') + '/') for p in ignore)
    def error(exc):
        raise exc
    for directory, dirs, files in os.walk(root, onerror=error, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink() and not ignored((Path(directory)/d).relative_to(root).as_posix()))
        for filename in sorted(files):
            path = Path(directory)/filename
            rel = path.relative_to(root)
            if path.is_symlink() or ignored(rel.as_posix()):
                continue
            if (rel.as_posix() == 'README.md' or ('docs' in rel.parts[:-1] and path.suffix == '.md')):
                yes, no = claims(path.read_text(encoding='utf-8'))
                positives.extend({'path': rel.as_posix(), 'phrase': p} for p in yes)
                negatives.extend({'path': rel.as_posix(), 'phrase': p} for p in no)
            if path.suffix != '.py' or set(rel.parts[:-1]) & {'fixtures', 'docs', 'examples'}:
                continue
            if evidence(path.read_text(encoding='utf-8')):
                is_test = 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
                (tests if is_test else production).append(rel.as_posix())
    findings = []
    if positives and not production:
        findings.append({'rule': 'documented-clustering-claim-false', 'severity': 'MEDIUM' if tests else 'HIGH', 'claims': positives, 'message': 'documented grouping claim has no production evidence'})
    if negatives and production:
        findings.append({'rule': 'documented-no-clustering-claim-false', 'severity': 'HIGH', 'claims': negatives, 'message': 'documented absence claim is contradicted by production evidence'})
    verdict = 'FAIL' if findings else 'PASS'
    return {'status': verdict, 'verdict': verdict, 'findings': findings,
            'evidence': {'production': production, 'tests': tests}}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH'], default='HIGH')
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['status'])
        for finding in result['findings']:
            print(finding['severity'] + ' ' + finding['rule'])
        if args.verbose:
            print(json.dumps(result['evidence'], sort_keys=True))
    levels = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(levels[f['severity']] >= levels[args.fail_on] for f in result['findings']) else 0
