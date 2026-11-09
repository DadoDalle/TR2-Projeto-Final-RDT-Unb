import argparse
import os
import subprocess
import sys

from cliente import PASTA_PROJETO, ALPHA_PADRAO, BETA_PADRAO, TIMEOUT_MIN_PADRAO, saida_utf8

# Roda em sequência as execuções do cliente.py de cada análise e, no fim,
# gera a tabela/gráficos correspondentes com o comparar.py.
#
#   alfa-beta : SR janela 16 com 10% de perda, variando um parâmetro por vez
#               a partir dos valores do TCP (α=0.125, β=0.25)
#   piso      : SR janela 16 sem perda e com 10% de perda, variando o timeout
#               mínimo (0, 30, 60 e 100 ms)
#   timeout   : GBN e SR janela 16 com 5% e 10% de perda, timeout fixo e adaptativo
#   final     : SAW, GBN 16 e SR 16 (fixo e adaptativo) sem perda, para a tabela
#               integrada do relatório final (use --file large)

PARES_ALFA_BETA = [(0.125, 0.25), (0.05, 0.25), (0.25, 0.25), (0.5, 0.25), (0.125, 0.125), (0.125, 0.5)]
PISOS_S = [0, 0.03, 0.06, 0.1]

def adaptativo(args, alpha, beta):
    return ["--adaptive", "--alpha", str(alpha), "--beta", str(beta), "--timeout-min", str(args.timeout_min)]

def plano_alfa_beta(args):
    return [["--protocol", "sr", "--window", "16", "--loss", "0.1"] + adaptativo(args, a, b)
            for a, b in PARES_ALFA_BETA]

def plano_piso(args):
    # Mesmos α e β, variando o timeout mínimo, sem perda e com 10% de perda
    execucoes = []
    for perda in ("0", "0.1"):
        for piso in PISOS_S:
            execucoes.append(["--protocol", "sr", "--window", "16", "--loss", perda, "--adaptive",
                              "--alpha", str(args.alpha), "--beta", str(args.beta), "--timeout-min", str(piso)])
    return execucoes

def plano_timeout(args):
    execucoes = []
    for protocol in ("gbn", "sr"):
        for perda in ("0.05", "0.1"):
            base = ["--protocol", protocol, "--window", "16", "--loss", perda]
            if not args.sem_fixo:
                execucoes.append(base)
            execucoes.append(base + adaptativo(args, args.alpha, args.beta))
    return execucoes

def plano_final(args):
    adapt = adaptativo(args, args.alpha, args.beta)
    return [
        ["--protocol", "saw"],
        ["--protocol", "gbn", "--window", "16"],
        ["--protocol", "gbn", "--window", "16"] + adapt,
        ["--protocol", "sr", "--window", "16"],
        ["--protocol", "sr", "--window", "16"] + adapt,
    ]

PLANOS = {"alfa-beta": plano_alfa_beta, "piso": plano_piso, "timeout": plano_timeout, "final": plano_final}
# Análise do comparar.py gerada no fim de cada plano
ANALISES = {"alfa-beta": "alfa-beta", "piso": "alfa-beta", "timeout": "timeout", "final": "final"}

def main():
    saida_utf8()
    parser = argparse.ArgumentParser(description="Executa os lotes de testes da Entrega 3 e do relatório final")
    parser.add_argument("--plano", choices=PLANOS.keys(), required=True, help="Lote de execuções")
    parser.add_argument("--server", required=True, help="IP do servidor")
    parser.add_argument("--group", required=True, help="Nome do grupo")
    parser.add_argument("--file", default="small", help="Arquivo (padrão: small; para o plano final use large)")
    parser.add_argument("--alpha", type=float, default=ALPHA_PADRAO, help="α escolhido (planos timeout e final)")
    parser.add_argument("--beta", type=float, default=BETA_PADRAO, help="β escolhido (planos timeout e final)")
    parser.add_argument("--timeout-min", type=float, default=TIMEOUT_MIN_PADRAO,
                        help=f"Piso do timeout adaptativo em segundos (padrão: {TIMEOUT_MIN_PADRAO})")
    parser.add_argument("--seed", type=int, default=1, help="Semente da perda simulada, igual em todas as execuções (padrão: 1)")
    parser.add_argument("--sem-fixo", action="store_true", help="Plano timeout: pula as execuções com timeout fixo")
    parser.add_argument("--dry-run", action="store_true", help="Só mostra os comandos, sem executar")
    args = parser.parse_args()

    cliente = os.path.join(PASTA_PROJETO, "cliente.py")
    comuns = ["--server", args.server, "--group", args.group, "--file", args.file, "--seed", str(args.seed)]
    execucoes = PLANOS[args.plano](args)

    for i, extra in enumerate(execucoes, 1):
        comando = [sys.executable, cliente] + comuns + extra
        print(f"\n##### [{i}/{len(execucoes)}] python cliente.py {' '.join(comuns + extra)}", flush=True)
        if not args.dry_run:
            subprocess.run(comando, check=False)

    analise = [sys.executable, os.path.join(PASTA_PROJETO, "comparar.py"), "--analise", ANALISES[args.plano],
               "--file", args.file, "--alpha", str(args.alpha), "--beta", str(args.beta),
               "--timeout-min", str(args.timeout_min)]
    print(f"\n##### Análise: python comparar.py {' '.join(analise[2:])}", flush=True)
    if not args.dry_run:
        subprocess.run(analise, check=False)

if __name__ == "__main__":
    main()
