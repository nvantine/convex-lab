"""Build CVXPY and LaTeX together from a small expression language.

No Python evaluation occurs. Each accepted AST node is interpreted explicitly.
DCP composition rules: Boyd & Vandenberghe §§3.2, 4.2; CVXPY DCP tutorial.
"""
import ast
import math
import keyword
import re
from dataclasses import dataclass

import cvxpy as cp
import numpy as np
from core.notation import atom_math, symbol


class ProblemError(ValueError):
    """An actionable specification, syntax, shape, or domain error."""


@dataclass(frozen=True)
class Limits:
    variable_entries: int = 5000
    parameter_entries: int = 100000
    ast_nodes: int = 500
    ast_depth: int = 50
    constraints: int = 100
    criteria: int = 8


@dataclass
class Expression:
    value: cp.Expression
    latex: str
    row: bool = False


@dataclass
class BuiltProblem:
    problem: cp.Problem
    variables: dict
    declarations: list
    objective: dict
    constraints: list
    diagnostics: list
    criteria: list
    names: dict

    def preview(self):
        return {"is_dcp": self.problem.is_dcp() and all(c["is_dcp"] for c in self.criteria), "objective": self.objective,
                "criteria": [{k: v for k, v in c.items() if k != "value"} for c in self.criteria],
                "constraints": [{k: v for k, v in c.items() if k != "value"} for c in self.constraints],
                "declarations": self.declarations, "diagnostics": self.diagnostics}


ATOMS = {"sum": cp.sum, "sum_squares": cp.sum_squares, "square": cp.square,
         "quad_form": cp.quad_form, "norm": cp.norm, "abs": cp.abs,
         "pos": cp.pos, "max": cp.max, "maximum": cp.maximum,
         "hstack": cp.hstack, "vstack": cp.vstack, "transpose": cp.transpose}
DOMAINS = {"free", "nonneg", "nonpos", "symmetric", "PSD"}


def number(value):
    """Round-trip scalar values; scientific notation needs a real LaTeX exponent."""
    value = float(value)
    rendered = repr(value)
    if "e" in rendered:
        mantissa, exponent = rendered.split("e")
        return mantissa + r"\times 10^{" + str(int(exponent)) + "}"
    return str(int(value)) if value.is_integer() else rendered


def numeric(value):
    try:
        # Reject strings, booleans, ragged lists, and implicit numeric coercions.
        raw = np.asarray(value)
        if raw.dtype.kind not in "iuf" or raw.ndim > 2:
            raise ValueError
        array = raw.astype(float)
        if not np.isfinite(array).all() or array.size == 0:
            raise ValueError
        return array
    except (TypeError, ValueError):
        raise ProblemError("Values must be finite real numbers, vectors, or rectangular matrices.") from None


def shape_of(raw):
    if not isinstance(raw, list) or len(raw) > 2 or any(type(n) is not int or n <= 0 for n in raw):
        raise ProblemError("Shape must be [], [n], or [rows, columns], with positive integer dimensions.")
    return tuple(raw)


