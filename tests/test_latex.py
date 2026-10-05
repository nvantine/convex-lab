"""The LaTeX path must mean the same thing as the expression path."""
import ast
import numpy as np
import pytest
from core.latex_input import LatexError, to_expression
from core.notation import expression_source
from core.parser import ProblemError, build_problem
from core.presets import PRESETS, get_preset
from core.solve import solve


def shapes(spec):
    return {d['name']:tuple(d['shape']) for d in build_problem(spec).declarations}


@pytest.mark.parametrize('key', [key for key in PRESETS if 'objective' in get_preset(key)])
def test_every_initial_preset_roundtrips_and_has_same_optimum(key):
    spec = get_preset(key)
    names = shapes(spec)
    changed = {**spec, 'objective': {**spec['objective'], 'expression': to_expression(expression_source(spec['objective']['expression'], spec), names)},
               'constraints': [to_expression(expression_source(c, spec), names) for c in spec['constraints']]}
    original, converted = solve(build_problem(spec)), solve(build_problem(changed))
    assert converted['status'] == original['status'] == 'optimal'
    assert converted['optimal_value'] == pytest.approx(original['optimal_value'], abs=1e-6)
    for name in original['variables']:
        np.testing.assert_allclose(converted['variables'][name], original['variables'][name], atol=1e-4)


def test_quadratic_and_linear_forms_are_recognized():
    names = {'w': (2,), 'Sigma': (2,2), 'mu': (2,), 'lam': ()}
    source = to_expression(r'\mu^\top w - \lambda w^\top \Sigma w', names)
    assert 'quad_form(w, Sigma)' in source
    assert 'transpose(mu) @ w' in source
    assert 'lam' in source
    spec = get_preset('mean-variance')
    spec['parameters'][-1]['name'] = 'lam'
    spec['objective']['expression'] = source
    assert build_problem(spec).problem.is_dcp()


@pytest.mark.parametrize('tex, expected', [
    (r'\sum_i w_i', 'sum(w)'), (r'\sum_{i} (w)_{i}', 'sum(w)'),
    (r'\|w\|_1', "norm(w, 1)"), (r'\|w\|_{\infty}', "norm(w, 'inf')"),
    (r'\frac{w_0}{2}', 'w[0] / 2.0'), (r'\sum_i w_i^2', 'sum(square(w))'),
    (r'\sum_{i,j} X_{i,j}', 'sum(X)'), (r'\sum_{\mathrm{rows}}X', 'sum(X, axis=0)'),
    (r'\max\{w,0\}', 'maximum(w, 0.0)'), (r'|w|', 'abs(w)'),
])
def test_common_notation(tex, expected):
    assert to_expression(tex, {'w': (2,), 'X': (2,2)}) == expected


def test_indices_stacking_and_frobenius_norm():
    names = {'x': (2,), 'X': (2,2)}
    assert to_expression(r'X_{0,1}', names) == 'X[0, 1]'
    assert to_expression(r'\|X\|_F^2', names) == 'sum_squares(X)'
    assert 'hstack' in to_expression(r'\begin{bmatrix}x & x\end{bmatrix}', names)
    assert to_expression(r'10^{-3} x', names) == '0.001 * x'


@pytest.mark.parametrize('source', [r'\input{secret}', r'\href{file}{x}', r'\unknown x', r'x.value', r'\frac{x}',
                                    r'\|x\|_3', r'x^3', r'x^y', r'\sum_{i=1}^5 x_i', r'x < 1', r'x = 1 = 2', r'x y'])
def test_unsupported_or_ambiguous_notation_is_rejected(source):
    with pytest.raises(LatexError):
        to_expression(source, {'x': (2,), 'y': (2,)})


def test_literal_latex_can_be_used_inside_atom_calls():
    spec = get_preset('min-variance')
    spec['objective']['expression'] = r'latex(r"w^\top \Sigma w")'
    result = solve(build_problem(spec))
    np.testing.assert_allclose(result['variables']['w'], [.8,.2], atol=1e-5)
    spec['objective']['expression'] = r'quad_form(w, latex(r"\Sigma"))'
    assert build_problem(spec).problem.is_dcp()
    spec['objective']['expression'] = 'latex(__import__("os"))'
    with pytest.raises(ProblemError, match='literal string'):
        build_problem(spec)


