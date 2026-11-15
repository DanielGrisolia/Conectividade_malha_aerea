"""
Conectividade da malha aérea doméstica brasileira (VRA - ANAC).

Uso:
    python analise_malha.py --pasta dados --saida saida
    python analise_malha.py --pasta dados --tipos N C      # inclui cargueiros nacionais
    python analise_malha.py --pasta dados --hubs 60        # pares só entre os 60 maiores

Espera os CSVs mensais do VRA na pasta (ex.: VRA_20251.csv ... VRA_202512.csv).
A linha 1 do arquivo é "Atualizado em: ..." e o cabeçalho está na linha 2.

Colunas usadas:
  ICAO Aeródromo Origem/Destino -> vértices e arestas do grafo
  Situação Voo                  -> só REALIZADO vira aresta; CANCELADO entra na taxa de cancelamento
  Código Tipo Linha             -> filtro (N = nacional; ver --tipos)
  ICAO Empresa Aérea            -> nº de empresas e dependência de uma companhia por aeroporto
  Partida Prevista/Real         -> atraso mediano na partida por aeroporto
"""
import argparse
import glob
import itertools
import os
import unicodedata

import networkx as nx
import pandas as pd
from networkx.algorithms.connectivity import (build_auxiliary_node_connectivity,
                                              local_node_connectivity)
from networkx.algorithms.flow import build_residual_network, edmonds_karp

# Prefixos ICAO usados pelo Brasil
PREFIXOS_BR = ("SB", "SD", "SI", "SJ", "SN", "SS", "SW")


# ---------------------------------------------------------------- leitura ---
def normaliza(txt):
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return txt.strip().lower()


def le_csv(caminho):
    """Lê um CSV mensal do VRA: separador ';', UTF-8, linha 1 = 'Atualizado em: ...'."""
    try:
        df = pd.read_csv(caminho, sep=";", skiprows=1, encoding="utf-8-sig",
                         dtype=str, keep_default_na=False)
    except UnicodeDecodeError:
        raise SystemExit(f"{caminho}: não está em UTF-8 (tente encoding='latin-1').")
    if df.shape[1] < 12:
        raise SystemExit(f"{caminho}: formato inesperado ({df.shape[1]} colunas); "
                         "confira o separador (esperado ';').")
    return df


def acha_coluna(df, *palavras):
    for col in df.columns:
        if all(p in normaliza(col) for p in palavras):
            return col
    raise KeyError(f"Coluna com {palavras} não encontrada. Colunas: {list(df.columns)}")


def carrega_voos(pasta):
    arquivos = sorted(glob.glob(os.path.join(pasta, "*.csv")))
    if not arquivos:
        raise SystemExit(f"Nenhum CSV em {pasta}")
    partes = []
    for a in arquivos:
        df = le_csv(a)
        partes.append(pd.DataFrame({
            "empresa": df[acha_coluna(df, "empresa")].str.strip().str.upper(),
            "tipo_linha": df[acha_coluna(df, "tipo", "linha")].str.strip().str.upper(),
            "origem": df[acha_coluna(df, "origem")].str.strip().str.upper(),
            "destino": df[acha_coluna(df, "destino")].str.strip().str.upper(),
            "situacao": df[acha_coluna(df, "situacao")].str.strip().str.upper(),
            "partida_prev": pd.to_datetime(df[acha_coluna(df, "partida", "prevista")],
                                           errors="coerce"),
            "partida_real": pd.to_datetime(df[acha_coluna(df, "partida", "real")],
                                           errors="coerce"),
        }))
        print(f"  {os.path.basename(a)}: {len(df)} linhas")
    return pd.concat(partes, ignore_index=True)


def filtra_domesticos(voos, tipos):
    """Mantém etapas entre dois aeródromos brasileiros e dos tipos de linha pedidos.
    Devolve REALIZADOS e CANCELADOS (os cancelados não viram aresta, só estatística)."""
    br = voos["origem"].str.startswith(PREFIXOS_BR) & voos["destino"].str.startswith(PREFIXOS_BR)
    br &= voos["origem"] != voos["destino"]
    print("\nEtapas entre aeródromos brasileiros, por 'Código Tipo Linha':")
    print(voos[br]["tipo_linha"].value_counts().to_string())
    print("\nSituação Voo:", voos["situacao"].value_counts().to_dict())
    dom = voos[br & voos["tipo_linha"].isin(tipos)]
    print(f"\nTipos usados: {tipos} -> {len(voos)} etapas no arquivo, {len(dom)} domésticas "
          f"({(dom['situacao'] == 'REALIZADO').sum()} realizadas)")
    return dom


# ------------------------------------------------------------------ grafo ---
def monta_grafo(realizados):
    """Grafo não direcionado; peso 'voos' = nº de etapas realizadas nos dois sentidos."""
    pares = pd.Series(list(map(lambda x: tuple(sorted(x)),
                               zip(realizados["origem"], realizados["destino"]))))
    G = nx.Graph()
    for (a, b), n in pares.value_counts().items():
        G.add_edge(a, b, voos=int(n))
    return G


def metricas_operacionais(dom):
    """Estatísticas por aeroporto usando as demais colunas do VRA."""
    a = pd.concat([dom.assign(aeroporto=dom["origem"]), dom.assign(aeroporto=dom["destino"])])
    g = a.groupby("aeroporto")
    out = pd.DataFrame({
        "etapas_programadas": g.size(),
        "taxa_cancel_pct": g["situacao"].apply(lambda s: round(100 * (s == "CANCELADO").mean(), 2)),
        "n_empresas": g["empresa"].nunique(),
        "pct_empresa_dominante": g["empresa"].apply(
            lambda s: round(100 * s.value_counts(normalize=True).iloc[0], 1)),
    })
    saidas = dom[dom["situacao"] == "REALIZADO"].copy()
    saidas["atraso_min"] = (saidas["partida_real"] - saidas["partida_prev"]).dt.total_seconds() / 60
    out["atraso_mediano_partida_min"] = saidas.groupby("origem")["atraso_min"].median().round(1)
    return out.reset_index()


