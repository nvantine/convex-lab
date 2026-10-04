from django import forms
from core.solve import SOLVERS


class ProblemForm(forms.Form):
    name = forms.CharField(max_length=120, label="Problem name")
    variables = forms.JSONField(widget=forms.Textarea(attrs={"rows": 7}), help_text="Shapes: [] scalar, [n] vector, [rows, columns] matrix.")
    parameters = forms.JSONField(required=False, widget=forms.Textarea(attrs={"rows": 9}), help_text="Named constants with numeric values. Domains certify signs and positive semidefiniteness.")
    sense = forms.ChoiceField(choices=[("minimize", "Minimize"), ("maximize", "Maximize")], label="Objective direction")
    expression = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), label="Objective expression", max_length=20000)
    constraints = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 6}), label="Constraints", help_text="One <=, >=, or == comparison per line.")
    solver = forms.ChoiceField(choices=[(s, s) for s in SOLVERS], initial="CLARABEL")

    def specification(self):
        data = self.cleaned_data
        return {"version": 1, "variables": data["variables"], "parameters": [] if data["parameters"] is None else data["parameters"],
                "objective": {"sense": data["sense"], "expression": data["expression"]},
                "constraints": [line.strip() for line in data["constraints"].splitlines() if line.strip()]}


def initial_from_spec(name, spec):
    return {"name": name, "variables": spec["variables"],
            "parameters": spec["parameters"],
            "sense": spec["objective"]["sense"], "expression": spec["objective"]["expression"],
            "constraints": "\n".join(spec["constraints"]), "solver": "CLARABEL"}
