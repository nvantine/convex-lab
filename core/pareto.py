"""Convex multicriterion optimization; Boyd & Vandenberghe §4.7.

All criteria are oriented as minimizations g_i (negate a maximization).
Strictly positive weighted sums are efficient. Zero weights and epsilon optima
can be weakly efficient; a positive secondary sum breaks those ties. Finite
solver tolerances and finite sampling mean we report numerical candidates,
not an exact global frontier or global nadir ranges.
"""
from copy import deepcopy
import time

import numpy as np

from core.parser import Limits, Parser, ProblemError, build_problem
from core.solve import solve

DOMINANCE_TOLERANCE = 1e-6
TIE_TOLERANCE = 1e-8


def oriented_expressions(criteria):
    return [f"-({c['expression']})" if c['sense'] == 'maximize' else f"({c['expression']})" for c in criteria]


def scalar_spec(spec, expression, additional=()):
    changed = deepcopy(spec)
    changed.pop('criteria', None)
    changed.pop('input', None)
    changed['objective'] = {'sense': 'minimize', 'expression': expression}
    changed['constraints'] += list(additional)
    return changed


def weighted_expression(expressions, weights, ideal, scales):
    return ' + '.join(f'({float(a)!r}) * (({expr}) - ({float(z)!r})) / ({float(s)!r})'
                      for expr, a, z, s in zip(expressions, weights, ideal, scales))


def criterion_values(built, criteria, limits):
    parser = Parser(built.names, {}, limits)
    values = [parser.expression(parser.tree(c['expression'])).value.value for c in criteria]
    if any(value is None or not np.isfinite(value) for value in values):
        raise ProblemError('Solver did not produce finite values for every criterion.')
    return [float(value) for value in values]


