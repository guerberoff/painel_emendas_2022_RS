#!/usr/bin/env python
# coding: utf-8

import pandas as pd
import geopandas as gpd
import unicodedata
from dash import Dash, dcc, html, Input, Output
import plotly.express as px

# --- FUNÇÃO AUXILIAR ANTIBOMBA ---
# Remove acentos e padroniza os nomes (incluindo apóstrofos e hífens) para evitar erros de casamento
def tirar_acentos(texto):
    if pd.isna(texto):
        return texto
    texto = str(texto)
    # Remove acentos
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    # Remove apóstrofos retos, curvos e substitui hífens por espaços
    texto = texto.replace("'", "").replace("’", "").replace("-", " ")
    return texto.upper().strip()

# --- CARREGAMENTO E TRATAMENTO DOS DADOS LEVES ---

# 1. Processando o arquivo de Emendas (Leve)
df_emendas = pd.read_csv('emendas 2022.csv', sep=';', encoding='utf-8-sig')
emendas_uteis = df_emendas[['Autor da emenda', 'Localidade do gasto (Regionalização)', 'Valor pago']].copy()

# Limpeza e conversão da coluna de valores monetários
emendas_uteis['Valor pago'] = (
    emendas_uteis['Valor pago']
    .astype(str)
    .str.replace('R$', '', regex=False)
    .str.replace("'", "", regex=False)
    .str.replace(' ', '', regex=False)
    .str.replace('.', '', regex=False)
    .str.replace(',', '.', regex=False)
    .astype(float)
)

# Padronizando nomes de políticos e municípios nas emendas
emendas_uteis['CANDIDATO'] = emendas_uteis['Autor da emenda'].str.split(' - ').str[-1].apply(tirar_acentos)
emendas_uteis['MUNICIPIO'] = emendas_uteis['Localidade do gasto (Regionalização)'].str.split(' - ').str[0].apply(tirar_acentos)

# Agrupando valores enviados por deputado para cada município
emendas_agrupadas = emendas_uteis.groupby(['CANDIDATO', 'MUNICIPIO'])['Valor pago'].sum().reset_index()

# 2. Carregando o arquivo de Votos Otimizado (Gerado com 27 MB)
df_votos_limpo = pd.read_csv('votacao_candidato_limpo.csv')
df_votos_limpo['CANDIDATO'] = df_votos_limpo['CANDIDATO'].apply(tirar_acentos)
df_votos_limpo['MUNICIPIO'] = df_votos_limpo['MUNICIPIO_UPPER'].apply(tirar_acentos)

# Agrupando votos do candidato por município
votos_agrupados = df_votos_limpo.groupby(['CANDIDATO', 'MUNICIPIO'])['QT_VOTOS_NOMINAIS'].sum().reset_index()

# 3. Cruzamento Final (Merge)
dados_finais = pd.merge(votos_agrupados, emendas_agrupadas, on=['CANDIDATO', 'MUNICIPIO'], how='inner')

# Mantendo apenas registros com relevância eleitoral mínima para estabilidade do painel
df_final_filtrado = dados_finais[dados_finais['QT_VOTOS_NOMINAIS'] >= 1000].copy()
df_final_filtrado['MUNICIPIO_UPPER'] = df_final_filtrado['MUNICIPIO'].str.upper()

# 4. Carregando o arquivo Geográfico (Mapas)
gdf = gpd.read_file('municipios_rs.geojson')
gdf['name_upper'] = gdf['name'].apply(tirar_acentos)


# --- INICIALIZAÇÃO DO DASH ---
app = Dash(__name__)
server = app.server  # Linha vital para o funcionamento no Render


# --- LAYOUT DO PAINEL ---
app.layout = html.Div([
    html.H1("Painel de Controle: Emendas e Votação por Município", 
            style={'textAlign': 'center', 'fontFamily': 'sans-serif', 'padding': '10px'}),
    
    html.Div([
        html.Label("Selecione o Candidato:", style={'fontWeight': 'bold', 'fontSize': '16px'}),
        dcc.Dropdown(
            id='dropdown-candidato',
            options=[{'label': i, 'value': i} for i in sorted(df_final_filtrado['CANDIDATO'].unique())],
            value=sorted(df_final_filtrado['CANDIDATO'].unique())[0] if len(df_final_filtrado) > 0 else None,
            style={'width': '50%', 'marginTop': '8px'}
        ),
    ], style={'margin': '20px'}),
    
    dcc.Graph(id='mapa-interativo', style={'height': '80vh'})
])


# --- LÓGICA INTERATIVA (CALLBACK) ---
@app.callback(
    Output('mapa-interativo', 'figure'),
    Input('dropdown-candidato', 'value')
)
def update_map(selected_candidato):
    if not selected_candidato:
        return px.choropleth(title="Nenhum candidato selecionado.")

    # Filtrando dados do candidato escolhido no menu
    df_candidato = df_final_filtrado[df_final_filtrado['CANDIDATO'] == selected_candidato].copy()

    # Unindo os dados políticos com o mapa geográfico do RS
    gdf_plot = gdf.merge(df_candidato, left_on='name_upper', right_on='MUNICIPIO_UPPER', how='left')

    # Preenchendo locais sem dados com zero para não quebrar o mapa visualmente
    gdf_plot['Valor pago'] = gdf_plot['Valor pago'].fillna(0)
    gdf_plot['QT_VOTOS_NOMINAIS'] = gdf_plot['QT_VOTOS_NOMINAIS'].fillna(0)

    # Construindo o mapa coroplético
    fig = px.choropleth(
        gdf_plot,
        geojson=gdf_plot.geometry, 
        locations=gdf_plot.index,
        color='Valor pago',
        hover_name='name',
        custom_data=['Valor pago', 'QT_VOTOS_NOMINAIS'], 
        color_continuous_scale="YlOrRd", 
        range_color=[0, max(1, gdf_plot['Valor pago'].max())],
        title=f"Distribuição de Emendas e Votos: {selected_candidato}"
    )

    # Formatando a caixinha de informações que aparece ao passar o mouse (Hover)
    fig.update_traces(
        hovertemplate="<b>%{hovertext}</b><br>Valor das Emendas: R$ %{customdata[0]:,.2f}<br>Votos Conquistados: %{customdata[1]:,.0f}<extra></extra>",
        marker_line_width=0.5,
        marker_line_color='white'
    )

    # Ajustes finais de câmera e enquadramento geográfico das coordenadas do RS
    fig.update_geos(
        fitbounds="locations", 
        visible=False
    )

    fig.update_layout(
        margin={"r":0,"t":50,"l":0,"b":0},
        geo=dict(bgcolor='white', showland=True, landcolor='#f0f0f0', showframe=False)
    )

    return fig


# --- EXECUÇÃO EM MODO LOCAL ---
if __name__ == '__main__':
    app.run(debug=True)