def test_renderer_uses_math_instead_of_function_names():
    preview = build_problem(get_preset('mean-variance')).preview()
    latex = preview['objective']['latex']
    assert r'\Sigma' in latex and r'\mu' in latex and r'\top' in latex
    assert '@' not in latex and 'quad_form' not in latex
    budget = preview['constraints'][0]['latex']
    assert r'\sum' in budget and 'operatorname{sum}' not in budget
    spec = get_preset('least-squares')
    assert r'\right\|_{2}^2' in build_problem(spec).preview()['objective']['latex']


def test_large_latex_and_bad_symbols_have_friendly_errors():
    with pytest.raises(LatexError):
        to_expression('x+'*2000+'x', {'x': ()})
    with pytest.raises(LatexError, match='Unknown symbol'):
        to_expression(r'\theta x', {'x': ()})


def test_slices_roundtrip_without_python_looking_text():
    spec = get_preset('min-variance')
    for source in ('sum(w[0:2])', 'sum(w[::-1])', 'w[-1]', 'sum(Sigma[:, 0])'):
        rendered = expression_source(source, spec)
        assert r'\text' not in rendered
        converted = to_expression(rendered, shapes(spec))
        # Build/solve to validate index shapes through the actual whitelist.
        changed = {**spec, 'objective': {'sense': 'minimize', 'expression': converted}}
        assert build_problem(changed).problem.is_dcp()


def test_matrix_product_row_orientation_is_preserved_in_display():
    spec = get_preset('min-variance')
    spec['parameters'].append({'name':'v', 'value':[1,2]})
    for expression in ('transpose(w) @ Sigma @ v', 'w @ Sigma @ v', 'transpose(w) @ v'):
        spec['objective']['expression'] = expression
        latex = expression_source(expression, spec)
        assert latex.count(r'^{\top}') == 1
        parsed = to_expression(latex, shapes(spec))
        assert build_problem({**spec, 'objective':{'sense':'minimize','expression':parsed}}).problem.is_dcp()


def test_juxtaposed_declared_letters_and_exact_names():
    assert to_expression(r'\|Ax-b\|_2^2', {'A':(3,2),'x':(2,),'b':(3,)}) == 'sum_squares(A @ x - b)'
    assert to_expression('Ax', {'A':(3,2),'x':(2,), 'Ax':(3,)}) == 'Ax'
    with pytest.raises(LatexError, match='transpose'):
        to_expression('xy', {'x':(2,), 'y':(2,)})


def test_notation_conversion_respects_owner_limits():
    from core.input import convert_spec, editable_spec
    from core.parser import Limits
    spec = get_preset('min-variance')
    spec['variables'][0]['shape'] = [5001]
    spec['parameters'] = []
    spec['objective']['expression'] = 'sum_squares(w)'
    spec['constraints'] = ['sum(w) == 1']
    limits = Limits(variable_entries=6000)
    source = editable_spec(spec, 'latex', limits)
    assert build_problem(convert_spec(source, 'latex', limits), limits).problem.is_dcp()


def test_standard_portfolio_math_has_no_unnecessary_parentheses():
    spec = get_preset('mean-variance')
    assert expression_source(spec['objective']['expression'], spec) == r'\mu^{\top} w - \mathrm{risk\_aversion}  w^{\top} \Sigma w'
    preview = build_problem(spec).preview()
    assert r'\left(' not in preview['objective']['latex']
    assert preview['constraints'][0]['latex'] == r'\sum_{i}w_{i} = 1'


@pytest.mark.parametrize('source, grouping', [
    ('3 * (w[0] + w[1])', True),
    ('w[0] - (w[1] + 2)', True),
    ('square(w[0] + w[1])', True),
    ('-(w[0] - w[1])', True),
    ('(w[0] + w[1]) / 3', False),
    ('w[0] * 3', False),
    ('sum(w)', False),
    ('quad_form(w, Sigma)', False),
])
def test_minimal_grouping_roundtrips_without_changing_values(source, grouping):
    spec = get_preset('min-variance')
    rendered = expression_source(source,spec)
    assert (r'\left(' in rendered) == grouping
    converted = to_expression(rendered,shapes(spec))
    before, after = build_problem(spec), build_problem(spec)
    for built in (before,after):
        built.names['w'].value = [.2,.8]
    from core.parser import Parser, Limits
    for parser, expression in [(Parser(before.names,{},Limits()),source),(Parser(after.names,{},Limits()),converted)]:
        value = parser.expression(parser.tree(expression)).value.value
        if expression == source:
            original = value
        else:
            np.testing.assert_allclose(value,original)
