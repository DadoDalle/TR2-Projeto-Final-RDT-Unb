import argparse
import csv
import os
try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Aviso: 'matplotlib' não instalado. Os gráficos não serão gerados.")
    plt = None

from cliente import PASTA_PROJETO, PASTA_RESULTADOS, ARQUIVO_RESUMO, nome_cenario, caminho_relativo

# Saídas da comparação: resultados/<arquivo>/comparacao/
CENARIOS = [("saw", 1), ("gbn", 4), ("gbn", 8), ("gbn", 16), ("sr", 4), ("sr", 8), ("sr", 16)]
PERDAS = [0.0, 0.05, 0.10]

def pasta_comparacao(arquivo):
    pasta = os.path.join(PASTA_RESULTADOS, arquivo, "comparacao")
    os.makedirs(pasta, exist_ok=True)
    return pasta

def ler_resumo(arquivo):
    # Para cada combinação protocolo x janela x perda, guarda a execução mais recente
    resultados = {}
    with open(ARQUIVO_RESUMO, newline="") as f:
        for linha in csv.DictReader(f):
            if linha["arquivo"] != arquivo or linha["md5_ok"] != "1":
                continue
            chave = (linha["protocol"], int(linha["window_size"]), round(float(linha["perda"]), 2))
            resultados[chave] = linha
    return resultados

