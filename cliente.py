import socket
import time
import hashlib
import argparse
import csv
import random
import os
from collections import deque
from datetime import datetime # Importação nova para formatar a hora atual
try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Aviso: 'matplotlib' não instalado. Os gráficos não serão gerados.")
    plt = None

PORTA = 8080

# Organização dos arquivos gerados (sempre relativa à pasta do projeto):
#   resultados/resumo.csv                         -> uma linha por execução
#   resultados/<arquivo>/<cenario>/metrics_*.csv  -> métricas por segmento
#   resultados/<arquivo>/<cenario>/grafico_*.png  -> gráfico da execução
#   recebidos/received_<arquivo>                  -> arquivo baixado e validado
PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
PASTA_RESULTADOS = os.path.join(PASTA_PROJETO, "resultados")
PASTA_RECEBIDOS = os.path.join(PASTA_PROJETO, "recebidos")
ARQUIVO_RESUMO = os.path.join(PASTA_RESULTADOS, "resumo.csv")

def nome_cenario(protocol, window_size, perda):
    # Ex: saw_w01_p00, gbn_w16_p10 (números com 2 dígitos para ordenar certo)
    return f"{protocol}_w{window_size:02d}_p{round(perda * 100):02d}"

def caminho_relativo(caminho):
    return os.path.relpath(caminho, PASTA_PROJETO).replace(os.sep, "/")

