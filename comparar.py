import argparse
import csv
import os
try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Aviso: 'matplotlib' não instalado. Os gráficos não serão gerados.")
    plt = None

from cliente import (PASTA_PROJETO, PASTA_RESULTADOS, ARQUIVO_RESUMO, ALPHA_PADRAO, BETA_PADRAO,
                     TIMEOUT_MIN_PADRAO, nome_cenario, caminho_relativo, saida_utf8)

# Saídas da comparação: resultados/<arquivo>/comparacao/
CENARIOS = [("saw", 1), ("gbn", 4), ("gbn", 8), ("gbn", 16), ("sr", 4), ("sr", 8), ("sr", 16)]
PERDAS = [0.0, 0.05, 0.10]

# Grade de α, β e piso do timeout testada na análise offline (replay) do estimador
ALPHAS = [0.05, 0.125, 0.25, 0.5]
BETAS = [0.125, 0.25, 0.5]
PISOS_MS = [0, 30, 40, 50, 60, 80, 100]

# ---------------------------------------------------------------------------
# Leitura dos resultados
# ---------------------------------------------------------------------------

def pasta_comparacao(arquivo):
    pasta = os.path.join(PASTA_RESULTADOS, arquivo, "comparacao")
    os.makedirs(pasta, exist_ok=True)
    return pasta

def ler_resumo(arquivo):
    # Execuções do arquivo pedido com MD5 OK, na ordem em que foram feitas.
    # Linhas da Entrega 2 não têm timeout_modo/alpha/beta: eram timeout fixo.
    execucoes = []
    with open(ARQUIVO_RESUMO, newline="") as f:
        for linha in csv.DictReader(f):
            if linha["arquivo"] != arquivo or linha["md5_ok"] != "1":
                continue
            linha["timeout_modo"] = linha.get("timeout_modo") or "fixo"
            linha["window_size"] = int(linha["window_size"])
            linha["perda"] = round(float(linha["perda"]), 2)
            linha["alpha"] = float(linha.get("alpha") or ALPHA_PADRAO)
            linha["beta"] = float(linha.get("beta") or BETA_PADRAO)
            linha["timeout_min"] = float(linha.get("timeout_min_ms") or 0) / 1000
            execucoes.append(linha)
    return execucoes

def ultima(execucoes, protocol, janela, perda, modo="fixo", alpha=None, beta=None, timeout_min=None):
    # Execução mais recente de um cenário (α, β e piso só importam no modo adaptativo)
    escolhida = None
    for r in execucoes:
        if (r["protocol"], r["window_size"], r["perda"], r["timeout_modo"]) != (protocol, janela, perda, modo):
            continue
        if modo == "adaptativo" and any(abs(r[campo] - valor) > 1e-9 for campo, valor in
                                        (("alpha", alpha), ("beta", beta), ("timeout_min", timeout_min))):
            continue
        escolhida = r
    return escolhida

def ler_metricas(caminho_csv):
    with open(os.path.join(PASTA_PROJETO, caminho_csv), newline="") as f:
        return list(csv.DictReader(f))

def salvar_texto(arquivo, nome, texto):
    caminho = os.path.join(pasta_comparacao(arquivo), nome)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print(texto)
    print(f"\nTabela salva em '{caminho_relativo(caminho)}'.")

def salvar_figura(fig, arquivo, nome):
    caminho = os.path.join(pasta_comparacao(arquivo), nome)
    fig.tight_layout()
    fig.savefig(caminho)
    plt.close(fig)
    print(f"Gráfico salvo em '{caminho_relativo(caminho)}'.")

def celula(r, formato):
    return formato(r) if r else "—"

def media_movel(valores, n):
    saida = []
    soma = 0.0
    for i, v in enumerate(valores):
        soma += v
        if i >= n:
            soma -= valores[i - n]
        saida.append(soma / min(i + 1, n))
    return saida

# ---------------------------------------------------------------------------
# Entrega 2: janelas (SAW x GBN x SR com timeout fixo)
# ---------------------------------------------------------------------------

