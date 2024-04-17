import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objs as go
import networkx as nx
import requests
from math import sqrt, log
import pandas as pd

# Initialize the Dash app
app = dash.Dash(__name__)

# Define the layout of the app
app.layout = html.Div([
    html.H1("Ethereum and ERC20 Transaction Visualizer"),
    html.Label("Ethereum Address:"),
    dcc.Input(id='eth-address', type='text', value='', style={'width': '30%'}),
    html.Br(),
    html.Label("API Key:"),
    dcc.Input(id='api-key', type='text', value='', style={'width': '30%'}),
    html.Br(),
    html.Label("Hide Zero Value Transactions:"),
    dcc.Checklist(id='hide-zero-txns',
                  options=[
                      {'label': ' Hide', 'value': 'hide'}
                  ],
                  value=[],
                  inline=True),
    html.Button('Generate Graphs', id='generate-graph', n_clicks=0),
    html.Div(id='eth-graph-container'),
    html.Div(id='erc20-graph-container'),
    html.Div(id='time-series-chart-container')
])

# Define callback to update graph
@app.callback(
    [Output('eth-graph-container', 'children'),
    Output('erc20-graph-container', 'children'),
    Output('time-series-chart-container', 'children')],
    [Input('generate-graph', 'n_clicks')],
    [State('eth-address', 'value'), State('api-key', 'value'), State('hide-zero-txns', 'value')]
)
def update_graphs(n_clicks, address, api_key, hide_zero):
    if n_clicks > 0:
        transactions, erc20_transactions = fetch_transactions(address, api_key)
        if 'hide' in hide_zero:
            transactions = transactions[transactions['value'] != '0']
            erc20_transactions = erc20_transactions[erc20_transactions['value'] != '0']
        
        if transactions.empty and erc20_transactions.empty:
            return html.Div("No data available for Ethereum transactions"), html.Div("No data available for ERC20 transactions")
        elif transactions.empty:
            eth_graph_div = html.Div("No data available for Ethereum transactions")
        else:
            eth_graph = create_network_graph(transactions)
            eth_graph_div = dcc.Graph(figure=draw_plotly_graph(eth_graph, False, center_node=address))
        
        if erc20_transactions.empty:
            erc20_graph_div = html.Div("No data available for ERC20 transactions")
        else:
            erc20_graph = create_network_graph(erc20_transactions, token=True)
            erc20_graph_div = dcc.Graph(figure=draw_plotly_graph(erc20_graph, True, center_node=address))

        # Create time series data
        transactions['time'] = pd.to_datetime(transactions['timeStamp'], unit='s')
        # Ensure the value is in ether
        transactions['value'] = transactions['value'].astype(float) / 10**18
        time_series_data = transactions.groupby('time')['value'].sum().cumsum()

        # Create time series plot
        time_series_fig = go.Figure([go.Scatter(x=time_series_data.index, y=time_series_data)])
        time_series_fig.update_layout(
            title='Cumulative Transaction Value Over Time',
            xaxis_title='Time',
            yaxis_title='Cumulative Value (in Ether)',
            yaxis=dict(type='linear', ticksuffix=' ETH')  # Specify ticksuffix for clarity
        )

        time_series_div = dcc.Graph(figure=time_series_fig)

        return eth_graph_div, erc20_graph_div, time_series_div

    return html.Div(), html.Div(), html.Div()

def fetch_transactions(address, api_key):
    eth_url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&startblock=0&endblock=99999999&sort=asc&apikey={api_key}"
    erc20_url = f"https://api.etherscan.io/api?module=account&action=tokentx&address={address}&startblock=0&endblock=99999999&sort=asc&apikey={api_key}"

    try:
        eth_response = requests.get(eth_url)
        if eth_response.status_code == 200:
            eth_transactions = pd.DataFrame(eth_response.json().get('result', []))
        else:
            print(f"Failed to fetch Ethereum transactions: {eth_response.status_code}")
            eth_transactions = pd.DataFrame()

        erc20_response = requests.get(erc20_url)
        if erc20_response.status_code == 200:
            erc20_transactions = pd.DataFrame(erc20_response.json().get('result', []))
            # Ensure 'tokenDecimal' field is converted to integer
            erc20_transactions['tokenDecimal'] = erc20_transactions['tokenDecimal'].astype(int)
        else:
            print(f"Failed to fetch ERC20 transactions: {erc20_response.status_code}")
            erc20_transactions = pd.DataFrame()

    except Exception as e:
        print(f"An error occurred: {e}")
        eth_transactions = pd.DataFrame()
        erc20_transactions = pd.DataFrame()

    return eth_transactions, erc20_transactions

def create_network_graph(transactions, token=False):
    G = nx.Graph()
    for _, tx in transactions.iterrows():
        value = float(tx['value']) / (10 ** int(tx['tokenDecimal'])) if token else float(tx['value']) / 10**18
        if value > 0:
            G.add_edge(tx['from'], tx['to'], weight=value)
        else:
            print("Filtered out transaction with adjusted value 0 or negative")
    if not nx.number_of_nodes(G):
        print("No nodes in the graph. Please check transaction data and filters.")
    return G

def draw_plotly_graph(G, is_token, center_node=None):
    # Adjust layout settings to increase spacing
    pos = nx.kamada_kawai_layout(G, scale=2)

    edge_x = []
    edge_y = []
    edge_annotations = []

    for edge in G.edges(data=True):
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
        # Label edges with transaction value
        midpoint_x = (x0 + x1) / 2
        midpoint_y = (y0 + y1) / 2
        edge_annotations.append({
            'x': midpoint_x,
            'y': midpoint_y,
            'xref': "x",
            'yref': "y",
            'text': f"{edge[2]['weight']:.4f} {'ETH' if not is_token else 'TOKENS'}",
            'showarrow': False,
            'font': {'size': 10}
        })

    edge_trace = go.Scatter(x=edge_x, y=edge_y, line={'width': 0.5, 'color': '#888'}, hoverinfo='none', mode='lines')
    node_x = []
    node_y = []
    node_text = []
    node_sizes = []

    # Adjust sizes to avoid overly large nodes
    max_size = 25  # Maximum size for any node
    base_size = 10  # Base size for other nodes
    center_size = 15  # Fixed size for the center node
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)
        if node == center_node:
            node_sizes.append(center_size)
        else:
            node_degree = nx.degree(G, node)
            # Use a logarithmic scale for degree size adjustment, capped at max_size
            node_sizes.append(min(base_size + log(node_degree+1), max_size))

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode='markers+text', hoverinfo='text', text=node_text, textposition="top center",
        marker={'showscale': True, 'colorscale': 'YlGnBu', 'size': node_sizes, 'color': [], 'colorbar': {'thickness': 15, 'title': 'Node Connections', 'xanchor': 'left', 'titleside': 'right'}}
    )

    fig = go.Figure(data=[edge_trace, node_trace], layout=go.Layout(
        title='<b>Transaction Network</b>', titlefont_size=16, showlegend=False, hovermode='closest',
        margin={'b': 20, 'l': 5, 'r': 5, 't': 40},
        xaxis={'showgrid': False, 'zeroline': False, 'showticklabels': False},
        yaxis={'showgrid': False, 'zeroline': False, 'showticklabels': False},
        annotations=edge_annotations
    ))
    return fig

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)
