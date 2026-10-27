import socket
import time
import hashlib
import argparse
import csv
import random
import os
import sys
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

ALPHA_PADRAO = 0.125  # Valores do TCP real (Kurose / RFC 6298)
BETA_PADRAO = 0.25
# Piso do timeout adaptativo (o "RTO mínimo" do TCP: 1 s na RFC 6298, 200 ms
# no Linux). Sem ele, em períodos estáveis o DevRTT cai para ~1 ms e o timeout
# fica colado no RTT (~22 ms); qualquer fila no servidor estoura a janela
# inteira à toa. 60 ms (~3x o RTT) foi o menor valor com quase nenhum
# estouro nos RTTs medidos (ver comparar.py --analise alfa-beta).
TIMEOUT_MIN_PADRAO = 0.06
TIMEOUT_MAX_S = 3.0   # Teto do backoff exponencial do timeout adaptativo

def nome_cenario(protocol, window_size, perda, adaptativo=False, alpha=ALPHA_PADRAO, beta=BETA_PADRAO,
                 timeout_min=TIMEOUT_MIN_PADRAO):
    # Ex: saw_w01_p00, gbn_w16_p10 (números com 2 dígitos para ordenar certo)
    # Timeout adaptativo ganha sufixo com α, β e o piso em ms:
    #   sr_w16_p10_adapt_a0.125_b0.25_min60
    nome = f"{protocol}_w{window_size:02d}_p{round(perda * 100):02d}"
    if adaptativo:
        nome += f"_adapt_a{alpha:g}_b{beta:g}_min{round(timeout_min * 1000)}"
    return nome

def caminho_relativo(caminho):
    return os.path.relpath(caminho, PASTA_PROJETO).replace(os.sep, "/")

def saida_utf8():
    # No Windows, quando a saída vai para um arquivo ou pipe, o Python usa
    # cp1252, que não tem α e β: força UTF-8 para não quebrar os prints
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

class Temporizador:
    # Define o timeout de retransmissão usado em cada REQ.
    #
    # O RTT estimado é calculado em qualquer modo (coluna rtt_estimated_ms):
    #   RTT_est = (1 - α) * RTT_est + α * RTT_medido
    #   DevRTT  = (1 - β) * DevRTT  + β * |RTT_medido - RTT_est|
    # Modo fixo: o timeout é sempre o valor de --timeout.
    # Modo adaptativo (Entrega 3): timeout = RTT_est + 4 * DevRTT, nunca
    # abaixo do piso --timeout-min (ver TIMEOUT_MIN_PADRAO).
    #
    # Algoritmo de Karn: uma amostra só entra na média se não for ambígua.
    # Se um segmento teve dois REQs e só um DATA chegou, não dá para saber a
    # qual REQ ele responde. Por isso cada protocolo conta REQs enviados e
    # DATAs recebidos por segmento, e a amostra só vale quando todo REQ já teve
    # resposta (ver amostra_valida). DATA descartado pela perda simulada não
    # conta como resposta, pois simula um pacote que nunca chegou.
    # Para o timeout não ficar preso num valor baixo demais quando o RTT sobe
    # de repente, cada timeout dobra o valor atual (backoff exponencial) até
    # chegar uma nova amostra válida.
    def __init__(self, adaptativo, timeout_inicial_s, alpha, beta, timeout_min_s):
        self.adaptativo = adaptativo
        self.alpha = alpha
        self.beta = beta
        self.timeout_min_s = timeout_min_s
        self.timeout_s = timeout_inicial_s
        self.rtt_est_s = None
        self.dev_rtt_s = 0.0
        # Erro de previsão |RTT_medido - RTT_est anterior|: mede a qualidade do estimador
        self.soma_erro_s = 0.0
        self.amostras_erro = 0

    def registrar_amostra(self, rtt_s):
        if self.rtt_est_s is None:
            # Primeira amostra (RFC 6298): RTT_est = R e DevRTT = R / 2
            self.rtt_est_s = rtt_s
            self.dev_rtt_s = rtt_s / 2
        else:
            self.soma_erro_s += abs(rtt_s - self.rtt_est_s)
            self.amostras_erro += 1
            self.rtt_est_s = (1 - self.alpha) * self.rtt_est_s + self.alpha * rtt_s
            self.dev_rtt_s = (1 - self.beta) * self.dev_rtt_s + self.beta * abs(rtt_s - self.rtt_est_s)

        if self.adaptativo:
            timeout = max(self.rtt_est_s + 4 * self.dev_rtt_s, self.timeout_min_s)
            self.timeout_s = min(timeout, TIMEOUT_MAX_S)

    def registrar_timeout(self):
        if self.adaptativo:
            self.timeout_s = min(self.timeout_s * 2, TIMEOUT_MAX_S)

    def rtt_est_ms(self):
        return self.rtt_est_s * 1000 if self.rtt_est_s is not None else 0.0

    def erro_medio_ms(self):
        return self.soma_erro_s / self.amostras_erro * 1000 if self.amostras_erro else 0.0

