from django import forms
from core.input import convert_spec, editable_spec
from core.solve import SOLVERS


class ProblemForm(forms.Form):
    name = forms.CharField(max_length=120, label='Problem name')
    variables = forms.JSONField(widget=forms.Textarea(attrs={'rows': 7}), help_text='Shapes: [] scalar, [n] vector, [rows, columns] matrix.')
    parameters = forms.JSONField(required=False, widget=forms.Textarea(attrs={'rows': 9}), help_text='Named constants with numeric values. Domains certify signs and positive semidefiniteness.')
    source_language = forms.ChoiceField(required=False, choices=[('latex', 'LaTeX'), ('expression', 'Expressions')], widget=forms.HiddenInput)
    mode = forms.ChoiceField(required=False, choices=[('single', 'One objective'), ('multi', 'Multiple criteria')], label='Problem type')
    sense = forms.ChoiceField(choices=[('minimize', 'Minimize'), ('maximize', 'Maximize')], required=False, label='Objective direction')
    expression = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2, 'class': 'equation-input'}), label='Objective expression', max_length=20000)
    constraints = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 6, 'class': 'equation-input'}), label='Constraints', help_text='One comparison per line. LaTeX: =, \\le, \\ge. Expressions: ==, <=, >=.')
    criteria = forms.JSONField(required=False, widget=forms.Textarea(attrs={'rows': 8}), help_text='Two or more named scalar criteria, each with its own direction and expression.')
    solver = forms.ChoiceField(choices=[(s, s) for s in SOLVERS], initial='CLARABEL')
    method = forms.ChoiceField(required=False, choices=[('weighted', 'Weighted sum'), ('epsilon', 'Epsilon constraints')])
    samples = forms.IntegerField(required=False, min_value=2, initial=20, label='Sample budget (including anchors)')
    normalize = forms.BooleanField(required=False, initial=True, label='Normalize criteria using anchor ranges')
    primary = forms.IntegerField(required=False, min_value=0, initial=0, label='Primary criterion (zero-based, epsilon method)')
    weights = forms.JSONField(required=False, label='Optional first weight vector (JSON)')
    epsilon = forms.JSONField(required=False, label='Optional first epsilon bounds (JSON)', help_text='Raw criterion units. null for the primary; upper bounds for minimized criteria, lower bounds for maximized criteria.')
    scales = forms.JSONField(required=False, label='Optional positive normalization scales (JSON)')
    seed = forms.IntegerField(required=False, initial=42, label='Sampling seed')

    def specification(self, limits=None):
        data = self.cleaned_data
        spec = {'version': 1, 'variables': data['variables'], 'parameters': [] if data['parameters'] is None else data['parameters'],
                'constraints': [line.strip() for line in data['constraints'].splitlines() if line.strip()]}
        if data.get('mode') == 'multi':
            spec['criteria'] = data['criteria']
        else:
            spec['objective'] = {'sense': data['sense'] or 'minimize', 'expression': data['expression']}
        language = data['source_language'] or 'expression'
        converted = convert_spec(spec, language, limits)
        converted['input'] = {'language': language, **{key: value for key, value in spec.items() if key in ('objective', 'criteria', 'constraints')}}
        return converted

    def frontier_options(self):
        data = self.cleaned_data
        return {'solver': data['solver'], 'method': data['method'] or 'weighted',
                'samples': data['samples'] if data['samples'] is not None else 20, 'normalize': data['normalize'],
                'primary': data['primary'] if data['primary'] is not None else 0,
                'seed': data['seed'] if data['seed'] is not None else 42,
                **{field: data[field] for field in ('weights', 'epsilon', 'scales')}}


def initial_from_spec(name, spec, language='latex'):
    source = editable_spec(spec, language)
    objective = source.get('objective', {'sense': 'minimize', 'expression': ''})
    return {'name': name, 'variables': source['variables'], 'parameters': source['parameters'],
            'source_language': language, 'mode': 'multi' if source.get('criteria') else 'single',
            'sense': objective['sense'], 'expression': objective['expression'],
            'criteria': source.get('criteria', []), 'constraints': '\n'.join(source['constraints']),
            'solver': 'CLARABEL', 'method': 'weighted', 'samples': 20, 'normalize': True, 'primary': 0, 'seed': 42}