def analise_janelas(execucoes, arquivo, janela, perda):
    cabecalho = "| Protocolo | Janela | " + " | ".join(f"{p*100:.0f}% perda" for p in PERDAS) + " |"
    separador = "|---|---|" + "---|" * len(PERDAS)
    linhas = [f"Arquivo: {arquivo} — cada célula: throughput efetivo (kbps) / retransmissões / tempo total (s)", "",
              cabecalho, separador]

    for protocol, n in CENARIOS:
        celulas = [celula(ultima(execucoes, protocol, n, p),
                          lambda r: f"{float(r['throughput_efetivo_kbps']):.1f} / {r['retransmissoes']} / {float(r['tempo_total_s']):.1f}")
                   for p in PERDAS]
        linhas.append(f"| {protocol.upper()} | {n} | " + " | ".join(celulas) + " |")

    # Retransmissões por erro (timeout): mostra quantos REQs cada protocolo reenvia a cada perda
    linhas += ["", "| Protocolo | Janela | Perda | Timeouts | Retransmissões | Retransmissões por timeout |", "|---|---|---|---|---|---|"]
    for protocol, n in CENARIOS:
        for p in PERDAS[1:]:
            r = ultima(execucoes, protocol, n, p)
            if r and int(r["timeouts"]) > 0:
                razao = int(r["retransmissoes"]) / int(r["timeouts"])
                linhas.append(f"| {protocol.upper()} | {n} | {p*100:.0f}% | {r['timeouts']} | {r['retransmissoes']} | {razao:.2f} |")

    salvar_texto(arquivo, "tabela.md", "\n".join(linhas))
    grafico_gbn_vs_sr(execucoes, arquivo, janela, perda)
    grafico_janela(execucoes, arquivo)

def grafico_gbn_vs_sr(execucoes, arquivo, janela, perda):
    if not plt:
        return
    gbn = ultima(execucoes, "gbn", janela, perda)
    sr = ultima(execucoes, "sr", janela, perda)
    if not gbn or not sr:
        print(f"Faltam execuções de GBN e/ou SR com janela {janela} e {perda*100:.0f}% de perda para o gráfico.")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for linha, cor in ((gbn, "tab:red"), (sr, "tab:blue")):
        metricas = ler_metricas(linha["csv"])
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

    # Ex: gbn_vs_sr_w16_p10.png (mesmo padrão de janela/perda das pastas de cenário)
    sufixo = nome_cenario("gbn", janela, perda)[len("gbn_"):]
    salvar_figura(fig, arquivo, f"gbn_vs_sr_{sufixo}.png")

def grafico_janela(execucoes, arquivo):
    # Throughput efetivo sem perda em função do tamanho da janela (análise a)
    if not plt:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    for protocol, cor in (("gbn", "tab:red"), ("sr", "tab:blue")):
        pontos = [(1, ultima(execucoes, "saw", 1, 0.0))] + [(n, ultima(execucoes, protocol, n, 0.0)) for n in (4, 8, 16)]
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
    salvar_figura(fig, arquivo, "throughput_por_janela.png")

# ---------------------------------------------------------------------------
# Entrega 3: escolha de α e β
# ---------------------------------------------------------------------------

def replay_estimador(amostras, alpha, beta, piso_ms):
    # Reaplica a EWMA do cliente sobre uma série de RTTs medidos, com outros
    # α, β e piso. Para cada amostra, compara com a previsão feita ANTES dela:
    #   erro  = |RTT_medido - RTT_est|
    #   acima = RTT_medido > max(RTT_est + 4 * DevRTT, piso) (o timer teria expirado à toa)
    est = dev = None
    ests, timeouts, erros, acima = [], [], [], 0
    for rtt in amostras:
        if est is None:
            est, dev = rtt, rtt / 2
        else:
            timeout = max(est + 4 * dev, piso_ms)
            erros.append(abs(rtt - est))
            if rtt > timeout:
                acima += 1
            est = (1 - alpha) * est + alpha * rtt
            dev = (1 - beta) * dev + beta * abs(rtt - est)
        ests.append(est)
        timeouts.append(max(est + 4 * dev, piso_ms))
    n = max(len(erros), 1)
    return {
        "ests": ests,
        "timeouts": timeouts,
        "erro_medio": sum(erros) / n,
        "timeout_medio": sum(timeouts) / len(timeouts),
        "pct_acima": 100 * acima / n,
    }

def amostras_validas(metricas):
    # Mesma regra de Karn do cliente, na versão estrita possível só com o CSV:
    # segmentos sem retransmissão, na ordem em que chegaram
    validas = [m for m in metricas if m["retransmissions"] == "0"]
    validas.sort(key=lambda m: m["timestamp"])
    return [(int(m["segment"]), float(m["rtt_ms"])) for m in validas]