def amostra_valida(reqs_enviados, datas_recebidos):
    # Karn: o RTT (último REQ -> DATA) só é confiável se cada REQ enviado para
    # o segmento já recebeu seu DATA. Ex.: no GBN, os segmentos reenviados "de
    # carona" já tinham recebido o DATA original (descartado por estar fora de
    # ordem), então o DATA novo só pode ser a resposta do REQ retransmitido.
    return datas_recebidos == reqs_enviados

def linha_csv(seq, timestamp_iso, size_bytes, rtt_ms, rtt_estimated_ms, timeout_ms, thr_kbps, ret, t_out_occ, window_size, protocol, sim_loss):
    return [
        seq,
        timestamp_iso,
        size_bytes,
        round(rtt_ms, 2),
        round(rtt_estimated_ms, 2),
        round(timeout_ms, 2),
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

def baixar_segmento(sock, servidor, seq, temporizador, perda):
    retransmissoes = 0
    timeout_ocorrido = False
    simulou_perda = False
    duplicados = 0
    reqs_enviados = 0
    datas_recebidos = 0

    inicio_req = time.time()

    while True:
        enviar_req(sock, servidor, seq)
        reqs_enviados += 1
        envio = time.time()
        timeout_s = temporizador.timeout_s
        prazo = envio + timeout_s # Momento em que o timer deste REQ expira

        try:
            while True:
                # Espera apenas o tempo que falta para o timer expirar
                sock.settimeout(max(prazo - time.time(), 0.001))
                dados, _ = sock.recvfrom(65507)
                chegada = time.time()
                # Pega o momento em que o pacote chegou em formato ISO 8601
                timestamp_chegada = datetime.now().isoformat()

                pacote = parse_data(dados)
                if pacote is None:
                    continue
                if pacote[0] != seq:
                    if pacote[0] < seq:
                        duplicados += 1 # DATA repetido de um segmento já recebido
                    continue # Pacote atrasado/duplicado de outro segmento: ignora

                if perda_simulada(perda):
                    simulou_perda = True
                    continue # Descarta o DATA e continua esperando até o timeout

                datas_recebidos += 1
                payload = pacote[1]
                size_bytes = len(payload)

                enviar_ack(sock, servidor, seq)

                # RTT = último REQ enviado -> DATA (é o que o Wireshark mostra)
                rtt_s = chegada - envio
                if amostra_valida(reqs_enviados, datas_recebidos):
                    temporizador.registrar_amostra(rtt_s)

                # Throughput em kbps (kilobits per second), considerando todo o
                # tempo gasto no segmento, inclusive timeouts e retransmissões
                # size_bytes * 8 = bits | / tempo_s = bits por seg | / 1000 = kilobits por seg
                tempo_s = chegada - inicio_req
                throughput_kbps = ((size_bytes * 8) / tempo_s) / 1000 if tempo_s > 0 else 0

                return (payload, timestamp_chegada, size_bytes, rtt_s * 1000, timeout_s * 1000, throughput_kbps,
                        retransmissoes, timeout_ocorrido, simulou_perda, duplicados)

        except socket.timeout:
            timeout_ocorrido = True
            retransmissoes += 1
            temporizador.registrar_timeout()

def transferir_saw(sock, servidor, total_seg, temporizador, perda):
    dados_completos = bytearray()
    metricas = []
    total_duplicados = 0

    for seq in range(total_seg):
        payload, timestamp_iso, size_bytes, rtt_ms, t_out_ms, thr_kbps, ret, t_out_occ, sim, dup = baixar_segmento(sock, servidor, seq, temporizador, perda)
        dados_completos.extend(payload)
        total_duplicados += dup
        metricas.append(linha_csv(seq, timestamp_iso, size_bytes, rtt_ms, temporizador.rtt_est_ms(), t_out_ms, thr_kbps,
                                  ret, t_out_occ, 1, "saw", sim))
        mostrar_progresso(seq + 1, total_seg)

    return dados_completos, metricas, total_duplicados

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

def transferir_gbn(sock, servidor, total_seg, window_size, temporizador, perda):
    # Go-Back-N: até N REQs pendentes, um único timer (do segmento mais antigo
    # da janela). Só aceita DATA na ordem; fora de ordem é descartado.
    # Se o timer expirar, reenvia o REQ do base e de todos os seguintes.
    dados_completos = bytearray()
    metricas = []
    duplicados = 0

    retransmissoes = [0] * total_seg
    timeout_ocorrido = [False] * total_seg
    simulou_perda = [False] * total_seg
    ultimo_envio = [0.0] * total_seg
    timeout_envio = [0.0] * total_seg # Timeout (ms) em vigor no último REQ de cada segmento
    reqs_enviados = [0] * total_seg   # Para o algoritmo de Karn (ver amostra_valida)
    datas_recebidos = [0] * total_seg

    base = 0           # Segmento mais antigo ainda não recebido
    proximo = 0        # Próximo seq que ainda não teve REQ enviado
    inicio_timer = None
    medidor = MedidorThroughput(window_size, time.time())

    while base < total_seg:
        # Preenche a janela com novos REQs
        while proximo < base + window_size and proximo < total_seg:
            enviar_req(sock, servidor, proximo)
            reqs_enviados[proximo] += 1
            ultimo_envio[proximo] = time.time()
            timeout_envio[proximo] = temporizador.timeout_s * 1000
            if base == proximo:
                inicio_timer = ultimo_envio[proximo]
            proximo += 1

        try:
            # Espera até o prazo do timer. Se o prazo já passou, ainda lê o que
            # estiver no buffer do socket: um DATA que já chegou não pode
            # virar timeout só porque o cliente demorou para processá-lo.
            restante = temporizador.timeout_s - (time.time() - inicio_timer)
            sock.settimeout(max(restante, 0.0001))
            dados, _ = sock.recvfrom(65507)
        except socket.timeout:
            if temporizador.timeout_s - (time.time() - inicio_timer) <= 0:
                # Timeout do base: volta N, reenviando todos os REQs pendentes
                timeout_ocorrido[base] = True
                temporizador.registrar_timeout()
                for seq in range(base, proximo):
                    enviar_req(sock, servidor, seq)
                    reqs_enviados[seq] += 1
                    ultimo_envio[seq] = time.time()
                    timeout_envio[seq] = temporizador.timeout_s * 1000
                    retransmissoes[seq] += 1
                inicio_timer = time.time()
            continue

        chegada = time.time()
        timestamp_chegada = datetime.now().isoformat()

        pacote = parse_data(dados)
        if pacote is None:
            continue
        seq, payload = pacote

        if seq != base:
            if 0 <= seq < total_seg:
                datas_recebidos[seq] += 1 # Chegou (mesmo descartado): o REQ teve resposta
            if seq < base:
                duplicados += 1 # DATA repetido de um segmento já recebido
            continue # Fora de ordem ou duplicado: GBN descarta sem guardar

        if perda_simulada(perda):
            simulou_perda[seq] = True
            continue

        datas_recebidos[seq] += 1
        enviar_ack(sock, servidor, seq)
        dados_completos.extend(payload)

        rtt_s = chegada - ultimo_envio[seq]
        if amostra_valida(reqs_enviados[seq], datas_recebidos[seq]):
            temporizador.registrar_amostra(rtt_s)
        thr_kbps = medidor.registrar(chegada, len(payload))
        metricas.append(linha_csv(seq, timestamp_chegada, len(payload), rtt_s * 1000, temporizador.rtt_est_ms(),
                                  timeout_envio[seq], thr_kbps, retransmissoes[seq], timeout_ocorrido[seq],
                                  window_size, "gbn", simulou_perda[seq]))

        base += 1
        # Reinicia o timer para o novo base (se ainda houver REQ pendente)
        inicio_timer = time.time() if base < proximo else None
        mostrar_progresso(base, total_seg)

    return dados_completos, metricas, duplicados

def transferir_sr(sock, servidor, total_seg, window_size, temporizador, perda):
    # Selective Repeat: até N REQs pendentes, um timer por segmento.
    # Aceita DATA fora de ordem dentro da janela e guarda em buffer;
    # no timeout, reenvia apenas o REQ daquele segmento.
    buffer = {}        # seq -> payload recebido fora de ordem
    dados_completos = bytearray()
    linhas = {}        # seq -> linha do CSV
    duplicados = 0

    retransmissoes = [0] * total_seg
    timeout_ocorrido = [False] * total_seg
    simulou_perda = [False] * total_seg
    ultimo_envio = [0.0] * total_seg
    timeout_envio = [0.0] * total_seg # Timeout (ms) em vigor no último REQ de cada segmento
    reqs_enviados = [0] * total_seg   # Para o algoritmo de Karn (ver amostra_valida)
    datas_recebidos = [0] * total_seg
    prazos = {}        # seq pendente -> instante em que seu timer expira

    base = 0           # Segmento mais antigo ainda não entregue em ordem
    proximo = 0
    medidor = MedidorThroughput(window_size, time.time())

    while base < total_seg:
        # Preenche a janela com novos REQs
        while proximo < base + window_size and proximo < total_seg:
            enviar_req(sock, servidor, proximo)
            reqs_enviados[proximo] += 1
            ultimo_envio[proximo] = time.time()
            timeout_envio[proximo] = temporizador.timeout_s * 1000
            prazos[proximo] = ultimo_envio[proximo] + temporizador.timeout_s
            proximo += 1

        try:
            # Espera até o prazo do timer mais próximo. Se o prazo já passou,
            # ainda lê o que estiver no buffer do socket: um DATA que já
            # chegou não pode virar timeout só porque o cliente demorou para
            # processá-lo.
            sock.settimeout(max(min(prazos.values()) - time.time(), 0.0001))
            dados, _ = sock.recvfrom(65507)
        except socket.timeout:
            # Nada chegou até o prazo: retransmite só os segmentos expirados
            agora = time.time()
            expirados = [seq for seq, prazo in prazos.items() if prazo <= agora]
            if expirados:
                # Um único backoff por rodada: vários timers vencendo juntos
                # indicam o mesmo evento (ex.: aumento do RTT), não N eventos
                temporizador.registrar_timeout()
            for seq in expirados:
                timeout_ocorrido[seq] = True
                retransmissoes[seq] += 1
                enviar_req(sock, servidor, seq)
                reqs_enviados[seq] += 1
                ultimo_envio[seq] = time.time()
                timeout_envio[seq] = temporizador.timeout_s * 1000
                prazos[seq] = ultimo_envio[seq] + temporizador.timeout_s
            continue

        chegada = time.time()
        timestamp_chegada = datetime.now().isoformat()

        pacote = parse_data(dados)
        if pacote is None:
            continue
        seq, payload = pacote

        if seq < base or seq in buffer:
            duplicados += 1
            enviar_ack(sock, servidor, seq) # Duplicado: reconhece de novo (Kurose)
            continue
        if seq >= base + window_size:
            continue # Fora da janela

        if perda_simulada(perda):
            simulou_perda[seq] = True
            continue

        datas_recebidos[seq] += 1
        enviar_ack(sock, servidor, seq)
        buffer[seq] = payload
        del prazos[seq]

        rtt_s = chegada - ultimo_envio[seq]
        if amostra_valida(reqs_enviados[seq], datas_recebidos[seq]):
            temporizador.registrar_amostra(rtt_s)
        thr_kbps = medidor.registrar(chegada, len(payload))
        linhas[seq] = linha_csv(seq, timestamp_chegada, len(payload), rtt_s * 1000, temporizador.rtt_est_ms(),
                                timeout_envio[seq], thr_kbps, retransmissoes[seq], timeout_ocorrido[seq],
                                window_size, "sr", simulou_perda[seq])

        # Entrega em ordem tudo que já estiver contíguo a partir do base
        while base in buffer:
            dados_completos.extend(buffer.pop(base))
            base += 1
            mostrar_progresso(base, total_seg)

    metricas = [linhas[seq] for seq in range(total_seg)]
    return dados_completos, metricas, duplicados

# ---------------------------------------------------------------------------
# Gráfico, resumo e encerramento
# ---------------------------------------------------------------------------

def gerar_grafico(metricas, titulo, caminho):
    if not plt:
        return

    seqs = [m[0] for m in metricas]
    rtts = [m[3] for m in metricas] # rtt_ms
    ests = [m[4] for m in metricas] # rtt_estimated_ms
    touts = [m[5] for m in metricas] # timeout_ms
    thrs = [m[6] for m in metricas] # throughput_kbps
    rets = [m[7] for m in metricas] # retransmissions

    sumRTT = sum(rtts)
    avgRTT = sumRTT / len(rtts) if len(rtts) > 0 else 0

    # Cria uma figura com 4 gráficos (4 linhas, 1 coluna)
    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(10, 13), sharex=True)

    # Gráfico 1: RTT medido vs RTT estimado (EWMA)
    color1 = 'tab:red'
    ax1.set_ylabel('RTT (ms)')
    ax1.plot(seqs, rtts, color=color1, marker='o', markersize=2, linewidth=0.6, alpha=0.6, label='RTT medido')
    ax1.plot(seqs, ests, color='black', linewidth=1.2, label='RTT estimado (EWMA)')
    ax1.set_title(f'{titulo}\nRTT Médio: {avgRTT:.2f} ms')
    ax1.grid(True, linestyle='--', alpha=0.6) # Adiciona grade para facilitar a leitura
    ax1.legend(loc='upper right')

    # Gráfico 2: Timeout em vigor no REQ de cada segmento
    color2 = 'tab:purple'
    ax2.set_ylabel('Timeout (ms)', color=color2)
    ax2.plot(seqs, touts, color=color2, linewidth=1)
    ax2.tick_params(axis='y', labelcolor=color2)
    ax2.grid(True, linestyle='--', alpha=0.6)

    # Gráfico 3: Throughput
    color3 = 'tab:blue'
    ax3.set_ylabel('Throughput (kbps)', color=color3)
    ax3.plot(seqs, thrs, color=color3, marker='x', markersize=3, linewidth=1, alpha=0.7)
    ax3.tick_params(axis='y', labelcolor=color3)
    ax3.grid(True, linestyle='--', alpha=0.6)

    # Gráfico 4: Retransmissões
    color4 = 'tab:green'
    ax4.set_xlabel('Número do Segmento')
    ax4.set_ylabel('Retransmissões', color=color4)
    ax4.bar(seqs, rets, color=color4, width=1.0)
    ax4.tick_params(axis='y', labelcolor=color4)
    ax4.grid(True, linestyle='--', alpha=0.6)

    fig.tight_layout()
    plt.savefig(caminho)
    plt.close(fig)
    print(f"    Gráfico salvo em '{caminho_relativo(caminho)}'.")

