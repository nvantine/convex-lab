"""A documented LaTeX subset lowered to our whitelisted expression AST.

LaTeX typesetting itself is not a mathematical parser. This deliberately small
recursive-descent parser gives sums, norms, indices, fractions and matrix
products definite solver semantics. It never evaluates Python or runs TeX.
"""
import ast
import re
from dataclasses import dataclass

from core.notation import GREEK


class LatexError(ValueError):
    pass


@dataclass
class Term:
    node: ast.expr
    shape: tuple = ()
    row: bool = False
    indexed: bool = False

    def __post_init__(self):
        self.node.latex_shape = self.shape


def transpose_factor(node, vector):
    """Recognize c*xᵀ as well as xᵀ without treating vector coefficients as scalars."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'transpose' and ast.dump(node.args[0]) == ast.dump(vector):
        return ast.Constant(1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        for scalar, rest in ((node.left, node.right), (node.right, node.left)):
            if getattr(scalar, 'latex_shape', None) == ():
                factor = transpose_factor(rest, vector)
                if factor is not None:
                    return scalar if isinstance(factor, ast.Constant) and factor.value == 1 else ast.BinOp(scalar, ast.Mult(), factor)
    return None


def call(name, *args, **kwargs):
    return ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=list(args),
                    keywords=[ast.keyword(arg=k, value=ast.Constant(v)) for k, v in kwargs.items()])


TOKEN = re.compile(r'\\[A-Za-z]+|\\\\|\\[{}_|,;!]|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?|[A-Za-z][A-Za-z0-9]*|<=|>=|==|[{}()[\]^_+*/=<>|,;&:-]')


class LatexParser:
    def __init__(self, source, names):
        if not isinstance(source, str) or not source.strip() or len(source) > 20000:
            raise LatexError('Enter a nonempty LaTeX expression (at most 20,000 characters).')
        source = source.strip()
        if source.startswith('$$') and source.endswith('$$'):
            source = source[2:-2]
        elif source.startswith('$') and source.endswith('$'):
            source = source[1:-1]
        source = source.replace(r'\left', '').replace(r'\right', '').replace(r'\,', ' ').replace(r'\;', ' ').replace(r'\!', ' ')
        source = source.replace(r'\lVert', r'\|').replace(r'\rVert', r'\|').replace(r'\{', '{').replace(r'\}', '}')
        self.tokens = []
        position = 0
        while position < len(source):
            if source[position].isspace():
                position += 1
                continue
            match = TOKEN.match(source, position)
            if not match:
                raise LatexError(f'Unsupported LaTeX near {source[position:position+20]!r}. See the notation reference.')
            self.tokens.append(match.group())
            position = match.end()
        if len(self.tokens) > 1000:
            raise LatexError('LaTeX expression exceeds the token budget.')
        self.position = 0
        self.stops = set()
        self.names = names
        self.indices = set()
        self.depth = 0

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else ''

    def take(self, expected=None):
        token = self.peek()
        if not token or (expected is not None and token != expected):
            raise LatexError(f'Expected {expected or "an expression"}; found {token or "end of input"}.')
        self.position += 1
        return token

    def parse(self):
        left = self.expression()
        relations = {'=': ast.Eq, '==': ast.Eq, '<=': ast.LtE, '>=': ast.GtE,
                     r'\le': ast.LtE, r'\leq': ast.LtE, r'\ge': ast.GtE, r'\geq': ast.GtE}
        if self.peek() in relations:
            op = relations[self.take()]()
            right = self.expression()
            node = ast.Compare(left=left.node, ops=[op], comparators=[right.node])
        else:
            node = left.node
        if self.peek():
            raise LatexError(f'Unsupported or ambiguous token {self.peek()!r}. Use one relation per constraint.')
        return ast.fix_missing_locations(node)

    def expression(self):
        left = self.product()
        while self.peek() in ('+', '-'):
            op = ast.Add() if self.take() == '+' else ast.Sub()
            right = self.product()
            left = Term(ast.BinOp(left.node, op, right.node), left.shape or right.shape)
        return left

    def starts_atom(self):
        token = self.peek()
        return bool(token) and (token in ('(', '{', '[', r'\frac', r'\|', '|', r'\sum', r'\max', r'\begin',
                                         r'\mathrm', r'\mathbf', r'\boldsymbol') or
                                token in GREEK.values() or re.fullmatch(r'[A-Za-z][A-Za-z0-9]*|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+', token))

    def product(self):
        left = self.power()
        while self.peek() not in self.stops and (self.peek() in ('*', '/', r'\cdot', r'\times', r'\odot') or self.starts_atom()):
            explicit = self.take() if self.peek() in ('*', '/', r'\cdot', r'\times', r'\odot') else ''
            right = self.power()
            if explicit == '/':
                op, shape, row = ast.Div(), left.shape or right.shape, left.row
            elif left.indexed or right.indexed or explicit == r'\odot':
                op, shape, row = ast.Mult(), left.shape or right.shape, left.row
            elif left.shape and right.shape:
                if len(left.shape) == 1 and not left.row:
                    raise LatexError('Vector products need a transpose: use x^\\top y, or \\odot for elementwise multiplication.')
                op = ast.MatMult()
                if len(left.shape) == len(right.shape) == 1:
                    shape, row = (), False
                elif len(left.shape) == 2 and len(right.shape) == 2:
                    shape, row = (left.shape[0], right.shape[1]), False
                elif len(left.shape) == 2:
                    shape, row = (left.shape[0],), False
                else:
                    shape, row = (right.shape[1],), True
            else:
                op, shape, row = ast.Mult(), left.shape or right.shape, left.row or right.row
            node = ast.BinOp(left.node, op, right.node)
            # Quadratic forms require the recognized atom for CVXPY's DCP rules.
            if isinstance(op, ast.MatMult) and isinstance(left.node, ast.BinOp) and isinstance(left.node.op, ast.MatMult):
                first = left.node.left
                factor = transpose_factor(first, right.node)
                if factor is not None:
                    quadratic = call('quad_form', right.node, left.node.right)
                    node = quadratic if isinstance(factor, ast.Constant) and factor.value == 1 else ast.BinOp(factor, ast.Mult(), quadratic)
            left = Term(node, shape, row, left.indexed or right.indexed)
        return left

    def power(self):
        value = self.atom()
        while self.peek() in ('^', '_'):
            operation = self.take()
            braced = self.peek() == '{'
            if braced:
                self.take('{')
            if operation == '^' and self.peek() in (r'\top', r'\mathsf', 'T'):
                if self.take() == r'\mathsf':
                    self.take('{'); self.take('T'); self.take('}')
                value = Term(call('transpose', value.node), value.shape[::-1] if len(value.shape) == 2 else value.shape, not value.row)
            elif operation == '^':
                sign = -1 if self.peek() == '-' and self.take() else 1
                exponent = self.take()
                if exponent == r'\circ':
                    exponent = self.take()
                if not exponent.isdigit():
                    raise LatexError('Use a transpose or a literal square. General powers are not supported.')
                power = int(exponent) * sign
                if power == 2:
                    # Squared Euclidean/Frobenius norms share the direct QP atom.
                    node = value.node
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'norm'
                            and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)
                            and (node.args[1].value == 'fro' or (node.args[1].value == 2 and len(getattr(node.args[0], 'latex_shape', ())) <= 1))):
                        value = Term(call('sum_squares', node.args[0]))
                    else:
                        value = Term(call('square', node), value.shape, value.row, value.indexed)
                elif isinstance(value.node, ast.Constant) and abs(power) <= 100:
                    try:
                        value = Term(ast.Constant(value.node.value ** power))
                    except (OverflowError, ZeroDivisionError):
                        raise LatexError('Invalid constant power.') from None
                else:
                    raise LatexError('Decision expressions support squares; other powers are limited to numeric constants.')
            else:
                tokens = []
                while self.peek() and self.peek() not in ('}', ')', '+', '*', '/', '=', r'\le', r'\ge'):
                    if self.peek() not in (':', ',', '-') and not self.peek().isdigit() and self.peek() not in self.indices:
                        break
                    tokens.append(self.take())
                    if not braced:
                        break
                indices = ''.join(tokens).split(',')
                if all(index in self.indices for index in indices):
                    value.indexed = True
                elif indices and all(re.fullmatch(r'-?\d+|(?:-?\d*)?:(?:-?\d*)?(?::(?:-?\d*)?)?', index) for index in indices):
                    if len(indices) > len(value.shape):
                        raise LatexError('Too many indices for the declared shape.')
                    index_nodes, shape = [], []
                    for dimension, text in zip(value.shape, indices):
                        def integer(text):
                            number = int(text)
                            return ast.Constant(number) if number >= 0 else ast.UnaryOp(ast.USub(), ast.Constant(-number))
                        if ':' in text:
                            bounds = text.split(':')
                            if len(bounds) > 3:
                                raise LatexError('A slice uses start:stop:step.')
                            bounds += [''] * (3-len(bounds))
                            numbers = [int(b) if b else None for b in bounds]
                            try:
                                shape.append(len(range(*slice(*numbers).indices(dimension))))
                            except ValueError as error:
                                raise LatexError(str(error)) from error
                            index_nodes.append(ast.Slice(*[integer(b) if b else None for b in bounds]))
                        else:
                            index_nodes.append(integer(text))
                    shape += list(value.shape[len(indices):])
                    index = index_nodes[0] if len(indices) == 1 else ast.Tuple(elts=index_nodes, ctx=ast.Load())
                    value = Term(ast.Subscript(value.node, index, ctx=ast.Load()), tuple(shape))
                else:
                    raise LatexError('Use zero-based integer indices, literal slices, or dummy indices within a sum/max.')
            if braced:
                self.take('}')
        return value

    def group(self, opening='{'):
        self.take(opening)
        result = self.expression()
        self.take({ '{': '}', '(': ')', '[': ']' }[opening])
        return result

    def name(self, token):
        reverse = {command: name for name, command in GREEK.items() if name != 'lambda'}
        name = reverse.get(token, token)
        # Exact identifiers win over treating an underscore as vector indexing.
        if self.peek() == '_' and self.position+1 < len(self.tokens):
            combined = name + '_' + self.tokens[self.position+1]
            if combined in self.names:
                self.take('_'); self.take(); name = combined
        if name not in self.names:
            raise LatexError(f"Unknown symbol '{name}'. Declare it as a variable or parameter; \\lambda uses the name lam.")
        return Term(ast.Name(id=name, ctx=ast.Load()), tuple(self.names[name]))

    def atom(self):
        self.depth += 1
        if self.depth > 50:
            raise LatexError('LaTeX nesting is too deep.')
        try:
            return self._atom()
        finally:
            self.depth -= 1

    def _atom(self):
        token = self.peek()
        if token in ('+', '-'):
            self.take()
            a = self.power()
            return Term(ast.UnaryOp(ast.USub() if token == '-' else ast.UAdd(), a.node), a.shape, a.row, a.indexed)
        if token in ('(', '{', '['):
            return self.group(token)
        if token == r'\frac':
            self.take()
            a, b = self.group(), self.group()
            return Term(ast.BinOp(a.node, ast.Div(), b.node), a.shape or b.shape)
        if token in (r'\|', '|'):
            self.take()
            old_stops = self.stops
            self.stops = old_stops | {token}
            value = self.expression()
            self.stops = old_stops
            self.take(token)
            if token == '|':
                return Term(call('abs', value.node), value.shape)
            order = 2
            if self.peek() == '_':
                self.take('_')
                brace = self.peek() == '{'
                if brace: self.take('{')
                literal = self.take()
                order = {r'\infty': 'inf', 'F': 'fro', '1': 1, '2': 2}.get(literal)
                if order is None: raise LatexError('Norm order must be 1, 2, F, or \\infty.')
                if brace: self.take('}')
            return Term(call('norm', value.node, ast.Constant(order)))
        if token in (r'\mathrm', r'\mathbf', r'\boldsymbol'):
            self.take(); self.take('{')
            pieces = []
            while self.peek() and self.peek() != '}':
                pieces.append(self.take().replace(r'\_', '_'))
            self.take('}')
            name = ''.join(pieces)
            if name in GREEK.values():
                return self.name(name)
            return self.name(name)
        if token in (r'\sum', r'\max'):
            command = self.take()
            indices, axis = set(), None
            if self.peek() == '_':
                self.take('_')
                braced = self.peek() == '{'
                if braced: self.take('{')
                if self.peek() == r'\mathrm':
                    self.take(); self.take('{'); direction = self.take(); self.take('}')
                    axis = {'rows': 0, 'columns': 1}.get(direction)
                    if axis is None: raise LatexError('Use rows or columns for an axis reduction.')
                else:
                    indices.add(self.take())
                    while self.peek() == ',': self.take(','); indices.add(self.take())
                if braced: self.take('}')
                if self.peek() == '^':
                    raise LatexError('Bounded sums are not yet supported. Use a full sum with dummy indices or an indexed expression in Expression input.')
            old = self.indices
            self.indices = old | indices
            if command == r'\max' and self.peek() == '{' and not indices and axis is None:
                self.take('{'); a = self.expression()
                if self.peek() == ',':
                    self.take(','); b = self.expression(); self.take('}')
                    self.indices = old
                    return Term(call('maximum', a.node, b.node), a.shape or b.shape)
                self.take('}'); value = a
            else:
                value = self.power()
            self.indices = old
            keyword = {} if axis is None else {'axis': axis}
            shape = () if axis is None else value.shape[:axis] + value.shape[axis+1:]
            return Term(call('sum' if command == r'\sum' else 'max', value.node, **keyword), shape)
        if token == r'\begin':
            self.take(); self.take('{'); self.take('bmatrix'); self.take('}')
            rows = []
            while True:
                row = [self.expression()]
                while self.peek() == '&': self.take('&'); row.append(self.expression())
                rows.append(row)
                if self.peek() != r'\\': break
                self.take()
            self.take(r'\end'); self.take('{'); self.take('bmatrix'); self.take('}')
            nodes = [call('hstack', ast.List(elts=[p.node for p in row], ctx=ast.Load())) for row in rows]
            if len(rows) == 1:
                return Term(nodes[0], (sum(p.shape[-1] if p.shape else 1 for p in rows[0]),))
            return Term(call('vstack', ast.List(elts=nodes, ctx=ast.Load())), (len(rows), len(rows[0])))
        token = self.take()
        if re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', token):
            return Term(ast.Constant(float(token)))
        if token in GREEK.values() or re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', token):
            return self.name(token)
        raise LatexError(f'Unsupported LaTeX command/token {token!r}. See the notation reference.')


def to_expression(source, names):
    try:
        return ast.unparse(LatexParser(source, names).parse())
    except (RecursionError, MemoryError):
        raise LatexError('LaTeX expression is too deeply nested.') from None


def expand_latex_calls(node, names):
    """Allow latex(r'...') inside whitelisted expression calls; literal text only."""
    class Expand(ast.NodeTransformer):
        def visit_Call(self, current):
            if isinstance(current.func, ast.Name) and current.func.id == 'latex':
                if len(current.args) != 1 or current.keywords or not isinstance(current.args[0], ast.Constant) or not isinstance(current.args[0].value, str):
                    raise LatexError('latex(...) accepts one literal string, for example latex(r"w^\\top \\Sigma w").')
                result = LatexParser(current.args[0].value, names).parse()
                if isinstance(result, ast.Compare):
                    raise LatexError('Use a whole constraint in LaTeX input, not a relation inside a function call.')
                return result
            return self.generic_visit(current)
    return ast.fix_missing_locations(Expand().visit(node))
