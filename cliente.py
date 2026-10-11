import socket
import time
import hashlib
import argparse
import csv
from datetime import datetime # Importação nova para formatar a hora atual
try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Aviso: 'matplotlib' não instalado. Os gráficos não serão gerados.")
    plt = None

PORTA = 8080

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

def baixar_segmento(sock, servidor, seq):
    pacote_req = f"REQ|seq={seq}".encode("utf-8")
    pacote_ack = f"ACK|seq={seq}".encode("utf-8")
    
    retransmissoes = 0
    timeout_ocorrido = False
    timeout_ms = sock.gettimeout() * 1000 # Pega o timeout do socket configurado (em ms)
    
    inicio_req = time.time()
    
    while True:
        sock.sendto(pacote_req, servidor)
        
        try:
            dados, _ = sock.recvfrom(65507)
            # Pega o momento em que o pacote chegou em formato ISO 8601
            timestamp_chegada = datetime.now().isoformat() 

            idx1 = dados.find(b"|")
            idx2 = dados.find(b"|", idx1 + 1)
            idx3 = dados.find(b"|", idx2 + 1)
            
            if idx3 != -1:
                cabecalho = dados[:idx3].decode("utf-8", errors="ignore")
                
                if cabecalho.startswith("DATA"):
                    seq_recebida = int(cabecalho.split("|")[1].split("=")[1])
                    
                    if seq_recebida == seq:
                        payload = dados[idx3+1:]
                        size_bytes = len(payload)
                        
                        sock.sendto(pacote_ack, servidor)
                        
                        rtt_s = time.time() - inicio_req
                        rtt_ms = rtt_s * 1000
                        
                        # Throughput em kbps (kilobits per second)
                        # size_bytes * 8 = bits | / rtt_s = bits por seg | / 1000 = kilobits por seg
                        throughput_kbps = ((size_bytes * 8) / rtt_s) / 1000 if rtt_s > 0 else 0
                        
                        return payload, timestamp_chegada, size_bytes, rtt_ms, timeout_ms, throughput_kbps, retransmissoes, timeout_ocorrido
        
        except socket.timeout:
            timeout_ocorrido = True
            retransmissoes += 1

def gerar_grafico(metricas):
    if not plt:
        return
        
    seqs = [m[0] for m in metricas]
    rtts = [m[3] for m in metricas] # rtt_ms
    thrs = [m[6] for m in metricas] # throughput_kbps

    sumRTT = sum(rtts)
    avgRTT = sumRTT / len(rtts) if len(rtts) > 0 else 0
    print(f"    RTT médio: {avgRTT:.2f} ms")

    # Cria uma figura com 2 gráficos (2 linhas, 1 coluna)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # Gráfico 1: RTT
    color1 = 'tab:red'
    ax1.set_ylabel('RTT (ms)', color=color1)
    ax1.plot(seqs, rtts, color=color1, marker='o', markersize=3, linewidth=1)
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.set_title(f'Métricas Stop-and-Wait\nRTT Médio: {avgRTT:.2f} ms')
    ax1.grid(True, linestyle='--', alpha=0.6) # Adiciona grade para facilitar a leitura

    # Gráfico 2: Throughput
    color2 = 'tab:blue'
    ax2.set_xlabel('Número do Segmento')
    ax2.set_ylabel('Throughput (kbps)', color=color2)
    ax2.plot(seqs, thrs, color=color2, marker='x', markersize=3, linewidth=1, alpha=0.7)
    ax2.tick_params(axis='y', labelcolor=color2)
    ax2.grid(True, linestyle='--', alpha=0.6)

    fig.tight_layout()
    plt.savefig('grafico_saw.png')
    print("    Gráfico salvo como 'grafico_saw.png'.")

def main():
    parser = argparse.ArgumentParser(description="Cliente RDT Stop-and-Wait")
    parser.add_argument("--server", required=True, help="IP do servidor")
    parser.add_argument("--group", required=True, help="Nome do grupo")
    parser.add_argument("--file", required=True, help="Tamanho do arquivo (small, medium, large)")
    args = parser.parse_args()

    sock = criar_socket(timeout=1.0)
    servidor = (args.server, PORTA)

    print(f"=== Entrega 1 - Stop-and-Wait (Grupo: {args.group}) ===")
    
    try:
        rtt, server_time = ping(sock, servidor)
        print(f"[1] PING -> RTT: {rtt:.2f} ms")

        tamanho_arq, checksum_esperado, total_seg, tam_seg = hello(sock, servidor, args.group, args.file)
        print(f"[2] HELLO -> Arquivo: {args.file} | Tamanho: {tamanho_arq}B | MD5: {checksum_esperado}")

        print("[3] DOWNLOAD -> Baixando segmentos...")
        dados_completos = bytearray()
        metricas = []
        
        # Parâmetros constantes para a Entrega 1 (Stop-and-Wait)
        window_size = 1
        protocol = "saw"
        rtt_estimated_ms = 0.0 # Será implementado apenas na Tarefa 3
        
        for seq in range(total_seg):
            payload, timestamp_iso, size_bytes, rtt_ms, t_out_ms, thr_kbps, ret, t_out_occ = baixar_segmento(sock, servidor, seq)
            dados_completos.extend(payload)
            
            # Montando a linha do CSV com todas as colunas obrigatórias
            linha_metrica = [
                seq, 
                timestamp_iso, 
                size_bytes, 
                round(rtt_ms, 2), 
                rtt_estimated_ms, 
                t_out_ms, 
                round(thr_kbps, 2), 
                ret, 
                int(t_out_occ), 
                window_size, 
                protocol
            ]
            metricas.append(linha_metrica)
            
            if (seq + 1) % (total_seg // 10 if total_seg >= 10 else 1) == 0:
                print(f"    Progresso: {seq + 1}/{total_seg} segmentos...")
                
        # Gravação do CSV de métricas com nome dinâmico
        data_hora_atual = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_csv = f"metrics_{args.group.lower()}_{protocol}_{data_hora_atual}.csv"
        
        with open(nome_csv, "w", newline="") as f:
            writer = csv.writer(f)
            # Cabeçalho exigido pelo documento
            writer.writerow([
                "segment", "timestamp", "size_bytes", "rtt_ms", 
                "rtt_estimated_ms", "timeout_ms", "throughput_kbps", 
                "retransmissions", "timeout_occurred", "window_size", "protocol"
            ])
            writer.writerows(metricas)
            
        print(f"    Métricas salvas em '{nome_csv}'.")
        
        # Geração de Gráfico
        gerar_grafico(metricas)

        # Passo 4 - FIN e DONE
        print("[4] ENCERRAMENTO E VALIDAÇÃO")
        md5_calculado = hashlib.md5(dados_completos).hexdigest()
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
                            nome_arquivo = f"received_{args.file}"
                            with open(nome_arquivo, "wb") as f:
                                f.write(dados_completos)
                            print(f"    [SUCESSO] Arquivo validado e salvo como '{nome_arquivo}'.")
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