CAMPOS_RESUMO = [
    "data_hora", "grupo", "arquivo", "protocol", "window_size", "perda",
    "timeout_modo", "alpha", "beta", "timeout_ms", "timeout_min_ms", "timeout_medio_ms",
    "tempo_total_s", "throughput_efetivo_kbps", "throughput_medio_kbps",
    "throughput_teorico_kbps", "rtt_medio_ms", "erro_estimador_ms", "retransmissoes",
    "timeouts", "perdas_simuladas", "duplicados", "md5_ok", "csv"
]

def salvar_resumo(dados):
    # Acumula uma linha por execução para montar as tabelas comparativas
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)

    # Resumo de uma versão anterior (Entrega 2) não tem as colunas novas:
    # reescreve o arquivo com o cabeçalho atual, marcando as linhas antigas
    # como timeout fixo, que era o único modo existente.
    if os.path.exists(ARQUIVO_RESUMO):
        with open(ARQUIVO_RESUMO, newline="") as f:
            leitor = csv.DictReader(f)
            antigas = list(leitor)
            cabecalho = leitor.fieldnames
        if cabecalho != CAMPOS_RESUMO:
            with open(ARQUIVO_RESUMO, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CAMPOS_RESUMO)
                writer.writeheader()
                for linha in antigas:
                    linha.setdefault("timeout_modo", "fixo")
                    writer.writerow({campo: linha.get(campo, "") for campo in CAMPOS_RESUMO})

    novo = not os.path.exists(ARQUIVO_RESUMO)
    with open(ARQUIVO_RESUMO, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_RESUMO)
        if novo:
            writer.writeheader()
        writer.writerow(dados)