def analise_alfa_beta(execucoes, arquivo, protocol, janela, perda, alpha, beta, timeout_min, csv_replay, faixa):
    piso_ms = timeout_min * 1000
    linhas = [f"Arquivo: {arquivo} — escolha de α, β e do timeout mínimo", ""]

    # 1) Execuções reais com timeout adaptativo no cenário pedido
    pares = []
    for r in execucoes:
        if ((r["protocol"], r["window_size"], r["perda"], r["timeout_modo"]) == (protocol, janela, perda, "adaptativo")
                and abs(r["timeout_min"] - timeout_min) < 1e-9):
            par = (r["alpha"], r["beta"])
            if par not in pares:
                pares.append(par)
    linhas += [f"Execuções reais: {protocol.upper()}, janela {janela}, perda {perda*100:.0f}%, timeout mínimo {piso_ms:g} ms "
               "(última execução de cada par)", "",
               "| α | β | Tempo total (s) | Throughput efetivo (kbps) | Retransmissões | Timeouts | Timeouts além das perdas simuladas | DATA duplicados | Timeout médio (ms) | Erro médio do estimador (ms) |",
               "|---|---|---|---|---|---|---|---|---|---|"]
    if not pares:
        linhas.append("| — | — | — | — | — | — | — | — | — | — |")
    for a, b in sorted(pares):
        r = ultima(execucoes, protocol, janela, perda, "adaptativo", a, b, timeout_min)
        extras = int(r["timeouts"]) - int(r["perdas_simuladas"])
        linhas.append(f"| {a:g} | {b:g} | {float(r['tempo_total_s']):.1f} | {float(r['throughput_efetivo_kbps']):.1f} | "
                      f"{r['retransmissoes']} | {r['timeouts']} | {extras} | {r.get('duplicados') or '—'} | "
                      f"{r.get('timeout_medio_ms') or '—'} | {r.get('erro_estimador_ms') or '—'} |")
    linhas += ["",
               "Timeouts além das perdas simuladas = timeouts − perdas simuladas: perdas naturais da rede + timeouts espúrios "
               "(timer venceu antes do DATA chegar). DATA duplicados = DATA recebidos de segmentos já aceitos, ou seja, "
               "retransmissões que não eram necessárias."]

    # 1b) Execuções reais variando o timeout mínimo (plano "piso" do experimentos.py)
    pisos = sorted({r["timeout_min"] for r in execucoes
                    if (r["protocol"], r["window_size"], r["timeout_modo"]) == (protocol, janela, "adaptativo")
                    and abs(r["alpha"] - alpha) < 1e-9 and abs(r["beta"] - beta) < 1e-9})
    if pisos:
        linhas += ["", f"Execuções reais variando o timeout mínimo: {protocol.upper()}, janela {janela}, α={alpha:g}, β={beta:g}", "",
                   "| Perda | Timeout mínimo (ms) | Tempo total (s) | Throughput efetivo (kbps) | Retransmissões | "
                   "Timeouts além das perdas simuladas | DATA duplicados | Timeout médio (ms) |",
                   "|---|---|---|---|---|---|---|---|"]
        for p in PERDAS:
            for piso in pisos:
                r = ultima(execucoes, protocol, janela, p, "adaptativo", alpha, beta, piso)
                if r:
                    extras = int(r["timeouts"]) - int(r["perdas_simuladas"])
                    linhas.append(f"| {p*100:.0f}% | {piso*1000:g} | {float(r['tempo_total_s']):.1f} | "
                                  f"{float(r['throughput_efetivo_kbps']):.1f} | {r['retransmissoes']} | {extras} | "
                                  f"{r.get('duplicados') or '—'} | {r.get('timeout_medio_ms') or '—'} |")
        linhas += ["", "Um piso baixo detecta perdas reais mais rápido, mas gera retransmissões espúrias quando o RTT "
                   "oscila; um piso alto evita os espúrios, mas cada perda real custa pelo menos o valor do piso."]

    # 2) Replay offline: mesma série de RTTs para todos os pares (comparação justa)
    if csv_replay is None:
        base = ultima(execucoes, protocol, janela, 0.0) or ultima(execucoes, protocol, janela, 0.0, "adaptativo",
                                                                    ALPHA_PADRAO, BETA_PADRAO, timeout_min)
        csv_replay = base["csv"] if base else None
    if csv_replay is None:
        linhas += ["", f"Sem execução de {protocol.upper()} janela {janela} sem perda para o replay (use --csv)."]
        salvar_texto(arquivo, "tabela_alfa_beta.md", "\n".join(linhas))
        return

    amostras = amostras_validas(ler_metricas(csv_replay))
    rtts = [rtt for _, rtt in amostras]
    resultados = {(a, b): replay_estimador(rtts, a, b, piso_ms) for a in ALPHAS for b in BETAS}

    linhas += ["", f"Replay offline do estimador sobre os RTTs de `{csv_replay}` ({len(rtts)} amostras válidas), "
               f"timeout mínimo {piso_ms:g} ms", "",
               "| α | β | Erro médio de previsão (ms) | Timeout médio (ms) | Amostras acima do timeout (%) |",
               "|---|---|---|---|---|"]
    for (a, b), res in resultados.items():
        destaque = " **(TCP)**" if (a, b) == (ALPHA_PADRAO, BETA_PADRAO) else ""
        linhas.append(f"| {a:g} | {b:g}{destaque} | {res['erro_medio']:.2f} | {res['timeout_medio']:.2f} | {res['pct_acima']:.2f} |")
    linhas += ["",
               "Erro de previsão: quanto o RTT_est errou o RTT seguinte (α controla a velocidade de reação). "
               "Amostras acima do timeout: RTTs que teriam estourado o timer sem haver perda, isto é, retransmissões "
               "espúrias (β controla a margem 4·DevRTT). Timeout médio: quanto se espera, em média, para detectar uma "
               "perda real. O melhor par equilibra poucos espúrios com um timeout baixo."]

    # 3) Efeito do piso do timeout com α e β do TCP
    linhas += ["", f"Piso do timeout (replay com α={ALPHA_PADRAO:g} e β={BETA_PADRAO:g})", "",
               "| Timeout mínimo (ms) | Amostras acima do timeout (%) | Timeout médio (ms) |", "|---|---|---|"]
    for piso in PISOS_MS:
        res = replay_estimador(rtts, ALPHA_PADRAO, BETA_PADRAO, piso)
        linhas.append(f"| {piso} | {res['pct_acima']:.2f} | {res['timeout_medio']:.2f} |")
    linhas += ["",
               "Sem piso, o DevRTT encolhe em períodos estáveis e o timeout fica colado no RTT: qualquer fila no "
               "servidor faz a janela inteira expirar à toa. O piso é o \"RTO mínimo\" do TCP real."]
    salvar_texto(arquivo, "tabela_alfa_beta.md", "\n".join(linhas))

    if not plt:
        return
    inicio, fim = faixa
    segs = [s for s, _ in amostras]
    idx = [i for i, s in enumerate(segs) if inicio <= s < fim] or list(range(len(segs)))
    x = [segs[i] for i in idx]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9), sharex=True)
    ax1.plot(x, [rtts[i] for i in idx], color="tab:red", marker="o", markersize=2, linewidth=0.5, alpha=0.5, label="RTT medido")
    for a, cor in zip(ALPHAS, ("tab:green", "black", "tab:orange", "tab:purple")):
        ests = resultados[(a, BETA_PADRAO)]["ests"]
        ax1.plot(x, [ests[i] for i in idx], color=cor, linewidth=1.2, label=f"RTT_est α={a:g}")
    ax1.set_ylabel("RTT (ms)")
    ax1.set_title(f"Replay do estimador — {protocol.upper()} janela {janela} ({arquivo}, segmentos {x[0]}–{x[-1]})")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend(loc="upper right", fontsize=8)

    ax2.plot(x, [rtts[i] for i in idx], color="tab:red", marker="o", markersize=2, linewidth=0.5, alpha=0.5, label="RTT medido")
    for b, cor in zip(BETAS, ("tab:green", "black", "tab:orange")):
        touts = resultados[(ALPHA_PADRAO, b)]["timeouts"]
        ax2.plot(x, [touts[i] for i in idx], color=cor, linewidth=1.2, label=f"Timeout β={b:g} (α={ALPHA_PADRAO:g})")
    if piso_ms:
        ax2.axhline(piso_ms, color="tab:gray", linestyle="--", linewidth=1, label=f"Timeout mínimo ({piso_ms:g} ms)")
    ax2.set_xlabel("Número do Segmento")
    ax2.set_ylabel("Timeout (ms)")
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend(loc="upper right", fontsize=8)
    salvar_figura(fig, arquivo, "alfa_beta_replay.png")

