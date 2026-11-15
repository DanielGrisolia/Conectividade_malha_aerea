# Conectividade da malha aérea doméstica brasileira

Aplicação prática do trabalho **"Conectividade e Fluxos em Redes: do Teorema de Menger ao
Algoritmo de Edmonds-Karp"** (Matemática Discreta, Projeto A2).

Modelamos a malha aérea doméstica como um grafo (aeroportos = vértices, rotas com voos
realizados = arestas) e perguntamos: **quais aeroportos são essenciais para a conectividade?**
Isto é, o que acontece com a rede se um aeroporto parar.

Integrantes: _(preencher)_

## Estrutura

```
analise_malha.py   # script da análise
requirements.txt   # dependências (networkx, pandas)
dados/             # CSVs mensais do VRA (ANAC), um por mês
saida/             # resultados gerados pelo script
```

## Como rodar

```bash
pip install -r requirements.txt
python analise_malha.py --pasta dados --saida saida
```

Opções úteis:

| Opção | Efeito |
|---|---|
| `--tipos N C` | inclui também linhas cargueiras nacionais (padrão: só `N`) |
| `--hubs 60` | limita a análise de pares aos 60 aeroportos de maior grau |
| `--top 20` | quantas linhas mostrar nos rankings |

Testado com Python 3.12, networkx 3.7 e pandas 3.0.

## Dados

Fonte: **ANAC, Histórico de Voos (VRA)** —
https://www.gov.br/anac/pt-br/assuntos/dados-e-estatisticas/historico-de-voos

Um CSV por mês, separador `;`, UTF-8, com a linha 1 `Atualizado em: ...` e o cabeçalho na
linha 2. **Não reabra e salve os CSVs no Excel**: isso altera o formato e quebra a leitura.

## Metodologia

- Só entram etapas **REALIZADAS** entre dois aeródromos brasileiros (prefixos ICAO SB, SD, SI,
  SJ, SN, SS, SW) e do tipo de linha escolhido (`Código Tipo Linha`). Etapas com origem igual ao
  destino são descartadas.
- O grafo é **não direcionado**: uma aresta por par de aeroportos, com peso = número de voos
  nos dois sentidos.
- Análises: κ(G), λ(G) e δ(G); pontos de articulação; simulação da falha de cada aeroporto;
  conectividade κ(s,t) entre pares não adjacentes (versão por vértices do Teorema de Menger)
  comparada ao limite min(grau(s), grau(t)); cortes mínimos dos pares abaixo do limite; vazão
  máxima entre os maiores hubs com Edmonds-Karp (capacidade = número de voos).
- Para cada aeroporto também são calculados, a partir das demais colunas do VRA: taxa de
  cancelamento, número de empresas, participação da empresa dominante e atraso mediano na
  partida.

## Limitações

- A rede é estática: não considera horários, conexões viáveis nem a capacidade real das
  aeronaves. Conectividade mede só a estrutura das rotas.
- Na vazão máxima, a capacidade de cada rota soma os voos dos dois sentidos (simplificação).
- Os resultados dependem do período escolhido (rotas sazonais).