def main():
    saida_utf8()
    parser = argparse.ArgumentParser(description="Cliente RDT-UnB (Stop-and-Wait, Go-Back-N e Selective Repeat)")
    parser.add_argument("--server", required=True, help="IP do servidor")
    parser.add_argument("--group", required=True, help="Nome do grupo")
    parser.add_argument("--file", required=True, help="Tamanho do arquivo (small, medium, large)")
    parser.add_argument("--protocol", choices=["saw", "gbn", "sr"], default="saw", help="Protocolo (padrão: saw)")
    parser.add_argument("--window", type=int, default=None, help="Tamanho da janela N para gbn/sr (padrão: 4)")
    parser.add_argument("--loss", type=float, default=0.0, help="Probabilidade de perda simulada, de 0 a 1 (ex: 0.05 = 5%%)")
    parser.add_argument("--timeout", type=float, default=1.0,
                        help="Timeout fixo em segundos; com --adaptive é o timeout inicial (padrão: 1.0)")
    parser.add_argument("--adaptive", action="store_true",
                        help="Usa timeout adaptativo: RTT_est + 4 * DevRTT (Entrega 3)")
    parser.add_argument("--alpha", type=float, default=ALPHA_PADRAO, help=f"Peso α da EWMA do RTT (padrão: {ALPHA_PADRAO})")
    parser.add_argument("--beta", type=float, default=BETA_PADRAO, help=f"Peso β da EWMA do DevRTT (padrão: {BETA_PADRAO})")
    parser.add_argument("--timeout-min", type=float, default=TIMEOUT_MIN_PADRAO,
                        help=f"Piso do timeout adaptativo em segundos (padrão: {TIMEOUT_MIN_PADRAO})")
    parser.add_argument("--seed", type=int, default=None, help="Semente do sorteio de perda (para reprodutibilidade)")
    args = parser.parse_args()

    if not 0 <= args.loss < 1:
        parser.error("--loss deve estar entre 0 e 1 (ex: 0.05 para 5%)")
    if not (0 < args.alpha <= 1 and 0 < args.beta <= 1):
        parser.error("--alpha e --beta devem estar entre 0 (exclusive) e 1")
    if args.timeout_min < 0:
        parser.error("--timeout-min deve ser >= 0")

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
    temporizador = Temporizador(args.adaptive, args.timeout, args.alpha, args.beta, args.timeout_min)
    modo = "adaptativo" if args.adaptive else "fixo"

    print(f"=== Cliente RDT-UnB - {protocol.upper()} (Grupo: {args.group}) ===")
    if args.adaptive:
        descricao_timeout = (f"adaptativo (α={args.alpha:g}, β={args.beta:g}, inicial {args.timeout*1000:.0f} ms, "
                             f"mínimo {args.timeout_min*1000:.0f} ms)")
    else:
        descricao_timeout = f"fixo de {args.timeout*1000:.0f} ms"
    print(f"    Janela: {window_size} | Perda simulada: {args.loss*100:.1f}% | Timeout: {descricao_timeout}")

    try:
        rtt, server_time = ping(sock, servidor)
        print(f"[1] PING -> RTT: {rtt:.2f} ms")

        tamanho_arq, checksum_esperado, total_seg, tam_seg = hello(sock, servidor, args.group, args.file)
        print(f"[2] HELLO -> Arquivo: {args.file} | Tamanho: {tamanho_arq}B | MD5: {checksum_esperado}")

        print("[3] DOWNLOAD -> Baixando segmentos...")
        inicio_transferencia = time.time()

        if protocol == "saw":
            dados_completos, metricas, duplicados = transferir_saw(sock, servidor, total_seg, temporizador, args.loss)
        elif protocol == "gbn":
            dados_completos, metricas, duplicados = transferir_gbn(sock, servidor, total_seg, window_size, temporizador, args.loss)
        else:
            dados_completos, metricas, duplicados = transferir_sr(sock, servidor, total_seg, window_size, temporizador, args.loss)

        tempo_total_s = time.time() - inicio_transferencia
        sock.settimeout(args.timeout)

        # Gravação do CSV de métricas: metrics_<grupo>_<protocolo>_<timestamp>.csv,
        # dentro da pasta do cenário (arquivo / protocolo + janela + perda + timeout).
        # O gráfico usa o mesmo sufixo para ficar fácil parear os dois.
        data_hora_atual = datetime.now().strftime("%Y%m%d_%H%M%S")
        sufixo = f"{args.group.lower()}_{protocol}_{data_hora_atual}"
        cenario = nome_cenario(protocol, window_size, args.loss, args.adaptive, args.alpha, args.beta, args.timeout_min)
        pasta_cenario = os.path.join(PASTA_RESULTADOS, args.file, cenario)
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
        timeout_medio_ms = sum(m[5] for m in metricas) / len(metricas)
        total_retx = sum(m[7] for m in metricas)
        total_timeouts = sum(m[8] for m in metricas)
        total_perdas = sum(m[11] for m in metricas)
        print(f"    Tempo total: {tempo_total_s:.2f} s")
        print(f"    RTT médio: {rtt_medio_s * 1000:.2f} ms | RTT estimado final: {temporizador.rtt_est_ms():.2f} ms"
              f" | Erro médio do estimador: {temporizador.erro_medio_ms():.2f} ms")
        print(f"    Timeout médio: {timeout_medio_ms:.2f} ms")
        print(f"    Throughput teórico máximo: {throughput_max_kbps:.2f} kbps")
        print(f"    Throughput médio medido: {throughput_medio_kbps:.2f} kbps")
        print(f"    Throughput efetivo (arquivo / tempo total): {throughput_efetivo_kbps:.2f} kbps")
        print(f"    Retransmissões: {total_retx} | Timeouts: {total_timeouts} | Perdas simuladas: {total_perdas}"
              f" | DATA duplicados: {duplicados}")

        # Geração de Gráfico
        titulo = (f"Métricas {protocol.upper()} (janela={window_size}, perda={args.loss*100:.0f}%, "
                  f"timeout {modo}" + (f", α={args.alpha:g}, β={args.beta:g}, mín. {args.timeout_min*1000:.0f} ms"
                                       if args.adaptive else "") + ")")
        gerar_grafico(metricas, titulo, nome_grafico)

        # Passo 4 - FIN e DONE
        print("[4] ENCERRAMENTO E VALIDAÇÃO")
        md5_calculado = hashlib.md5(dados_completos).hexdigest()
        print(f"    MD5 esperado:  {checksum_esperado}")
        print(f"    MD5 calculado: {md5_calculado}")
        if md5_calculado == checksum_esperado:
            print("    [OK] Checksum MD5 confere.")
        else:
            print("    [ERRO] Checksum MD5 não confere.")

        salvar_resumo({
            "data_hora": datetime.now().isoformat(timespec="seconds"),
            "grupo": args.group,
            "arquivo": args.file,
            "protocol": protocol,
            "window_size": window_size,
            "perda": args.loss,
            "timeout_modo": modo,
            "alpha": args.alpha,
            "beta": args.beta,
            "timeout_ms": args.timeout * 1000,
            "timeout_min_ms": args.timeout_min * 1000 if args.adaptive else "",
            "timeout_medio_ms": round(timeout_medio_ms, 2),
            "tempo_total_s": round(tempo_total_s, 2),
            "throughput_efetivo_kbps": round(throughput_efetivo_kbps, 2),
            "throughput_medio_kbps": round(throughput_medio_kbps, 2),
            "throughput_teorico_kbps": round(throughput_max_kbps, 2),
            "rtt_medio_ms": round(rtt_medio_s * 1000, 2),
            "erro_estimador_ms": round(temporizador.erro_medio_ms(), 2),
            "retransmissoes": total_retx,
            "timeouts": total_timeouts,
            "perdas_simuladas": total_perdas,
            "duplicados": duplicados,
            "md5_ok": int(md5_calculado == checksum_esperado),
            "csv": caminho_relativo(nome_csv),
        })
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