class Parser:
    def __init__(self, names, substitutions, limits):
        self.names = names
        self.substitutions = substitutions
        self.limits = limits
        self.nodes_used = 0
        self.diagnostics = []

    def tree(self, source):
        if not isinstance(source, str) or not source.strip() or len(source) > 20000:
            raise ProblemError("Enter a nonempty expression of at most 20,000 characters.")
        try:
            node = ast.parse(source, mode="eval").body
        except (SyntaxError, RecursionError, MemoryError):
            raise ProblemError("Bad syntax. Use expressions such as quad_form(w, Sigma).") from None
        from core.latex_input import LatexError, expand_latex_calls
        try:
            node = expand_latex_calls(node, {name: value.shape for name, value in self.names.items()})
        except (LatexError, RecursionError) as error:
            raise ProblemError(str(error)) from None
        self.nodes_used += sum(1 for _ in ast.walk(node))
        if self.nodes_used > self.limits.ast_nodes:
            raise ProblemError("Expression workload exceeds LAB_MAX_AST_NODES; simplify or ask the owner to raise it.")
        return node

    def expression(self, node, depth=0):
        if depth > self.limits.ast_depth:
            raise ProblemError("Expression nesting is too deep.")
        try:
            result = self._expression(node, depth)
            if result.value.size > self.limits.parameter_entries:
                raise ProblemError("An intermediate expression exceeds the configured size limit.")
            if not result.value.is_dcp():
                self.diagnostics.append({"expression": ast.unparse(node), "curvature": result.value.curvature,
                                         "sign": result.value.sign, "latex": result.latex,
                                         "rule": "DCP composition failed: check curvature and argument signs. Products of decision variables are not DCP; use square(x) for x squared."})
            return result
        except ProblemError:
            raise
        except (ValueError, TypeError, IndexError, ZeroDivisionError, cp.error.DCPError) as error:
            raise ProblemError(f"{ast.unparse(node)}: {error}") from None

    def _expression(self, node, depth):
        child = lambda n: self.expression(n, depth + 1)
        if isinstance(node, ast.Name):
            if node.id not in self.names:
                raise ProblemError(f"Unknown name '{node.id}'. Declare it as a variable or parameter.")
            return Expression(self.names[node.id], self.substitutions.get(node.id, symbol(node.id)))
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            array = numeric(node.value)
            return Expression(cp.Constant(array), number(array))
        if isinstance(node, (ast.List, ast.Tuple)):
            # Literal arrays contain only numbers; expression lists belong to stacking calls.
            try:
                array = numeric(ast.literal_eval(node))
            except (ValueError, SyntaxError):
                raise ProblemError("Array literals contain numbers only. Use hstack([...]) for expressions.") from None
            latex = r"\begin{bmatrix}" + r"\\".join(
                " & ".join(number(x) for x in row) for row in np.atleast_2d(array)) + r"\end{bmatrix}"
            return Expression(cp.Constant(array), latex)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            a = child(node.operand)
            return Expression(-a.value if isinstance(node.op, ast.USub) else a.value,
                              ("-" if isinstance(node.op, ast.USub) else "+") + r"\left(" + a.latex + r"\right)", a.row)
        if isinstance(node, ast.BinOp):
            a, b = child(node.left), child(node.right)
            if isinstance(node.op, ast.Add):
                value, latex = a.value + b.value, f"{a.latex} + {b.latex}"
            elif isinstance(node.op, ast.Sub):
                value, latex = a.value - b.value, f"{a.latex} - \\left({b.latex}\\right)"
            elif isinstance(node.op, ast.Mult):
                value = cp.multiply(a.value, b.value)
                operator = r"\odot" if a.value.shape and b.value.shape else r"\cdot"
                latex = rf"\left({a.latex}\right) {operator} \left({b.latex}\right)"
            elif isinstance(node.op, ast.MatMult):
                value = a.value @ b.value
                left = a.latex
                if a.value.ndim == 1 and b.value.ndim >= 1 and not a.row:
                    left = rf"\left({left}\right)^{{\top}}"
                latex = rf"\left({left}\right) \left({b.latex}\right)"
            elif isinstance(node.op, ast.Div):
                if b.value.is_constant() and b.value.value is not None and np.any(b.value.value == 0):
                    raise ProblemError("Division by zero is undefined.")
                value, latex = a.value / b.value, f"\\frac{{{a.latex}}}{{{b.latex}}}"
            elif isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant) and node.right.value == 2:
                value, latex = cp.square(a.value), f"\\left({a.latex}\\right)^2"
            else:
                raise ProblemError("Allowed operators: +, -, *, /, @, and **2. Use @ for matrix products; * is elementwise.")
            row = False
            if value.ndim == 1:
                row = a.value.ndim == 1 if isinstance(node.op, ast.MatMult) else (a.row or b.row)
            return Expression(value, latex, row)
        if isinstance(node, ast.Subscript):
            a = child(node.value)
            index = self.index(node.slice)
            label = (", ".join(ast.unparse(x) for x in node.slice.elts) if isinstance(node.slice, ast.Tuple) else ast.unparse(node.slice)).replace("_", r"\_")
            return Expression(a.value[index], f"{a.latex}_{{{label}}}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ATOMS:
            return self.call(node, depth)
        raise ProblemError("Only declared names, numeric literals, indexing, arithmetic, and listed atoms are allowed. Python attributes and code are not expressions.")

    def index(self, node):
        if isinstance(node, ast.Tuple):
            return tuple(self.index(x) for x in node.elts)
        if isinstance(node, ast.Slice):
            return slice(*(self.index(x) if x is not None else None for x in (node.lower, node.upper, node.step)))
        try:
            value = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            raise ProblemError("Indices and slice bounds must be literal integers.") from None
        if type(value) is not int:
            raise ProblemError("Indices must be literal integers.")
        return value

    def call(self, node, depth):
        name = node.func.id
        keywords = {}
        for kw in node.keywords:
            if kw.arg != "axis" or name not in {"sum", "max"} or kw.arg in keywords:
                raise ProblemError("Only sum/max accept the axis keyword (0 or 1).")
            axis = self.index(kw.value)
            if axis not in (0, 1):
                raise ProblemError("axis must be 0 or 1.")
            keywords[kw.arg] = axis
        if name in {"hstack", "vstack"}:
            if len(node.args) != 1 or not isinstance(node.args[0], (ast.List, ast.Tuple)) or keywords:
                raise ProblemError(f"Use {name}([expression, expression, ...]).")
            parts = [self.expression(n, depth + 1) for n in node.args[0].elts]
            if not parts:
                raise ProblemError("Stacking needs at least one expression.")
            value = ATOMS[name]([p.value for p in parts])
        else:
            expected = 2 if name in {"quad_form", "maximum"} else 1
            if name == "norm":
                if len(node.args) not in (1, 2):
                    raise ProblemError("Use norm(x), norm(x, 1), norm(x, 2), or norm(x, 'inf').")
                parts = [self.expression(node.args[0], depth + 1)]
                p = 2
                if len(node.args) == 2:
                    try:
                        p = ast.literal_eval(node.args[1])
                    except (ValueError, SyntaxError):
                        raise ProblemError("Norm order must be literal 1, 2, or 'inf'.") from None
                    if p not in (1, 2, "inf", "fro") or isinstance(p, bool):
                        raise ProblemError("Norm order must be 1, 2, or 'inf'.")
                value = cp.norm(parts[0].value, p=p)
                return Expression(value, r"\left\|" + parts[0].latex + r"\right\|_{" + str(p).replace("inf", r"\infty").replace("fro", "F") + "}")
            if len(node.args) != expected:
                raise ProblemError(f"{name} needs {expected} argument(s).")
            parts = [self.expression(n, depth + 1) for n in node.args]
            if name == "quad_form":
                x, matrix = (p.value for p in parts)
                if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or x.shape not in {(matrix.shape[0],), (matrix.shape[0], 1)}:
                    raise ProblemError("quad_form requires a vector and a square matrix of matching dimensions.")
                if not x.is_constant() and not matrix.is_constant():
                    raise ProblemError("quad_form cannot optimize its vector and matrix together: the joint expression is not DCP. Fix one as a parameter.")
            value = ATOMS[name](*(p.value for p in parts), **keywords)
        return Expression(value, atom_math(name, parts, keywords), not parts[0].row if name == 'transpose' and value.ndim == 1 else False)


def build_problem(spec, limits=None):
    """Validate a version-1 plain specification and create fresh CVXPY objects."""
    limits = limits or Limits()
    if not isinstance(spec, dict) or spec.get("version") != 1:
        raise ProblemError("Expected a version-1 problem specification.")
    names, substitutions, variables, declarations, constraints = {}, {}, {}, [], []
    totals = {"variables": 0, "parameters": 0}
    for kind in ("variables", "parameters"):
        rows = spec.get(kind)
        if not isinstance(rows, list) or (kind == "variables" and not rows):
            raise ProblemError(f"{kind} must be a list; declare at least one decision variable.")
        for row in rows:
            if not isinstance(row, dict):
                raise ProblemError("Each declaration must be an object with a name and shape/value.")
            name, domain = row.get("name"), row.get("domain", "free")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", name) or name in ATOMS or name == "latex" or keyword.iskeyword(name) or name in names:
                raise ProblemError("Names must be unique identifiers, start with a letter, and differ from atom names.")
            if not isinstance(domain, str) or domain not in DOMAINS:
                raise ProblemError(f"{name}: choose free, nonneg, nonpos, symmetric, or PSD.")
            for field in ("meaning", "units"):
                if not isinstance(row.get(field, ""), str) or len(row.get(field, "")) > 500:
                    raise ProblemError(f"{name}: {field} must be short text.")
            array = numeric(row.get("value")) if kind == "parameters" else None
            shape = tuple(array.shape) if array is not None else shape_of(row.get("shape"))
            size = math.prod(shape)
            totals[kind] += size
            cap = limits.variable_entries if kind == "variables" else limits.parameter_entries
            if totals[kind] > cap:
                raise ProblemError(f"{kind} exceed the owner-configured entry limit.")
            if domain in {"PSD", "symmetric"} and (len(shape) != 2 or shape[0] != shape[1]):
                raise ProblemError(f"{name}: {domain} requires a square matrix.")
            flags = {domain: True} if domain != "free" else {}
            try:
                if kind == "parameters":
                    obj = cp.Parameter(shape=shape, name=name, **flags)
                    obj.value = array
                    if not shape:
                        substitutions[name] = number(array)
                else:
                    # Explicit domain constraints expose all duals. Do not duplicate
                    # them with implicit variable attributes: duplicates split duals.
                    obj = cp.Variable(shape=shape, name=name)
                    variables[name] = obj
                    if domain in {"nonneg", "nonpos", "PSD", "symmetric"}:
                        value = {"nonneg": lambda: obj >= 0, "nonpos": lambda: obj <= 0,
                                 "PSD": lambda: obj >> 0, "symmetric": lambda: obj == obj.T}[domain]()
                        relation = {"nonneg": r"\ge 0", "nonpos": r"\le 0", "PSD": r"\succeq 0", "symmetric": " = " + symbol(name) + r"^{\mathsf T}"}[domain]
                        constraints.append({"source": f"{name}: {domain} domain", "latex": symbol(name) + relation,
                                            "value": value, "is_dcp": True})
                        if domain == "PSD":
                            constraints.append({"source": f"{name}: symmetry for PSD domain",
                                                "latex": symbol(name) + " = " + symbol(name) + r"^{\mathsf T}",
                                                "value": obj == obj.T, "is_dcp": True})
            except ValueError as error:
                raise ProblemError(f"{name}: value/domain mismatch: {error}") from None
            names[name] = obj
            declarations.append({"name": name, "kind": kind[:-1], "shape": list(shape), "domain": domain, "latex_name": symbol(name),
                                 "meaning": row.get("meaning", ""), "units": row.get("units", ""),
                                 "value": array.tolist() if array is not None else None})
    parser = Parser(names, substitutions, limits)
    criteria = []
    rows = spec.get("criteria")
    if rows is not None:
        if not isinstance(rows, list) or not 2 <= len(rows) <= limits.criteria:
            raise ProblemError(f"Declare between 2 and {limits.criteria} criteria (owner-configurable workload limit).")
        names_seen = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or row.get("sense") not in ("minimize", "maximize"):
                raise ProblemError("Each criterion needs a name, minimize/maximize direction, and expression.")
            label = row.get("name")
            if not isinstance(label, str) or not label.strip() or len(label) > 80 or label in names_seen:
                raise ProblemError("Criterion names must be nonempty, unique, and at most 80 characters.")
            names_seen.add(label)
            for field in ("meaning", "units"):
                if not isinstance(row.get(field, ""), str) or len(row.get(field, "")) > 500:
                    raise ProblemError("Criterion meaning and units must be short text.")
            expression = parser.expression(parser.tree(row.get("expression")))
            if expression.value.shape != ():
                raise ProblemError(f"Criterion {index+1} must be scalar.")
            objective = cp.Minimize(expression.value) if row["sense"] == "minimize" else cp.Maximize(expression.value)
            criteria.append({**row, "value": expression.value, "latex": expression.latex,
                             "is_dcp": objective.is_dcp(), "curvature": expression.value.curvature})
            if not objective.is_dcp():
                parser.diagnostics.append({"expression": row["expression"], "latex": expression.latex,
                    "curvature": expression.value.curvature, "sign": expression.value.sign,
                    "rule": f"Criterion {index+1} failed: minimize convex or maximize concave."})
        objective_spec = rows[0]
    else:
        objective_spec = spec.get("objective", {})
    if not isinstance(objective_spec, dict) or objective_spec.get("sense") not in ("minimize", "maximize"):
        raise ProblemError("Choose minimize or maximize for the objective.")
    expression = parser.expression(parser.tree(objective_spec.get("expression")))
    if expression.value.shape != ():
        raise ProblemError("The objective must be scalar. Reduce vectors with sum, sum_squares, or norm.")
    sense = objective_spec["sense"]
    cp_objective = cp.Minimize(expression.value) if sense == "minimize" else cp.Maximize(expression.value)
    objective_display = {"source": objective_spec["expression"], "latex": r"\operatorname{" + sense + r"}\quad " + expression.latex,
                         "curvature": expression.value.curvature, "sign": expression.value.sign, "sense": sense}
    if not criteria and not cp_objective.is_dcp():
        parser.diagnostics.append({"expression": objective_spec["expression"], "latex": expression.latex,
            "curvature": expression.value.curvature, "sign": expression.value.sign,
            "rule": "Objective rule failed: minimize a convex expression or maximize a concave expression."})
    sources = spec.get("constraints")
    if not isinstance(sources, list) or len(sources) > limits.constraints:
        raise ProblemError("Constraints must be a list of at most 100 comparison expressions.")
    for source in sources:
        node = parser.tree(source)
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], (ast.LtE, ast.GtE, ast.Eq)):
            raise ProblemError("Each constraint uses one <=, >=, or ==. Split chained comparisons into separate lines.")
        a, b = parser.expression(node.left), parser.expression(node.comparators[0])
        try:
            if isinstance(node.ops[0], ast.LtE):
                value, relation = a.value <= b.value, r"\le"
            elif isinstance(node.ops[0], ast.GtE):
                value, relation = a.value >= b.value, r"\ge"
            else:
                value, relation = a.value == b.value, "="
        except ValueError as error:
            raise ProblemError(f"{source}: {error}") from None
        if value.size > limits.parameter_entries:
            raise ProblemError("Constraint exceeds configured entry limit.")
        constraints.append({"source": source, "latex": f"{a.latex} {relation} {b.latex}",
                            "value": value, "is_dcp": value.is_dcp()})
        if not value.is_dcp():
            parser.diagnostics.append({"expression": source, "curvature": f"left {a.value.curvature}; right {b.value.curvature}",
                                       "sign": f"left {a.value.sign}; right {b.value.sign}", "latex": f"{a.latex} {relation} {b.latex}",
                                       "rule": f"Constraint {len(constraints)} failed: equality needs affine sides; <= needs convex left and concave right (reverse for >=)."})
    problem = cp.Problem(cp_objective, [c["value"] for c in constraints])
    return BuiltProblem(problem, variables, declarations, objective_display, constraints, parser.diagnostics, criteria, names)