def nondominated_indices(values, senses, ideal=None, scales=None, tolerance=DOMINANCE_TOLERANCE):
    """Compare every criterion, including maxima; keep the first equivalent point."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[1] != len(senses) or not np.isfinite(array).all():
        raise ProblemError('Dominance requires a finite point-by-criterion matrix.')
    signs = np.array([-1 if s == 'maximize' else 1 for s in senses])
    z = np.zeros(len(senses)) if ideal is None else np.asarray(ideal)
    scale = np.ones(len(senses)) if scales is None else np.asarray(scales)
    oriented = (array * signs - z) / scale
    kept = []
    for i, point in enumerate(oriented):
        others = oriented
        dominated = np.any(np.all(others <= point + tolerance, axis=1) & np.any(others < point - tolerance, axis=1))
        duplicate = any(np.all(np.abs(point - oriented[j]) <= tolerance) for j in kept)
        if not dominated and not duplicate:
            kept.append(i)
    return kept


def validate_options(options, count, maximum_samples=50):
    settings = {'method': 'weighted', 'samples': maximum_samples, 'normalize': True,
                'weights': None, 'epsilon': None, 'primary': 0, 'scales': None, 'seed': 42, **options}
    if settings['method'] not in ('weighted', 'epsilon'):
        raise ProblemError('Choose weighted sum or epsilon constraints.')
    if type(settings['samples']) is not int or not count <= settings['samples'] <= maximum_samples:
        raise ProblemError(f'Sample budget must be between the criterion count ({count}) and {maximum_samples}.')
    if type(settings['primary']) is not int or not 0 <= settings['primary'] < count:
        raise ProblemError('Primary criterion index is out of range (indices start at zero).')
    if type(settings['seed']) is not int or not 0 <= settings['seed'] < 2**32:
        raise ProblemError('Seed must be an integer between 0 and 2^32-1.')
    for field in ('weights', 'epsilon', 'scales'):
        values = settings[field]
        if values is None:
            continue
        if not isinstance(values, list) or len(values) != count:
            raise ProblemError(f'{field} must contain one entry per criterion.')
        for index, value in enumerate(values):
            if field == 'epsilon' and index == settings['primary'] and value is None:
                continue
            if type(value) not in (int, float) or not np.isfinite(value):
                raise ProblemError(f'{field} entries must be finite numbers.')
            if field == 'weights' and value < 0:
                raise ProblemError('Weights must be nonnegative.')
            if field == 'scales' and value <= 0:
                raise ProblemError('Normalization scales must be strictly positive.')
        if field == 'weights' and sum(values) <= 0:
            raise ProblemError('At least one weight must be positive.')
    if type(settings['normalize']) is not bool:
        raise ProblemError('Normalization must be true or false.')
    return settings


def generators(settings, count, anchor_values, capacity):
    """Simple deterministic grids in 2D/3D; seeded samples above three criteria."""
    rng = np.random.default_rng(settings['seed'])
    result = []
    if settings['method'] == 'weighted':
        if settings['weights'] is not None:
            result.append({'method': 'weighted', 'weights': settings['weights']})
        if count == 2:
            for a in np.linspace(0, 1, max(capacity, 1)+2)[1:-1]:
                result.append({'method': 'weighted', 'weights': [float(a), float(1-a)]})
        elif count == 3:
            level = 1
            while (level+2)*(level+3)//2 - 3 <= capacity-len(result):
                level += 1
            for i in range(level+1):
                for j in range(level+1-i):
                    weights = [i/level, j/level, (level-i-j)/level]
                    if max(weights) != 1:
                        result.append({'method': 'weighted', 'weights': weights})
        while len(result) < capacity:
            result.append({'method': 'weighted', 'weights': rng.dirichlet(np.ones(count)).tolist()})
    else:
        primary = settings['primary']
        if settings['epsilon'] is not None:
            result.append({'method': 'epsilon', 'primary': primary, 'epsilon': settings['epsilon']})
        low, high = np.min(anchor_values, axis=0), np.max(anchor_values, axis=0)
        if count == 2:
            other = 1-primary
            for threshold in np.linspace(low[other], high[other], max(capacity-len(result), 1)):
                bounds = [None]*count
                bounds[other] = float(threshold)
                result.append({'method': 'epsilon', 'primary': primary, 'epsilon': bounds})
        elif count == 3:
            remaining = [i for i in range(count) if i != primary]
            size = max(1, int(np.sqrt(max(0, capacity-len(result)))))
            for a in np.linspace(low[remaining[0]], high[remaining[0]], size):
                for b in np.linspace(low[remaining[1]], high[remaining[1]], size):
                    bounds = [None]*count
                    bounds[remaining[0]], bounds[remaining[1]] = float(a), float(b)
                    result.append({'method': 'epsilon', 'primary': primary, 'epsilon': bounds})
        while len(result) < capacity:
            bounds = rng.uniform(low, high).tolist()
            bounds[primary] = None
            result.append({'method': 'epsilon', 'primary': primary, 'epsilon': bounds})
    return result[:capacity]


def run_frontier(spec, options=None, limits=None, maximum_samples=50, total_seconds=20, solve_seconds=2):
    limits = limits or Limits()
    base = build_problem(spec, limits)
    if not base.criteria:
        raise ProblemError('Declare two or more criteria before sampling a frontier.')
    if not base.preview()['is_dcp']:
        raise ProblemError('Every criterion and constraint must pass DCP before sampling.')
    criteria = spec['criteria']
    count = len(criteria)
    settings = validate_options(options or {}, count, maximum_samples)
    expressions = oriented_expressions(criteria)
    signs = np.array([-1 if c['sense'] == 'maximize' else 1 for c in criteria])
    deadline = time.perf_counter() + total_seconds
    started = time.perf_counter()
    solver = settings.get('solver', 'CLARABEL')
    calls = 0
    attempts = []

    def execute(single):
        nonlocal calls
        remaining = deadline-time.perf_counter()
        if remaining <= 0:
            raise ProblemError('Request time budget exhausted.')
        built = build_problem(single, limits)
        result = solve(built, solver, max(.001, min(solve_seconds, remaining)))
        calls += 1
        return built, result

    def candidate(expression, extra, generator, tie_break, ideal, scales):
        primary_spec = scalar_spec(spec, expression, extra)
        built, primary_result = execute(primary_spec)
        if not primary_result['verified_optimal']:
            return None, primary_result['status']
        primary_preview = built.preview()
        final_spec, final_result, final_built = primary_spec, primary_result, built
        if tie_break:
            # Restrict to the primary optimum, then improve all remaining criteria.
            # A small numerical slack is explicit in the saved math (Boyd §4.7.4).
            secondary = weighted_expression(expressions, np.ones(count), ideal, scales)
            tie_attempts = []
            for multiplier in (1, 10, 100, 1000):
                slack = TIE_TOLERANCE*multiplier*max(1, abs(primary_result['optimal_value']))
                final_spec = scalar_spec(spec, secondary, [*extra, f'({expression}) <= {primary_result["optimal_value"] + slack!r}'])
                final_built, final_result = execute(final_spec)
                tie_attempts.append({'slack': slack, 'status': final_result['status']})
                if final_result['verified_optimal']:
                    break
            if not final_result['verified_optimal']:
                return None, final_result['status']
        else:
            slack, tie_attempts = None, []
        values = criterion_values(final_built, criteria, limits)
        return {'values': values, 'generator': generator, 'result': final_result,
                'preview': final_built.preview(), 'solved_spec': final_spec,
                'primary_result': primary_result, 'primary_preview': primary_preview,
                'tie_break': tie_break, 'tie_slack': slack, 'tie_attempts': tie_attempts}, 'optimal'

    anchors = []
    for index, expression in enumerate(expressions):
        point, status = candidate(expression, [], {'method': 'anchor', 'criterion': index}, True, np.zeros(count), np.ones(count))
        if point is None:
            raise ProblemError(f'Anchor for {criteria[index]["name"]} is {status}. Add bounds, change the solver, or review feasibility before defining ranges.')
        point['anchor_optimum'] = float(point['primary_result']['optimal_value'] * signs[index])
        anchors.append(point)
    anchor_values = np.array([point['values'] for point in anchors])
    ideal = np.array([p['anchor_optimum']*signs[i] for i,p in enumerate(anchors)])
    width = np.max(anchor_values*signs, axis=0)-ideal
    flat = width <= 1e-12*np.maximum(1, np.abs(ideal))
    default_scales = np.where(flat, 1, width)
    if not settings['normalize']:
        used_ideal, used_scales = np.zeros(count), np.ones(count)
    else:
        used_ideal = ideal
        used_scales = default_scales if settings['scales'] is None else np.array(settings['scales'])
    points = list(anchors)
    samples = generators(settings, count, anchor_values, settings['samples']-count)
    completed = True
    for generator in samples:
        if time.perf_counter() >= deadline:
            completed = False
            break
        if generator['method'] == 'weighted':
            weights = generator['weights']
            expression = weighted_expression(expressions, weights, used_ideal, used_scales)
            extra, tie_break = [], any(weight == 0 for weight in weights)
        else:
            primary = generator['primary']
            expression = expressions[primary]
            extra = [f'({expressions[i]}) <= {float(float(generator["epsilon"][i])*signs[i])!r}'
                     for i in range(count) if i != primary]
            tie_break = True
        try:
            point, status = candidate(expression, extra, generator, tie_break, used_ideal, used_scales)
            attempts.append({'generator': generator, 'status': status})
            if point is not None:
                points.append(point)
        except ProblemError as error:
            attempts.append({'generator': generator, 'status': 'skipped', 'message': str(error)})
            if time.perf_counter() >= deadline:
                completed = False
                break
    # Use anchor-derived scales for meaningful numerical dominance even in raw mode.
    kept = nondominated_indices([p['values'] for p in points], [c['sense'] for c in criteria], ideal, default_scales)
    selected = [points[i] for i in kept]
    for index, point in enumerate(selected):
        point['id'] = index
    if not selected:
        raise ProblemError('No verified nondominated samples were produced.')
    ranges = [{'name': c['name'], 'anchor_optimum': anchors[i]['anchor_optimum'],
               'sample_min': min(p['values'][i] for p in selected), 'sample_max': max(p['values'][i] for p in selected)}
              for i,c in enumerate(criteria)]
    return {'status': 'complete' if completed else 'incomplete', 'settings': settings,
            'criteria': [{k:v for k,v in c.items() if k != 'value'} for c in base.criteria],
            'anchors': anchors, 'points': selected, 'ranges': ranges, 'attempts': attempts,
            'normalization': {'ideal': used_ideal.tolist(), 'scales': used_scales.tolist(),
                              'anchor_ideal': ideal.tolist(), 'dominance_scales': default_scales.tolist(),
                              'zero_anchor_spread': flat.tolist()},
            'dominance_tolerance': DOMINANCE_TOLERANCE, 'elapsed_seconds': time.perf_counter()-started,
            'solver_calls': calls, 'requested_samples': settings['samples'],
            'finished_candidates': len(points), 'filtered_candidates': len(points)-len(selected)}