# ---------------------------------------------------------------- análises ---
def simula_falhas(G):
    """Remove cada aeroporto e mede o estrago."""
    total_voos = sum(d["voos"] for _, _, d in G.edges(data=True))
    n = G.number_of_nodes()
    linhas = []
    for v in G.nodes:
        voos_v = sum(d["voos"] for _, _, d in G.edges(v, data=True))
        H = G.copy()
        H.remove_node(v)
        comps = sorted(nx.connected_components(H), key=len, reverse=True)
        maior = len(comps[0]) if comps else 0
        pares_perdidos = (n - 1) * (n - 2) // 2 - sum(len(c) * (len(c) - 1) // 2 for c in comps)
        linhas.append({
            "aeroporto": v,
            "grau": G.degree(v),
            "voos": voos_v,
            "pct_voos_malha": round(100 * voos_v / total_voos, 2),
            "ponto_articulacao": (n - 1) - maior > 0,
            "aeroportos_isolados": (n - 1) - maior,
            "pares_sem_rota": pares_perdidos,
        })
    return pd.DataFrame(linhas).sort_values(
        ["pares_sem_rota", "voos"], ascending=False, ignore_index=True)


def conectividade_pares(G, hubs=None):
    """kappa(s,t) (Menger, vértices) vs. limite pelo grau, só para nós NÃO adjacentes."""
    nos = list(G.nodes)
    if hubs:
        nos = sorted(nos, key=G.degree, reverse=True)[:hubs]
    H = build_auxiliary_node_connectivity(G)          # construído uma vez só
    R = build_residual_network(H, "capacity")
    mapping = H.graph["mapping"]
    linhas = []
    for s, t in itertools.combinations(nos, 2):
        if G.has_edge(s, t):
            continue
        k = local_node_connectivity(G, s, t, auxiliary=H, residual=R)
        lim = min(G.degree(s), G.degree(t))
        linhas.append({"s": s, "t": t, "kappa_st": k, "limite_grau": lim,
                       "atinge_limite": k == lim})
    return pd.DataFrame(linhas)


def vazao_max(G, s, t):
    """Fluxo máximo com capacidade = nº de voos (Edmonds-Karp)."""
    return nx.maximum_flow_value(G, s, t, capacity="voos", flow_func=edmonds_karp)


# -------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta", default="dados")
    ap.add_argument("--saida", default="saida")
    ap.add_argument("--tipos", nargs="+", default=["N"],
                    help="códigos de 'Código Tipo Linha' a incluir (padrão: N)")
    ap.add_argument("--hubs", type=int, default=None,
                    help="limita a análise de pares aos N aeroportos de maior grau")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    os.makedirs(a.saida, exist_ok=True)

    print("Lendo CSVs:")
    dom = filtra_domesticos(carrega_voos(a.pasta), [t.upper() for t in a.tipos])
    G = monta_grafo(dom[dom["situacao"] == "REALIZADO"])

    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    print(f"\nGrafo: {G.number_of_nodes()} aeroportos, {G.number_of_edges()} rotas, "
          f"{len(comps)} componente(s)")
    if len(comps) > 1:
        print("  Componentes menores (fora da rede principal):",
              [sorted(c) for c in comps[1:]])
    G = G.subgraph(comps[0]).copy()  # análise na maior componente

    graus = [d for _, d in G.degree()]
    print(f"\nκ(G) = {nx.node_connectivity(G)}   λ(G) = {nx.edge_connectivity(G)}   "
          f"δ(G) = {min(graus)}   (Whitney: κ ≤ λ ≤ δ)")
    print("Pontos de articulação:", sorted(nx.articulation_points(G)))

    print("\nSimulando a falha de cada aeroporto...")
    crit = simula_falhas(G).merge(metricas_operacionais(dom), on="aeroporto", how="left")
    crit.to_csv(os.path.join(a.saida, "criticidade_aeroportos.csv"), index=False)
    print(crit.head(a.top).to_string(index=False))

    print("\nConectividade por pares (Menger, vértices)...")
    pares = conectividade_pares(G, a.hubs)
    pares.to_csv(os.path.join(a.saida, "pares_conectividade.csv"), index=False)
    print(f"  {len(pares)} pares não adjacentes; "
          f"{100 * pares['atinge_limite'].mean():.1f}% atingem o limite pelo grau")
    print(pares.groupby("kappa_st").size().rename("pares").to_string())
    frageis = pares.sort_values(["kappa_st", "limite_grau"]).head(a.top)

    print("\nGargalos (corte mínimo de vértices) de alguns pares com κ(s,t) baixo "
          "e limite pelo grau alto (rede ABAIXO do limite):")
    abaixo = pares[~pares["atinge_limite"]].sort_values(["kappa_st", "limite_grau"],
                                                        ascending=[True, False]).head(5)
    for _, r in abaixo.iterrows():
        print(f"  {r['s']} - {r['t']}: κ={r['kappa_st']} (limite {r['limite_grau']}), "
              f"corte {sorted(nx.minimum_node_cut(G, r['s'], r['t']))}")

    print("\nVazão máxima (capacidade = nº de voos) entre os maiores hubs:")
    top_hubs = sorted(G.nodes, key=G.degree, reverse=True)[:5]
    for s, t in itertools.combinations(top_hubs, 2):
        print(f"  {s} -> {t}: {vazao_max(G, s, t)} voos")


if __name__ == "__main__":
    main()