# ---------------------------------------------------------------------------
# Entrega 3: timeout fixo x adaptativo
# ---------------------------------------------------------------------------

def analise_timeout(execucoes, arquivo, protocolos, janela, alpha, beta, timeout_min):
    linhas = [f"Arquivo: {arquivo} — timeout fixo x adaptativo (janela {janela}, α={alpha:g}, β={beta:g}, "
              f"mínimo {timeout_min*1000:g} ms)", "",
              "| Protocolo | Perda | Timeout | Retransmissões | Timeouts | DATA duplicados | Tempo total (s) | Throughput efetivo (kbps) | Timeout médio (ms) |",
              "|---|---|---|---|---|---|---|---|---|"]
    barras = []  # (rótulo, tempo fixo, tempo adaptativo)
    for protocol in protocolos:
        for perda in PERDAS:
            fixo = ultima(execucoes, protocol, janela, perda)
            adapt = ultima(execucoes, protocol, janela, perda, "adaptativo", alpha, beta, timeout_min)
            if not fixo and not adapt:
                continue
            for modo, r in (("fixo", fixo), ("adaptativo", adapt)):
                if r:
                    linhas.append(f"| {protocol.upper()} | {perda*100:.0f}% | {modo} | {r['retransmissoes']} | {r['timeouts']} | "
                                  f"{r.get('duplicados') or '—'} | {float(r['tempo_total_s']):.1f} | "
                                  f"{float(r['throughput_efetivo_kbps']):.1f} | {r.get('timeout_medio_ms') or r['timeout_ms']} |")
                else:
                    linhas.append(f"| {protocol.upper()} | {perda*100:.0f}% | {modo} | — | — | — | — | — | — |")
            if fixo and adapt:
                ganho = float(fixo["tempo_total_s"]) / float(adapt["tempo_total_s"])
                linhas.append(f"| | | **adaptativo {ganho:.1f}× mais rápido** | | | | | | |")
                barras.append((f"{protocol.upper()} {perda*100:.0f}%", float(fixo["tempo_total_s"]), float(adapt["tempo_total_s"])))

    salvar_texto(arquivo, "tabela_timeout.md", "\n".join(linhas))

    if not plt or not barras:
        return
    fig, ax = plt.subplots(figsize=(max(6, 1.6 * len(barras)), 5))
    xs = range(len(barras))
    largura = 0.38
    b1 = ax.bar([x - largura / 2 for x in xs], [b[1] for b in barras], largura, color="tab:gray", label="Timeout fixo")
    b2 = ax.bar([x + largura / 2 for x in xs], [b[2] for b in barras], largura, color="tab:blue",
                label=f"Timeout adaptativo (α={alpha:g}, β={beta:g})")
    ax.bar_label(b1, fmt="%.1f", fontsize=8)
    ax.bar_label(b2, fmt="%.1f", fontsize=8)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([b[0] for b in barras])
    ax.set_ylabel("Tempo total (s)")
    ax.set_title(f"Timeout fixo x adaptativo — janela {janela} ({arquivo})")
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    ax.legend()
    salvar_figura(fig, arquivo, "timeout_fixo_vs_adaptativo.png")

