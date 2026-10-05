"""Views of sampled criterion values. Interpolation is explicitly optional."""
import numpy as np
import plotly.graph_objects as go


def frontier_charts(result):
    points, criteria = result['points'], result['criteria']
    values = np.asarray([point['values'] for point in points])
    labels = [c['name'] + (' ↓' if c['sense'] == 'minimize' else ' ↑') for c in criteria]
    ids = [p['id'] for p in points]
    charts = []
    def add(key, title, figure):
        figure.update_layout(title=title, template='plotly_white', height=480,
                             margin=dict(l=55, r=25, t=65, b=55))
        charts.append({'key': key, 'figure': figure.to_plotly_json()})
    if len(criteria) == 2:
        order = np.argsort(values[:, 0])
        figure = go.Figure(go.Scatter(x=values[order, 0].tolist(), y=values[order, 1].tolist(),
            mode='lines+markers', line={'dash':'dot','width':1}, customdata=[ids[i] for i in order], name='Verified samples', marker={'size': 9},
            hovertemplate='%{x:.6g}, %{y:.6g}<extra>Click to inspect</extra>'))
        low, high = values.min(axis=0), values.max(axis=0)
        padding = np.maximum(high-low, np.maximum(1e-9, np.abs(low)*.05))*.1
        low, high = low-padding, high+padding
        for value in values:
            bounds = [(float(value[i]), float(high[i])) if c['sense'] == 'minimize'
                      else (float(low[i]), float(value[i])) for i,c in enumerate(criteria)]
            figure.add_shape(type='rect', x0=bounds[0][0], x1=bounds[0][1], y0=bounds[1][0], y1=bounds[1][1],
                             fillcolor='rgba(150,150,150,0.10)', line_width=0, layer='below')
        figure.update_layout(xaxis={'title': labels[0], 'range': low[[0]].tolist()+high[[0]].tolist()},
                             yaxis={'title': labels[1], 'range': low[[1]].tolist()+high[[1]].tolist()})
        add('frontier-2d', 'Pareto samples', figure)
    else:
        marker = {'size': 6}
        if len(criteria) > 3:
            marker.update(color=values[:, 3].tolist(), colorscale='Viridis', showscale=True,
                          colorbar={'title': criteria[3]['name']})
        figure = go.Figure(go.Scatter3d(x=values[:, 0].tolist(), y=values[:, 1].tolist(), z=values[:, 2].tolist(),
            customdata=ids, mode='markers', marker=marker, name='Verified samples'))
        if len(criteria) == 3 and len(points) >= 3 and np.linalg.matrix_rank(values[:, :2]-values[0, :2]) == 2:
            figure.add_trace(go.Mesh3d(x=values[:, 0].tolist(), y=values[:, 1].tolist(), z=values[:, 2].tolist(),
                alphahull=-1, opacity=.2, color='steelblue', visible='legendonly', hoverinfo='skip',
                name='Interpolation (not solved)', showlegend=True))
        figure.update_layout(legend={'orientation':'h', 'x':0, 'y':-.12}, scene={'xaxis_title': labels[0], 'yaxis_title': labels[1], 'zaxis_title': labels[2]})
        add('frontier-3d', 'Pareto samples in 3D', figure)
        if len(criteria) > 3:
            dimensions = [dict(label=labels[i], values=values[:, i].tolist()) for i in range(len(criteria))]
            add('parallel', 'Parallel coordinates', go.Figure(go.Parcoords(
                dimensions=dimensions, line={'color': values[:, 0].tolist(), 'colorscale': 'Viridis'})))
            add('pairwise', 'Criterion projections', go.Figure(go.Splom(
                dimensions=dimensions, customdata=ids, marker={'size': 6}, diagonal_visible=False,
                showupperhalf=False)))
    return charts
