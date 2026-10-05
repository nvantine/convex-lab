from core.comparison import comparison_rows,experiment_metadata
from core.presets import get_preset


def test_exact_differences_and_selected_order():
    rows=comparison_rows([{'metadata':{'cost':10,'data':'a','seed':7}},
                          {'metadata':{'cost':15,'data':'a','seed':None}}])
    assert [r['name'] for r in rows if r['different']]==['cost','seed']
    assert rows[0]['values']==[10,15]


def test_objective_changes_are_visible_even_when_name_is_the_same():
    a=get_preset('min-variance');b=get_preset('min-variance')
    b['constraints'].append('w[0] <= 0.6')
    rows=comparison_rows([{'metadata':experiment_metadata(s,{})} for s in (a,b)])
    differences=[r['name'] for r in rows if r['different']]
    assert 'Constraints' in differences and 'Problem fingerprint' in differences
    assert 'Objective / criteria' not in differences
