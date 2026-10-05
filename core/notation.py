"""Mathematical notation for the existing expression language (no code execution)."""
import ast

GREEK = {name: '\\' + name for name in (
    'alpha beta gamma delta epsilon theta lambda mu nu xi pi rho sigma tau phi chi psi omega '
    'Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega').split()}
# 'lambda' is a Python keyword; use 'lam' as its declared identifier.
GREEK['lam'] = r'\lambda'


def symbol(name):
    if name in GREEK:
        return GREEK[name]
    if len(name) == 1:
        return name
    return r'\mathrm{' + name.replace('_', r'\_') + '}'


def grouped(part, minimum=100):
    """Parenthesize only when the parent operation would change the grouping."""
    return rf'\left({part.latex}\right)' if part.precedence < minimum else part.latex


def atom_math(name, parts, keywords):
    """Use precedence and compiled shapes, rather than wrapping every argument."""
    a = parts[0].latex
    shape = parts[0].value.shape
    if name == 'quad_form':
        return rf'{grouped(parts[0], 41)}^{{\top}} {grouped(parts[1], 20)} {grouped(parts[0], 20)}'
    if name == 'transpose':
        return rf'{grouped(parts[0], 41)}^{{\top}}'
    if name == 'square':
        return grouped(parts[0], 41) + '^{' + ('2' if not shape else r'\circ 2') + '}'
    if name == 'sum_squares':
        p = 'F' if len(shape) == 2 else '2'
        return rf'\left\|{a}\right\|_{{{p}}}^2' if shape else grouped(parts[0], 41) + '^2'
    if name in ('sum', 'max'):
        if not shape:
            return a
        if 'axis' in keywords:
            direction = 'rows' if keywords['axis'] == 0 else 'columns'
            return rf'\{name}_{{\mathrm{{{direction}}}}}{grouped(parts[0])}'
        index = 'i,j' if len(shape) == 2 else 'i'
        return rf'\{name}_{{{index}}}{grouped(parts[0])}_{{{index}}}'
    if name == 'abs':
        return rf'\left|{a}\right|'
    if name == 'pos':
        return rf'\max\left\{{{a},0\right\}}'
    if name == 'maximum':
        return rf'\max\left\{{{a},{parts[1].latex}\right\}}'
    if name in {'hstack', 'vstack'}:
        separator = ' & ' if name == 'hstack' else r'\\'
        return r'\begin{bmatrix}' + separator.join(p.latex for p in parts) + r'\end{bmatrix}'
    raise ValueError(f'No mathematical renderer for {name}')


def expression_source(source, spec, limits=None):
    """Render editable symbolic LaTeX without freezing scalar parameter values."""
    from core.parser import Parser, Limits, build_problem
    seed = {**spec, 'objective': {'sense': 'minimize', 'expression': '0'}, 'constraints': []}
    seed.pop('criteria', None)
    limits = limits or Limits()
    built = build_problem(seed, limits)
    parser = Parser(built.names, {}, limits)
    node = parser.tree(source)
    if isinstance(node, ast.Compare):
        a = parser.expression(node.left)
        b = parser.expression(node.comparators[0])
        relation = {ast.LtE: r'\le', ast.GtE: r'\ge', ast.Eq: '='}.get(type(node.ops[0]))
        if len(node.ops) != 1 or relation is None:
            from core.parser import ProblemError
            raise ProblemError('Use one <=, >=, or == per constraint.')
        return f'{a.latex} {relation} {b.latex}'
    return parser.expression(node).latex
