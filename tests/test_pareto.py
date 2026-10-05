"""Known answers and numerical safeguards for Boyd §4.7 / §6.3 tradeoffs."""
from copy import deepcopy
import json
import numpy as np
import pytest
from core import pareto
from core.input import convert_spec, editable_spec
from core.parser import ProblemError, build_problem
from core.presets import get_preset
from core.solve import solve

MULTI = ['return-risk', 'return-risk-turnover', 'four-criteria', 'least-squares-tradeoff']


@pytest.mark.parametrize('key', MULTI)
@pytest.mark.parametrize('method', ['weighted', 'epsilon'])
def test_frontiers_are_verified_feasible_nondominated_and_serializable(key, method):
    spec = get_preset(key)
    result = pareto.run_frontier(spec, {'method': method, 'samples': 20})
    assert result['status'] == 'complete'
    assert len(result['anchors']) == len(spec['criteria'])
    assert len(result['points']) >= 2
    json.dumps(result, allow_nan=False)
    points = result['points']
    values = [p['values'] for p in points]
    normal = result['normalization']
    kept = pareto.nondominated_indices(values, [c['sense'] for c in spec['criteria']], normal['anchor_ideal'], normal['dominance_scales'])
    assert kept == list(range(len(points)))
    for point in points:
        assert point['result']['verified_optimal']
        assert point['result']['max_violation'] <= 1e-5
        if 'w' in point['result']['variables']:
            weights = np.array(point['result']['variables']['w'])
            assert weights.sum() == pytest.approx(1, abs=1e-6)
            assert weights.min() >= -1e-6
        if point['generator']['method'] == 'epsilon':
            for i, bound in enumerate(point['generator']['epsilon']):
                if bound is None:
                    continue
                sign = -1 if spec['criteria'][i]['sense'] == 'maximize' else 1
                assert sign*(point['values'][i]-bound) <= 1e-5


def test_anchor_endpoints_match_single_criterion_optima():
    spec = get_preset('return-risk')
    result = pareto.run_frontier(spec, {'samples': 12})
    for index, anchor in enumerate(result['anchors']):
        single = deepcopy(spec)
        single['objective'] = single.pop('criteria')[index]
        optimum = solve(build_problem(single))
        assert anchor['anchor_optimum'] == pytest.approx(optimum['optimal_value'], abs=1e-7)
        # Tied anchor refinement may move the primary value by the explicit slack.
        assert abs(anchor['values'][index]-anchor['anchor_optimum']) <= anchor['tie_slack']+1e-7
    assert result['ranges'][0]['anchor_optimum'] == pytest.approx(.008, abs=1e-7)
    assert result['ranges'][1]['anchor_optimum'] == pytest.approx(.002, abs=1e-7)


def test_raw_weighted_sum_has_independent_closed_form():
    # .5*(.01*x²+.04*(1-x)²) - .5*(.001*x+.002*(1-x))
    # derivative: .05*x-.04+.0005=0 -> x=.79.
    result = pareto.run_frontier(get_preset('return-risk'),
        {'samples': 3, 'normalize': False, 'weights': [.5,.5]})
    point = next(p for p in result['points'] if p['generator']['method'] == 'weighted')
    np.testing.assert_allclose(point['result']['variables']['w'], [.79,.21], atol=1e-5)
    assert result['normalization']['scales'] == [1,1]


def test_normalization_and_custom_scales_are_used_in_actual_math():
    result = pareto.run_frontier(get_preset('return-risk'), {'samples': 3, 'weights': [.5,.5]})
    ideal, scales = [np.asarray(result['normalization'][field]) for field in ('ideal','scales')]
    # derivative of normalized .5*variance/s0 - .5*return/s1.
    expected = np.clip((.04-.0005*scales[0]/scales[1])/.05, 0, 1)
    point = next(p for p in result['points'] if p['generator']['method'] == 'weighted')
    assert point['result']['variables']['w'][0] == pytest.approx(expected, abs=1e-5)
    custom = pareto.run_frontier(get_preset('return-risk'), {'samples': 3, 'weights': [.5,.5], 'scales': [.1,.01]})
    assert custom['normalization']['scales'] == [.1,.01]