# ---------------------------------------------------------------------------
# Relatório final: visão integrada dos três protocolos
# ---------------------------------------------------------------------------

def analise_final(execucoes, arquivo, perda, alpha, beta, timeout_min):
    linhas_tabela = [("SAW", "saw", 1, "fixo"), ("GBN", "gbn", 16, "fixo"), ("GBN", "gbn", 16, "adaptativo"),
                     ("SR", "sr", 16, "fixo"), ("SR", "sr", 16, "adaptativo")]
    linhas = [f"Arquivo: {arquivo} — comparação final (perda simulada {perda*100:.0f}%, adaptativo com α={alpha:g}, "
              f"β={beta:g}, mínimo {timeout_min*1000:g} ms)", "",
              f"| Protocolo | Janela | Timeout | Throughput médio (kbps) | Retransmissões | Tempo total ({arquivo}) (s) |",
              "|---|---|---|---|---|---|"]
    barras = []
    for rotulo, protocol, janela, modo in linhas_tabela:
        r = ultima(execucoes, protocol, janela, perda, modo, alpha, beta, timeout_min)
        if r:
            thr = float(r["throughput_efetivo_kbps"])
            linhas.append(f"| {rotulo} | {janela} | {modo} | {thr:.1f} | {r['retransmissoes']} | {float(r['tempo_total_s']):.1f} |")
            barras.append((f"{rotulo} {janela}\n{modo}", thr, modo))
        else:
            linhas.append(f"| {rotulo} | {janela} | {modo} | — | — | — |")
    linhas += ["", "Throughput médio = tamanho do arquivo × 8 / tempo total da transferência."]
    salvar_texto(arquivo, "tabela_final.md", "\n".join(linhas))

    if not plt or not barras:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    cores = ["tab:gray" if modo == "fixo" else "tab:blue" for _, _, modo in barras]
    b = ax.bar([x[0] for x in barras], [x[1] for x in barras], color=cores)
    ax.bar_label(b, fmt="%.0f", fontsize=9)
    ax.set_ylabel("Throughput médio (kbps)")
    ax.set_title(f"Throughput médio por protocolo — arquivo {arquivo}, perda {perda*100:.0f}%")
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    salvar_figura(fig, arquivo, "throughput_final.png")

