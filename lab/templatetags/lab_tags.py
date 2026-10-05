import json
from django import template
register = template.Library()


@register.filter
def json_display(value):
    return 'Unavailable' if value is None else json.dumps(value, indent=2, allow_nan=False)


@register.filter
def number_display(value):
    return "Unavailable" if value is None else format(float(value), ".8g")


@register.filter
def short_json(value):
    return len(json.dumps(value, default=str)) <= 400


@register.filter
def report_cell(value):
    if value is None: return "Unavailable"
    if type(value) in (float,int): return number_display(value)
    if isinstance(value,(dict,list)): return json.dumps(value,indent=2,allow_nan=False)
    return str(value)


@register.filter
def numeric_display(value):
    """Readable numeric arrays; unrounded solver values remain in the snapshot."""
    def format_value(item, depth=0):
        if isinstance(item, list):
            return "[\n" + ",\n".join("  " * (depth+1) + format_value(x, depth+1) for x in item) + "\n" + "  " * depth + "]"
        return number_display(item)
    return format_value(value)
