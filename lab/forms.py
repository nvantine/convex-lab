from django import forms
from core.input import convert_spec, editable_spec
from core.solve import SOLVERS
from core.data import PORTFOLIO_PRESETS
from core.presets import PRESETS


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


def initial_from_spec(name, spec, language='latex', limits=None):
    source = editable_spec(spec, language, limits)
    objective = source.get('objective', {'sense': 'minimize', 'expression': ''})
    return {'name': name, 'variables': source['variables'], 'parameters': source['parameters'],
            'source_language': language, 'mode': 'multi' if source.get('criteria') else 'single',
            'sense': objective['sense'], 'expression': objective['expression'],
            'criteria': source.get('criteria', []), 'constraints': '\n'.join(source['constraints']),
            'solver': 'CLARABEL', 'method': 'weighted', 'samples': 20, 'normalize': True, 'primary': 0, 'seed': 42}


class DatasetForm(forms.Form):
    name = forms.CharField(max_length=120, initial='Market history')
    source = forms.ChoiceField(choices=[('alpaca','Alpaca · adjusted IEX daily bars'), ('yfinance','yfinance · adjusted Yahoo daily prices')], label='Data provider')
    symbols = forms.CharField(label='Ticker symbols', help_text='Stocks or ETFs, separated by commas or spaces. Use actual ticker symbols, not a description.')
    start = forms.DateField(widget=forms.DateInput(attrs={'type':'date'}), label='Start date (inclusive)')
    end = forms.DateField(widget=forms.DateInput(attrs={'type':'date'}), label='End date (inclusive, completed days)')
    batch_size = forms.IntegerField(required=False,min_value=1,max_value=5,initial=5,label='Symbols per batch')
    prefer_cache = forms.BooleanField(required=False,initial=True,label='Reuse recent locally cached prices')
    refresh_daily = forms.BooleanField(required=False,initial=True,label='Refresh daily after market close (owner only; requires the refresh timer)')

    def clean_symbols(self):
        import re
        from django.conf import settings
        values = list(dict.fromkeys(re.split(r'[\s,]+', self.cleaned_data['symbols'].strip().upper())))
        if not values or len(values)>settings.LAB_MAX_ASSETS or any(not re.fullmatch(r'[A-Z^][A-Z0-9.\^=\-]{0,19}', v) for v in values):
            raise forms.ValidationError(f'Enter 1–{settings.LAB_MAX_ASSETS} actual ticker symbols (for example SPY, AAPL, AGG).')
        return values

    def clean(self):
        from core.providers import last_completed_day
        data = super().clean()
        if data.get('start') and data.get('end'):
            if data['start'] >= data['end']:
                self.add_error('end','End must be after start.')
            if data['end'] > last_completed_day():
                self.add_error('end','Choose a completed trading day. Today is available after 5pm New York time.')
        return data


class TrainingForm(forms.Form):
    preset = forms.ChoiceField(choices=[(k, PRESETS[k][0]) for k in PORTFOLIO_PRESETS], label='Starting example')
    estimator = forms.ChoiceField(choices=[('ledoit-wolf','Ledoit–Wolf shrinkage'), ('sample','Sample covariance')], label='Covariance estimator')
    lookback = forms.IntegerField(required=False, min_value=2, label='Training return observations (optional)', help_text='Blank uses all training observations. Estimates and CVaR scenarios use training only.')


class EvaluationForm(forms.Form):
    dataset = forms.ModelChoiceField(queryset=None, label='Frozen dataset')
    variable = forms.ChoiceField(label='Decision vector to treat as asset weights')
    cost_bps = forms.FloatField(min_value=0,max_value=1000,initial=10,label='Trading cost (bps per buy or sell)')
    borrow_rate = forms.FloatField(min_value=0,max_value=1,initial=.03,label='Annual short borrow rate (fraction)',help_text='0.03 means 3%; charged on prior-close short notional, calendar days / 365.')
    financing_rate = forms.FloatField(min_value=0,max_value=1,initial=0,label='Annual negative-cash financing rate (fraction)')
    risk_free_rate = forms.FloatField(min_value=0,max_value=1,initial=0,label='Annual risk-free rate for Sharpe (fraction)',help_text='Used in the statistic only. Positive cash earns zero in this model.')
    mode = forms.ChoiceField(required=False,choices=[('rolling','Rolling re-optimization'),('fixed','Restore original weights')],initial='rolling',label='Rebalance policy')
    frequency = forms.ChoiceField(required=False,choices=[('monthly','Monthly'),('weekly','Weekly'),('daily','Daily'),('hold','Hold after entry')],initial='monthly',label='Rebalance frequency')
    lookback = forms.IntegerField(required=False,min_value=2,initial=126,label='Rolling lookback (past return observations)')
    estimator = forms.ChoiceField(required=False,choices=[('ledoit-wolf','Ledoit–Wolf'),('sample','Sample covariance')],initial='ledoit-wolf',label='Rolling covariance estimator')
    solver = forms.ChoiceField(required=False,choices=[(s,s) for s in SOLVERS],initial='CLARABEL',label='Rolling solver')
    mean_parameter = forms.ChoiceField(required=False,label='Parameter replaced by mean returns')
    covariance_parameter = forms.ChoiceField(required=False,label='Parameter replaced by covariance')
    returns_parameter = forms.ChoiceField(required=False,label='Parameter replaced by scenario returns')
    scenario_count_parameter = forms.ChoiceField(required=False,label='Parameter replaced by scenario count')
    previous_weights_parameter = forms.ChoiceField(required=False,label='Parameter replaced by prior-close drifting weights')
    scenario_variable = forms.ChoiceField(required=False,label='Auxiliary vector resized to scenario count (optional)')

    def __init__(self, *args, datasets, variables, spec=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.field_groups=[('Portfolio and rebalance policy',['dataset','variable','mode','frequency']),
            ('Costs and metric assumptions',['cost_bps','borrow_rate','financing_rate','risk_free_rate']),
            ('Rolling inputs (used only for rolling re-optimization)', ['lookback','estimator','solver','mean_parameter',
             'covariance_parameter','returns_parameter','scenario_count_parameter','previous_weights_parameter','scenario_variable'])]
        self.fields['dataset'].queryset = datasets
        self.fields['variable'].choices = [(v,v) for v in variables]
        spec=spec or {'parameters':[],'variables':[]}
        parameters=[p['name'] for p in spec['parameters']]
        defaults={'mean_parameter':'mu','covariance_parameter':'Sigma','returns_parameter':'R',
                  'scenario_count_parameter':'scenario_count','previous_weights_parameter':'w_prev','scenario_variable':'u'}
        for field,default in defaults.items():
            names=parameters if field!='scenario_variable' else [v['name'] for v in spec['variables']]
            self.fields[field].choices=[('','Keep unchanged')]+[(name,name) for name in names]
            if default in names: self.initial[field]=default

    def grouped_fields(self):
        return [(label,[self[name] for name in names]) for label,names in self.field_groups]

    def options(self):
        result={key:self.cleaned_data[key] for key in ('cost_bps','borrow_rate','financing_rate','risk_free_rate')}
        result.update({key:self.cleaned_data[key] or '' for key in ('mean_parameter','covariance_parameter','returns_parameter','scenario_count_parameter','previous_weights_parameter','scenario_variable')})
        result.update(mode=self.cleaned_data['mode'] or 'fixed',frequency=self.cleaned_data['frequency'] or 'hold',
            lookback=self.cleaned_data['lookback'] or 126,estimator=self.cleaned_data['estimator'] or 'ledoit-wolf',solver=self.cleaned_data['solver'] or 'CLARABEL')
        return result