# ---------------------------------------------------------------------------

def main():
    saida_utf8()
    parser = argparse.ArgumentParser(description="Tabelas comparativas e gráficos das Entregas 2 e 3")
    parser.add_argument("--analise", choices=["janelas", "alfa-beta", "timeout", "final"], default="janelas",
                        help="janelas: Entrega 2 | alfa-beta: escolha de α e β | timeout: fixo x adaptativo | "
                             "final: tabela integrada do relatório final (padrão: janelas)")
    parser.add_argument("--file", default="small", help="Arquivo usado nos testes (small, medium, large)")
    parser.add_argument("--protocol", choices=["saw", "gbn", "sr"], default="sr", help="Protocolo da análise alfa-beta (padrão: sr)")
    parser.add_argument("--window", type=int, default=16, help="Janela das análises (padrão: 16)")
    parser.add_argument("--loss", type=float, default=None,
                        help="Perda: gráfico GBN vs SR (padrão 0.10), alfa-beta (padrão 0.10) e final (padrão 0)")
    parser.add_argument("--alpha", type=float, default=ALPHA_PADRAO, help=f"α do timeout adaptativo comparado (padrão: {ALPHA_PADRAO})")
    parser.add_argument("--beta", type=float, default=BETA_PADRAO, help=f"β do timeout adaptativo comparado (padrão: {BETA_PADRAO})")
    parser.add_argument("--timeout-min", type=float, default=TIMEOUT_MIN_PADRAO,
                        help=f"Piso do timeout adaptativo comparado, em segundos (padrão: {TIMEOUT_MIN_PADRAO})")
    parser.add_argument("--csv", default=None, help="CSV de métricas usado no replay alfa-beta (padrão: última execução sem perda)")
    parser.add_argument("--faixa", default="0:500", help="Faixa de segmentos do gráfico de replay, ex: 0:500")
    args = parser.parse_args()

    if not os.path.exists(ARQUIVO_RESUMO):
        print(f"'{caminho_relativo(ARQUIVO_RESUMO)}' não encontrado. Rode o cliente.py antes.")
        return

    execucoes = ler_resumo(args.file)
    if args.analise == "janelas":
        analise_janelas(execucoes, args.file, args.window, round(args.loss if args.loss is not None else 0.10, 2))
    elif args.analise == "alfa-beta":
        inicio, fim = (int(v) for v in args.faixa.split(":"))
        csv_replay = caminho_relativo(os.path.abspath(args.csv)) if args.csv else None
        analise_alfa_beta(execucoes, args.file, args.protocol, args.window,
                          round(args.loss if args.loss is not None else 0.10, 2), args.alpha, args.beta,
                          args.timeout_min, csv_replay, (inicio, fim))
    elif args.analise == "timeout":
        analise_timeout(execucoes, args.file, ["gbn", "sr"], args.window, args.alpha, args.beta, args.timeout_min)
    else:
        analise_final(execucoes, args.file, round(args.loss if args.loss is not None else 0.0, 2),
                      args.alpha, args.beta, args.timeout_min)

if __name__ == "__main__":
    main()