def gerar_tabela(resultados, arquivo):
    cabecalho = "| Protocolo | Janela | " + " | ".join(f"{p*100:.0f}% perda" for p in PERDAS) + " |"
    separador = "|---|---|" + "---|" * len(PERDAS)
    linhas = [f"Arquivo: {arquivo} — cada célula: throughput efetivo (kbps) / retransmissões / tempo total (s)", "",
              cabecalho, separador]

    for protocol, janela in CENARIOS:
        celulas = []
        for perda in PERDAS:
            r = resultados.get((protocol, janela, perda))
            if r:
                celulas.append(f"{float(r['throughput_efetivo_kbps']):.1f} / {r['retransmissoes']} / {float(r['tempo_total_s']):.1f}")
            else:
                celulas.append("—")
        linhas.append(f"| {protocol.upper()} | {janela} | " + " | ".join(celulas) + " |")

    # Retransmissões por erro (timeout): mostra quantos REQs cada protocolo reenvia a cada perda
    linhas += ["", "| Protocolo | Janela | Perda | Timeouts | Retransmissões | Retransmissões por timeout |", "|---|---|---|---|---|---|"]
    for protocol, janela in CENARIOS:
        for perda in PERDAS[1:]:
            r = resultados.get((protocol, janela, perda))
            if r and int(r["timeouts"]) > 0:
                razao = int(r["retransmissoes"]) / int(r["timeouts"])
                linhas.append(f"| {protocol.upper()} | {janela} | {perda*100:.0f}% | {r['timeouts']} | {r['retransmissoes']} | {razao:.2f} |")

    texto = "\n".join(linhas)
    nome = os.path.join(pasta_comparacao(arquivo), "tabela.md")
    with open(nome, "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print(texto)
    print(f"\nTabela salva em '{caminho_relativo(nome)}'.")

def ler_metricas(nome_csv):
    with open(nome_csv, newline="") as f:
        return list(csv.DictReader(f))

def media_movel(valores, n):
    saida = []
    soma = 0.0
    for i, v in enumerate(valores):
        soma += v
        if i >= n:
            soma -= valores[i - n]
        saida.append(soma / min(i + 1, n))
    return saida

def grafico_gbn_vs_sr(resultados, arquivo, janela, perda):
    if not plt:
        return
    gbn = resultados.get(("gbn", janela, perda))
    sr = resultados.get(("sr", janela, perda))
    if not gbn or not sr:
        print(f"Faltam execuções de GBN e/ou SR com janela {janela} e {perda*100:.0f}% de perda para o gráfico.")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for linha, cor in ((gbn, "tab:red"), (sr, "tab:blue")):
        caminho_csv = os.path.join(PASTA_PROJETO, linha["csv"])
        metricas = ler_metricas(caminho_csv) if os.path.exists(caminho_csv) else None
        if metricas is None:
            print(f"CSV '{linha['csv']}' não encontrado.")
            return
        seqs = [int(m["segment"]) for m in metricas]
        thrs = [float(m["throughput_kbps"]) for m in metricas]
        acumulado = []
        total = 0
        for m in metricas:
            total += int(m["retransmissions"])
            acumulado.append(total)
        rotulo = linha["protocol"].upper()
        ax1.plot(seqs, media_movel(thrs, 50), color=cor, linewidth=1, label=f"{rotulo} (média móvel 50 seg.)")
        ax2.plot(seqs, acumulado, color=cor, linewidth=1.5, label=f"{rotulo} (total {total})")

    ax1.set_title(f"GBN vs SR — janela {janela}, perda {perda*100:.0f}% ({arquivo})")
    ax1.set_ylabel("Throughput (kbps)")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend()
    ax2.set_xlabel("Número do Segmento")
    ax2.set_ylabel("Retransmissões acumuladas")
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend()

    fig.tight_layout()
    # Ex: gbn_vs_sr_w16_p10.png (mesmo padrão de janela/perda das pastas de cenário)
    sufixo = nome_cenario("gbn", janela, perda)[len("gbn_"):]
    nome = os.path.join(pasta_comparacao(arquivo), f"gbn_vs_sr_{sufixo}.png")
    plt.savefig(nome)
    plt.close(fig)
    print(f"Gráfico salvo em '{caminho_relativo(nome)}'.")

def grafico_janela(resultados, arquivo):
    # Throughput efetivo sem perda em função do tamanho da janela (análise a)
    if not plt:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    for protocol, cor in (("gbn", "tab:red"), ("sr", "tab:blue")):
        pontos = [(1, resultados.get(("saw", 1, 0.0)))] + [(n, resultados.get((protocol, n, 0.0))) for n in (4, 8, 16)]
        pontos = [(n, float(r["throughput_efetivo_kbps"])) for n, r in pontos if r]
        if pontos:
            ax.plot([p[0] for p in pontos], [p[1] for p in pontos], marker="o", color=cor, label=protocol.upper())
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 4, 8, 16])
    ax.set_xticklabels(["1 (SAW)", "4", "8", "16"])
    ax.set_xlabel("Tamanho da janela")
    ax.set_ylabel("Throughput efetivo (kbps)")
    ax.set_title(f"Impacto da janela sem perda ({arquivo})")
    ax.grid(True, linestyle="--", alpha=0.6)
    ax.legend()
    fig.tight_layout()
    nome = os.path.join(pasta_comparacao(arquivo), "throughput_por_janela.png")
    plt.savefig(nome)
    plt.close(fig)
    print(f"Gráfico salvo em '{caminho_relativo(nome)}'.")

def main():
    parser = argparse.ArgumentParser(description="Tabela comparativa e gráficos da Entrega 2")
    parser.add_argument("--file", default="small", help="Arquivo usado nos testes (small, medium, large)")
    parser.add_argument("--window", type=int, default=16, help="Janela do gráfico GBN vs SR (padrão: 16)")
    parser.add_argument("--loss", type=float, default=0.10, help="Perda do gráfico GBN vs SR (padrão: 0.10)")
    args = parser.parse_args()

    if not os.path.exists(ARQUIVO_RESUMO):
        print(f"'{caminho_relativo(ARQUIVO_RESUMO)}' não encontrado. Rode o cliente.py antes.")
        return

    resultados = ler_resumo(args.file)
    gerar_tabela(resultados, args.file)
    grafico_gbn_vs_sr(resultados, args.file, args.window, round(args.loss, 2))
    grafico_janela(resultados, args.file)

if __name__ == "__main__":
    main()