def criar_socket(timeout=1.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    return sock

def ping(sock, servidor):
    inicio = time.time()
    sock.sendto(b"PING", servidor)

    dados, _ = sock.recvfrom(65507)
    fim = time.time()

    rtt = (fim - inicio) * 1000
    resposta = dados.decode("utf-8")
    server_time = float(resposta.split("|")[1].split("=")[1])

    return rtt, server_time

def hello(sock, servidor, grupo, arquivo):
    pacote = f"HELLO|grupo={grupo}|segment_size=512|file={arquivo}"
    sock.sendto(pacote.encode("utf-8"), servidor)

    dados_retornados, _ = sock.recvfrom(65507)
    resposta = dados_retornados.decode("utf-8")

    campos = resposta.split("|")
    tamanho_do_arquivo = int(campos[1].split("=")[1])
    checksum = campos[2].split("=")[1]
    total_segmentos = int(campos[4].split("=")[1])
    tamanho_segmento = int(campos[5].split("=")[1])

    return tamanho_do_arquivo, checksum, total_segmentos, tamanho_segmento

def enviar_req(sock, servidor, seq):
    sock.sendto(f"REQ|seq={seq}".encode("utf-8"), servidor)

def enviar_ack(sock, servidor, seq):
    sock.sendto(f"ACK|seq={seq}".encode("utf-8"), servidor)

def parse_data(dados):
    # Formato: DATA|seq=<n>|total=<bytes>|<payload_binário>
    # Retorna (seq, payload) ou None se o pacote não for um DATA válido
    idx1 = dados.find(b"|")
    idx2 = dados.find(b"|", idx1 + 1)
    idx3 = dados.find(b"|", idx2 + 1)

    if idx3 == -1:
        return None

    cabecalho = dados[:idx3].decode("utf-8", errors="ignore")
    if not cabecalho.startswith("DATA"):
        return None

    seq_recebida = int(cabecalho.split("|")[1].split("=")[1])
    return seq_recebida, dados[idx3+1:]

def perda_simulada(perda):
    # Simulação de perda (abordagem a): o DATA recebido é descartado com
    # probabilidade P antes de ser processado, como se nunca tivesse chegado.
    return perda > 0 and random.random() < perda

def linha_csv(seq, timestamp_iso, size_bytes, rtt_ms, timeout_ms, thr_kbps, ret, t_out_occ, window_size, protocol, sim_loss):
    rtt_estimated_ms = 0.0 # Será implementado apenas na Tarefa 3
    return [
        seq,
        timestamp_iso,
        size_bytes,
        round(rtt_ms, 2),
        rtt_estimated_ms,
        timeout_ms,
        round(thr_kbps, 2),
        ret,
        int(t_out_occ),
        window_size,
        protocol,
        int(sim_loss)
    ]

def mostrar_progresso(concluidos, total_seg):
    if concluidos % (total_seg // 10 if total_seg >= 10 else 1) == 0:
        print(f"    Progresso: {concluidos}/{total_seg} segmentos...")

# ---------------------------------------------------------------------------
# Stop-and-Wait (Entrega 1)
# ---------------------------------------------------------------------------

def baixar_segmento(sock, servidor, seq, timeout_s, perda):
    retransmissoes = 0
    timeout_ocorrido = False
    simulou_perda = False
    timeout_ms = timeout_s * 1000

    inicio_req = time.time()

    while True:
        enviar_req(sock, servidor, seq)
        prazo = time.time() + timeout_s # Momento em que o timer deste REQ expira

        try:
            while True:
                # Espera apenas o tempo que falta para o timer expirar
                sock.settimeout(max(prazo - time.time(), 0.001))
                dados, _ = sock.recvfrom(65507)
                # Pega o momento em que o pacote chegou em formato ISO 8601
                timestamp_chegada = datetime.now().isoformat()

                pacote = parse_data(dados)
                if pacote is None or pacote[0] != seq:
                    continue # Pacote atrasado/duplicado de outro segmento: ignora

                if perda_simulada(perda):
                    simulou_perda = True
                    continue # Descarta o DATA e continua esperando até o timeout

                payload = pacote[1]
                size_bytes = len(payload)

                enviar_ack(sock, servidor, seq)

                rtt_s = time.time() - inicio_req
                rtt_ms = rtt_s * 1000

                # Throughput em kbps (kilobits per second)
                # size_bytes * 8 = bits | / rtt_s = bits por seg | / 1000 = kilobits por seg
                throughput_kbps = ((size_bytes * 8) / rtt_s) / 1000 if rtt_s > 0 else 0

                return payload, timestamp_chegada, size_bytes, rtt_ms, timeout_ms, throughput_kbps, retransmissoes, timeout_ocorrido, simulou_perda

        except socket.timeout:
            timeout_ocorrido = True
            retransmissoes += 1

def transferir_saw(sock, servidor, total_seg, timeout_s, perda):
    dados_completos = bytearray()
    metricas = []

    for seq in range(total_seg):
        payload, timestamp_iso, size_bytes, rtt_ms, t_out_ms, thr_kbps, ret, t_out_occ, sim = baixar_segmento(sock, servidor, seq, timeout_s, perda)
        dados_completos.extend(payload)
        metricas.append(linha_csv(seq, timestamp_iso, size_bytes, rtt_ms, t_out_ms, thr_kbps, ret, t_out_occ, 1, "saw", sim))
        mostrar_progresso(seq + 1, total_seg)

    return dados_completos, metricas

# ---------------------------------------------------------------------------
# Janela deslizante (Entrega 2)
# ---------------------------------------------------------------------------

class MedidorThroughput:
    # Throughput instantâneo de protocolos com janela: bits dos últimos N
    # segmentos aceitos divididos pelo tempo que levaram para chegar.
    # Com N = 1 isso se reduz ao caso do SAW (segment_size * 8 / intervalo).
    def __init__(self, window_size, inicio):
        self.chegadas = deque([(inicio, 0)], maxlen=window_size + 1)

    def registrar(self, instante, size_bytes):
        self.chegadas.append((instante, size_bytes))
        t0 = self.chegadas[0][0]
        bits = sum(tamanho for _, tamanho in list(self.chegadas)[1:]) * 8
        dt = instante - t0
        return (bits / dt) / 1000 if dt > 0 else 0

def transferir_gbn(sock, servidor, total_seg, window_size, timeout_s, perda):
    # Go-Back-N: até N REQs pendentes, um único timer (do segmento mais antigo
    # da janela). Só aceita DATA na ordem; fora de ordem é descartado.
    # Se o timer expirar, reenvia o REQ do base e de todos os seguintes.
    dados_completos = bytearray()
    metricas = []
    timeout_ms = timeout_s * 1000

    retransmissoes = [0] * total_seg
    timeout_ocorrido = [False] * total_seg
    simulou_perda = [False] * total_seg
    ultimo_envio = [0.0] * total_seg

    base = 0           # Segmento mais antigo ainda não recebido
    proximo = 0        # Próximo seq que ainda não teve REQ enviado
    inicio_timer = None
    medidor = MedidorThroughput(window_size, time.time())

    while base < total_seg:
        # Preenche a janela com novos REQs
        while proximo < base + window_size and proximo < total_seg:
            enviar_req(sock, servidor, proximo)
            ultimo_envio[proximo] = time.time()
            if base == proximo:
                inicio_timer = ultimo_envio[proximo]
            proximo += 1

        restante = timeout_s - (time.time() - inicio_timer)

        if restante <= 0:
            # Timeout do base: volta N, reenviando todos os REQs pendentes
            timeout_ocorrido[base] = True
            for seq in range(base, proximo):
                enviar_req(sock, servidor, seq)
                ultimo_envio[seq] = time.time()
                retransmissoes[seq] += 1
            inicio_timer = time.time()
            continue

        try:
            sock.settimeout(max(restante, 0.001))
            dados, _ = sock.recvfrom(65507)
        except socket.timeout:
            continue # O próximo laço detecta o timeout e retransmite

        chegada = time.time()
        timestamp_chegada = datetime.now().isoformat()

        pacote = parse_data(dados)
        if pacote is None:
            continue
        seq, payload = pacote

        if seq != base:
            continue # Fora de ordem ou duplicado: GBN descarta sem guardar

        if perda_simulada(perda):
            simulou_perda[seq] = True
            continue

        enviar_ack(sock, servidor, seq)
        dados_completos.extend(payload)

        rtt_ms = (chegada - ultimo_envio[seq]) * 1000
        thr_kbps = medidor.registrar(chegada, len(payload))
        metricas.append(linha_csv(seq, timestamp_chegada, len(payload), rtt_ms, timeout_ms, thr_kbps,
                                  retransmissoes[seq], timeout_ocorrido[seq], window_size, "gbn", simulou_perda[seq]))

        base += 1
        # Reinicia o timer para o novo base (se ainda houver REQ pendente)
        inicio_timer = time.time() if base < proximo else None
        mostrar_progresso(base, total_seg)

    return dados_completos, metricas

def transferir_sr(sock, servidor, total_seg, window_size, timeout_s, perda):
    # Selective Repeat: até N REQs pendentes, um timer por segmento.
    # Aceita DATA fora de ordem dentro da janela e guarda em buffer;
    # no timeout, reenvia apenas o REQ daquele segmento.
    buffer = {}        # seq -> payload recebido fora de ordem
    dados_completos = bytearray()
    linhas = {}        # seq -> linha do CSV
    timeout_ms = timeout_s * 1000

    retransmissoes = [0] * total_seg
    timeout_ocorrido = [False] * total_seg
    simulou_perda = [False] * total_seg
    ultimo_envio = [0.0] * total_seg
    prazos = {}        # seq pendente -> instante em que seu timer expira

    base = 0           # Segmento mais antigo ainda não entregue em ordem
    proximo = 0
    medidor = MedidorThroughput(window_size, time.time())

    while base < total_seg:
        # Preenche a janela com novos REQs
        while proximo < base + window_size and proximo < total_seg:
            enviar_req(sock, servidor, proximo)
            ultimo_envio[proximo] = time.time()
            prazos[proximo] = ultimo_envio[proximo] + timeout_s
            proximo += 1

        # Retransmite somente os segmentos cujo timer expirou
        agora = time.time()
        for seq, prazo in list(prazos.items()):
            if prazo <= agora:
                timeout_ocorrido[seq] = True
                retransmissoes[seq] += 1
                enviar_req(sock, servidor, seq)
                ultimo_envio[seq] = time.time()
                prazos[seq] = ultimo_envio[seq] + timeout_s

        try:
            sock.settimeout(max(min(prazos.values()) - time.time(), 0.001))
            dados, _ = sock.recvfrom(65507)
        except socket.timeout:
            continue

        chegada = time.time()
        timestamp_chegada = datetime.now().isoformat()

        pacote = parse_data(dados)
        if pacote is None:
            continue
        seq, payload = pacote

        if seq < base or seq in buffer:
            enviar_ack(sock, servidor, seq) # Duplicado: reconhece de novo (Kurose)
            continue
        if seq >= base + window_size:
            continue # Fora da janela

        if perda_simulada(perda):
            simulou_perda[seq] = True
            continue

        enviar_ack(sock, servidor, seq)
        buffer[seq] = payload
        del prazos[seq]

        rtt_ms = (chegada - ultimo_envio[seq]) * 1000
        thr_kbps = medidor.registrar(chegada, len(payload))
        linhas[seq] = linha_csv(seq, timestamp_chegada, len(payload), rtt_ms, timeout_ms, thr_kbps,
                                retransmissoes[seq], timeout_ocorrido[seq], window_size, "sr", simulou_perda[seq])

        # Entrega em ordem tudo que já estiver contíguo a partir do base
        while base in buffer:
            dados_completos.extend(buffer.pop(base))
            base += 1
            mostrar_progresso(base, total_seg)

    metricas = [linhas[seq] for seq in range(total_seg)]
    return dados_completos, metricas

# ---------------------------------------------------------------------------
# Gráfico, resumo e encerramento
# ---------------------------------------------------------------------------

def gerar_grafico(metricas, protocol, window_size, perda, caminho):
    if not plt:
        return

    seqs = [m[0] for m in metricas]
    rtts = [m[3] for m in metricas] # rtt_ms
    thrs = [m[6] for m in metricas] # throughput_kbps
    rets = [m[7] for m in metricas] # retransmissions

    sumRTT = sum(rtts)
    avgRTT = sumRTT / len(rtts) if len(rtts) > 0 else 0

    # Cria uma figura com 3 gráficos (3 linhas, 1 coluna)
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 10), sharex=True)

    # Gráfico 1: RTT
    color1 = 'tab:red'
    ax1.set_ylabel('RTT (ms)', color=color1)
    ax1.plot(seqs, rtts, color=color1, marker='o', markersize=3, linewidth=1)
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.set_title(f'Métricas {protocol.upper()} (janela={window_size}, perda={perda*100:.0f}%)\nRTT Médio: {avgRTT:.2f} ms')
    ax1.grid(True, linestyle='--', alpha=0.6) # Adiciona grade para facilitar a leitura

    # Gráfico 2: Throughput
    color2 = 'tab:blue'
    ax2.set_ylabel('Throughput (kbps)', color=color2)
    ax2.plot(seqs, thrs, color=color2, marker='x', markersize=3, linewidth=1, alpha=0.7)
    ax2.tick_params(axis='y', labelcolor=color2)
    ax2.grid(True, linestyle='--', alpha=0.6)

    # Gráfico 3: Retransmissões
    color3 = 'tab:green'
    ax3.set_xlabel('Número do Segmento')
    ax3.set_ylabel('Retransmissões', color=color3)
    ax3.bar(seqs, rets, color=color3, width=1.0)
    ax3.tick_params(axis='y', labelcolor=color3)
    ax3.grid(True, linestyle='--', alpha=0.6)

    fig.tight_layout()
    plt.savefig(caminho)
    plt.close(fig)
    print(f"    Gráfico salvo em '{caminho_relativo(caminho)}'.")

