"""Convert two editable notations into the same validated expression specification."""
from copy import deepcopy
from core.latex_input import LatexError, to_expression
from core.notation import expression_source
from core.parser import Limits, ProblemError, build_problem


def convert_spec(spec, language, limits=None):
    result = deepcopy(spec)
    if language == 'expression':
        return result
    if language != 'latex':
        raise ProblemError('Choose LaTeX or expressions.')
    seed = {**spec, 'objective': {'sense': 'minimize', 'expression': '0'}, 'constraints': []}
    seed.pop('criteria', None)
    names = {name: value.shape for name, value in build_problem(seed, limits).names.items()}
    def convert(source):
        try:
            return to_expression(source, names)
        except LatexError as error:
            raise ProblemError(f'LaTeX input: {error}') from error
    if 'criteria' in result:
        rows = result['criteria']
        if not isinstance(rows, list) or not 2 <= len(rows) <= (limits or Limits()).criteria:
            raise ProblemError('Declare two or more criteria within the owner-configured limit.')
        for item in rows:
            if not isinstance(item, dict):
                raise ProblemError('Each criterion must be an object with a name, direction, and expression.')
            item['expression'] = convert(item.get('expression'))
    else:
        result['objective']['expression'] = convert(result['objective']['expression'])
    result['constraints'] = [convert(source) for source in result['constraints']]
    return result


def editable_spec(spec, language):
    result = deepcopy(spec)
    if spec.get('input', {}).get('language') == language:
        for field in ('objective', 'criteria', 'constraints'):
            if field in spec['input']:
                result[field] = deepcopy(spec['input'][field])
        return result
    if language == 'latex':
        if result.get('criteria'):
            for item in result['criteria']:
                item['expression'] = expression_source(item['expression'], spec)
        else:
            result['objective']['expression'] = expression_source(result['objective']['expression'], spec)
        result['constraints'] = [expression_source(source, spec) for source in spec['constraints']]
    return result