def test_zero_weight_and_duplicate_criteria_ties_refined():
    spec = get_preset('return-risk')
    spec['criteria'].append({'name':'Constant', 'sense':'minimize', 'expression':'1'})
    result = pareto.run_frontier(spec, {'samples': 4, 'weights': [0,0,1]})
    assert all(p['result']['verified_optimal'] for p in result['points'])
    constant = result['anchors'][2]
    assert constant['tie_break'] and constant['tie_slack'] > 0
    assert constant['values'][2] == 1
    assert not np.isnan(result['normalization']['scales']).any()
    assert all(p['tie_attempts'] for p in result['anchors'])


def test_dominance_uses_maxima_and_all_dimensions_and_deduplicates():
    assert pareto.nondominated_indices([[1,2],[2,1],[1,2],[.5,1]], ['minimize','maximize']) == [0,3]
    # First two tie in the first two projections; third criterion matters.
    assert pareto.nondominated_indices([[1,1,3],[1,1,2],[0,2,4]], ['minimize']*3) == [1,2]


@pytest.mark.parametrize('change', [{'samples':1},{'samples':51},{'weights':[-1,2]}, {'weights':[0,0]},
    {'weights':[1]}, {'weights':[float('nan'),1]}, {'scales':[0,1]}, {'primary':2},
    {'epsilon':[None,None]}, {'seed':-1}, {'normalize':'yes'}, {'method':'magic'}])
def test_bad_sampling_settings_are_rejected(change):
    with pytest.raises(ProblemError):
        pareto.run_frontier(get_preset('return-risk'), change)


def test_non_dcp_and_infeasible_anchor_errors():
    spec = get_preset('return-risk')
    spec['criteria'][1]['expression'] = 'square(w[0])'
    assert not build_problem(spec).preview()['is_dcp']
    with pytest.raises(ProblemError, match='DCP'):
        pareto.run_frontier(spec)
    spec = get_preset('return-risk')
    spec['constraints'].append('w <= -1')
    with pytest.raises(ProblemError, match='Anchor.*infeasible'):
        pareto.run_frontier(spec)
    spec = {'version':1, 'variables':[{'name':'x','shape':[]}], 'parameters':[], 'constraints':[],
        'criteria':[{'name':'x','sense':'minimize','expression':'x'}, {'name':'size','sense':'minimize','expression':'square(x)'}]}
    with pytest.raises(ProblemError, match='Anchor.*unbounded'):
        pareto.run_frontier(spec)


def test_partial_sweep_preserves_completed_anchors(monkeypatch):
    original = pareto.generators
    expired = False
    def expire_after_anchors(*args):
        nonlocal expired
        expired = True
        return original(*args)
    real_time = pareto.time.perf_counter
    monkeypatch.setattr(pareto, 'generators', expire_after_anchors)
    monkeypatch.setattr(pareto.time, 'perf_counter', lambda: real_time() + (1000 if expired else 0))
    result = pareto.run_frontier(get_preset('return-risk'), {'samples': 10})
    assert result['status'] == 'incomplete'
    assert len(result['points']) == 2


def test_seed_reproducibility_and_every_multicriterion_latex_roundtrip():
    for name in MULTI:
        spec = get_preset(name)
        converted = convert_spec(editable_spec(spec, 'latex'), 'latex')
        assert build_problem(converted).preview()['is_dcp']
        a = pareto.run_frontier(spec, {'samples':10})
        b = pareto.run_frontier(converted, {'samples':10})
        assert [p['generator'] for p in a['points']] == [p['generator'] for p in b['points']]
        np.testing.assert_allclose([p['values'] for p in a['points']], [p['values'] for p in b['points']], atol=1e-5)


def test_plot_types_and_optional_mesh_are_explicit():
    from core.charts import frontier_charts
    for key, types in [('return-risk',['scatter']), ('return-risk-turnover',['scatter3d','mesh3d']),
                       ('four-criteria',['scatter3d','parcoords','splom'])]:
        result = pareto.run_frontier(get_preset(key), {'samples':12})
        charts = frontier_charts(result)
        traces = [trace for chart in charts for trace in chart['figure']['data']]
        assert [t['type'] for t in traces] == types
        if key == 'return-risk-turnover':
            mesh = traces[1]
            assert mesh['visible'] == 'legendonly' and mesh['showlegend']
            assert mesh['name'] == 'Interpolation (not solved)'