def salvar_resumo(linha):
    # Acumula uma linha por execução para montar a tabela comparativa
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)
    novo = not os.path.exists(ARQUIVO_RESUMO)
    with open(ARQUIVO_RESUMO, "a", newline="") as f:
        writer = csv.writer(f)
        if novo:
            writer.writerow([
                "data_hora", "grupo", "arquivo", "protocol", "window_size", "perda",
                "timeout_ms", "tempo_total_s", "throughput_efetivo_kbps", "throughput_medio_kbps",
                "throughput_teorico_kbps", "rtt_medio_ms", "retransmissoes", "timeouts",
                "perdas_simuladas", "md5_ok", "csv"
            ])
        writer.writerow(linha)

def main():
    parser = argparse.ArgumentParser(description="Cliente RDT-UnB (Stop-and-Wait, Go-Back-N e Selective Repeat)")
    parser.add_argument("--server", required=True, help="IP do servidor")
    parser.add_argument("--group", required=True, help="Nome do grupo")
    parser.add_argument("--file", required=True, help="Tamanho do arquivo (small, medium, large)")
    parser.add_argument("--protocol", choices=["saw", "gbn", "sr"], default="saw", help="Protocolo (padrão: saw)")
    parser.add_argument("--window", type=int, default=None, help="Tamanho da janela N para gbn/sr (padrão: 4)")
    parser.add_argument("--loss", type=float, default=0.0, help="Probabilidade de perda simulada, de 0 a 1 (ex: 0.05 = 5%%)")
    parser.add_argument("--timeout", type=float, default=1.0, help="Timeout fixo em segundos (padrão: 1.0)")
    parser.add_argument("--seed", type=int, default=None, help="Semente do sorteio de perda (para reprodutibilidade)")
    args = parser.parse_args()

    if not 0 <= args.loss < 1:
        parser.error("--loss deve estar entre 0 e 1 (ex: 0.05 para 5%)")

    protocol = args.protocol
    if protocol == "saw":
        if args.window not in (None, 1):
            print("Aviso: Stop-and-Wait sempre usa janela 1; --window ignorado.")
        window_size = 1
    else:
        window_size = args.window if args.window is not None else 4
        if window_size < 1:
            parser.error("--window deve ser >= 1")

    if args.seed is not None:
        random.seed(args.seed)

    sock = criar_socket(timeout=args.timeout)
    servidor = (args.server, PORTA)

    print(f"=== Cliente RDT-UnB - {protocol.upper()} (Grupo: {args.group}) ===")
    print(f"    Janela: {window_size} | Perda simulada: {args.loss*100:.1f}% | Timeout: {args.timeout*1000:.0f} ms")

    try:
        rtt, server_time = ping(sock, servidor)
        print(f"[1] PING -> RTT: {rtt:.2f} ms")

        tamanho_arq, checksum_esperado, total_seg, tam_seg = hello(sock, servidor, args.group, args.file)
        print(f"[2] HELLO -> Arquivo: {args.file} | Tamanho: {tamanho_arq}B | MD5: {checksum_esperado}")

        print("[3] DOWNLOAD -> Baixando segmentos...")
        inicio_transferencia = time.time()

        if protocol == "saw":
            dados_completos, metricas = transferir_saw(sock, servidor, total_seg, args.timeout, args.loss)
        elif protocol == "gbn":
            dados_completos, metricas = transferir_gbn(sock, servidor, total_seg, window_size, args.timeout, args.loss)
        else:
            dados_completos, metricas = transferir_sr(sock, servidor, total_seg, window_size, args.timeout, args.loss)

        tempo_total_s = time.time() - inicio_transferencia
        sock.settimeout(args.timeout)

        # Gravação do CSV de métricas: metrics_<grupo>_<protocolo>_<timestamp>.csv,
        # dentro da pasta do cenário (arquivo / protocolo + janela + perda).
        # O gráfico usa o mesmo sufixo para ficar fácil parear os dois.
        data_hora_atual = datetime.now().strftime("%Y%m%d_%H%M%S")
        sufixo = f"{args.group.lower()}_{protocol}_{data_hora_atual}"
        pasta_cenario = os.path.join(PASTA_RESULTADOS, args.file, nome_cenario(protocol, window_size, args.loss))
        os.makedirs(pasta_cenario, exist_ok=True)
        nome_csv = os.path.join(pasta_cenario, f"metrics_{sufixo}.csv")
        nome_grafico = os.path.join(pasta_cenario, f"grafico_{sufixo}.png")

        with open(nome_csv, "w", newline="") as f:
            writer = csv.writer(f)
            # Cabeçalho exigido pelo documento (+ simulated_loss da Entrega 2)
            writer.writerow([
                "segment", "timestamp", "size_bytes", "rtt_ms",
                "rtt_estimated_ms", "timeout_ms", "throughput_kbps",
                "retransmissions", "timeout_occurred", "window_size", "protocol",
                "simulated_loss"
            ])
            writer.writerows(metricas)

        print(f"    Métricas salvas em '{caminho_relativo(nome_csv)}'.")

        # Throughput teórico máximo = (window_size * segment_size * 8) / RTT_médio
        # (para o SAW, window_size = 1 e a fórmula é a da Entrega 1)
        rtt_medio_s = sum(m[3] for m in metricas) / len(metricas) / 1000
        throughput_max_kbps = (window_size * tam_seg * 8) / rtt_medio_s / 1000
        throughput_medio_kbps = sum(m[6] for m in metricas) / len(metricas)
        throughput_efetivo_kbps = (len(dados_completos) * 8) / tempo_total_s / 1000
        total_retx = sum(m[7] for m in metricas)
        total_timeouts = sum(m[8] for m in metricas)
        total_perdas = sum(m[11] for m in metricas)
        print(f"    Tempo total: {tempo_total_s:.2f} s")
        print(f"    RTT médio: {rtt_medio_s * 1000:.2f} ms")
        print(f"    Throughput teórico máximo: {throughput_max_kbps:.2f} kbps")
        print(f"    Throughput médio medido: {throughput_medio_kbps:.2f} kbps")
        print(f"    Throughput efetivo (arquivo / tempo total): {throughput_efetivo_kbps:.2f} kbps")
        print(f"    Retransmissões: {total_retx} | Timeouts: {total_timeouts} | Perdas simuladas: {total_perdas}")

        # Geração de Gráfico
        gerar_grafico(metricas, protocol, window_size, args.loss, nome_grafico)

        # Passo 4 - FIN e DONE
        print("[4] ENCERRAMENTO E VALIDAÇÃO")
        md5_calculado = hashlib.md5(dados_completos).hexdigest()
        print(f"    MD5 esperado:  {checksum_esperado}")
        print(f"    MD5 calculado: {md5_calculado}")
        if md5_calculado == checksum_esperado:
            print("    [OK] Checksum MD5 confere.")
        else:
            print("    [ERRO] Checksum MD5 não confere.")

        salvar_resumo([
            datetime.now().isoformat(timespec="seconds"), args.group, args.file, protocol, window_size,
            args.loss, args.timeout * 1000, round(tempo_total_s, 2), round(throughput_efetivo_kbps, 2),
            round(throughput_medio_kbps, 2), round(throughput_max_kbps, 2), round(rtt_medio_s * 1000, 2),
            total_retx, total_timeouts, total_perdas, int(md5_calculado == checksum_esperado), caminho_relativo(nome_csv)
        ])
        print(f"    Resumo da execução adicionado em '{caminho_relativo(ARQUIVO_RESUMO)}'.")

        pacote_fin = f"FIN|checksum={md5_calculado}".encode("utf-8")

        recebeu_done = False
        for tentativa in range(5):
            sock.sendto(pacote_fin, servidor)
            try:
                while True:
                    dados_done, _ = sock.recvfrom(65507)
                    cabecalho_done = dados_done[:15].decode("utf-8", errors="ignore")
                    if cabecalho_done.startswith("DONE"):
                        resposta_done = dados_done.decode("utf-8", errors="ignore")
                        print(f"    Servidor respondeu: {resposta_done}")

                        if "ok=1" in resposta_done:
                            os.makedirs(PASTA_RECEBIDOS, exist_ok=True)
                            nome_arquivo = os.path.join(PASTA_RECEBIDOS, f"received_{args.file}")
                            with open(nome_arquivo, "wb") as f:
                                f.write(dados_completos)
                            print(f"    [SUCESSO] Arquivo validado e salvo em '{caminho_relativo(nome_arquivo)}'.")
                        else:
                            print("    [ERRO] Checksum inválido segundo o servidor (DONE|ok=0).")

                        recebeu_done = True
                        break
            except socket.timeout:
                print(f"    Timeout aguardando DONE (tentativa {tentativa+1}/5). Reenviando FIN...")
                continue

            if recebeu_done:
                break

        if not recebeu_done:
            print("    [ERRO] O servidor não respondeu com DONE após várias tentativas.")

    except Exception as e:
        print(f"\nErro de execução: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
