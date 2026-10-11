import socket
import time
import hashlib
import argparse
import csv
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
    
    inicio_req = time.time()
    
    while True:
        sock.sendto(pacote_req, servidor)
        
        try:
            dados, _ = sock.recvfrom(65507)

            # encontra o índice do terceiro '|' separando o cabeçalho do payload
            idx1 = dados.find(b"|")
            idx2 = dados.find(b"|", idx1 + 1)
            idx3 = dados.find(b"|", idx2 + 1)
            
            if idx3 != -1:
                # decode no cabeçalho
                cabecalho = dados[:idx3].decode("utf-8", errors="ignore")
                
                if cabecalho.startswith("DATA"):
                    seq_recebida = int(cabecalho.split("|")[1].split("=")[1])
                    
                    if seq_recebida == seq:
                        payload = dados[idx3+1:]
                        
                        # Envia ACK logo após receber e validar o DATA
                        sock.sendto(pacote_ack, servidor)
                        rtt = time.time() - inicio_req
                        throughput = len(payload) / rtt if rtt > 0 else 0
                        rtt = rtt * 1000  # Convertendo para milissegundos
                        
                        return payload, rtt, throughput, retransmissoes, timeout_ocorrido
        
        except socket.timeout:
            timeout_ocorrido = True
            retransmissoes += 1

def gerar_grafico(metricas):
    if not plt:
        return
        
    seqs = [m[0] for m in metricas]
    rtts = [m[1] for m in metricas]
    thrs = [m[2] for m in metricas]

    sumRTT = sum(rtts)
    avgRTT = sumRTT / len(rtts) if len(rtts) > 0 else 0
    print(f"    RTT médio: {avgRTT:.2f} ms")

    fig, ax1 = plt.subplots(figsize=(10, 5))

    color = 'tab:red'
    ax1.set_xlabel('Número do Segmento')
    ax1.set_ylabel('RTT (ms)', color=color)
    ax1.plot(seqs, rtts, color=color, marker='o', markersize=3, linewidth=1)
    ax1.tick_params(axis='y', labelcolor=color)

    ax2 = ax1.twinx()
    color = 'tab:blue'
    ax2.set_ylabel('Throughput (B/s)', color=color)
    ax2.plot(seqs, thrs, color=color, marker='x', markersize=3, linewidth=1, alpha=0.7)
    ax2.tick_params(axis='y', labelcolor=color)

    plt.title('Métricas Stop-and-Wait: RTT e Throughput por Segmento')
    plt.text(0.02, 0.98, f'RTT Médio: {avgRTT:.2f} ms', transform=plt.gca().transAxes, verticalalignment='top', fontsize=10)
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
        
        # Loop REQ -> DATA -> ACK
        for seq in range(total_seg):
            payload, rtt_seg, thr, ret, t_out = baixar_segmento(sock, servidor, seq)
            dados_completos.extend(payload)
            metricas.append([seq, rtt_seg, thr, ret, int(t_out)])
            
            if (seq + 1) % (total_seg // 10 if total_seg >= 10 else 1) == 0:
                print(f"    Progresso: {seq + 1}/{total_seg} segmentos...")
                
        # Gravação do CSV de métricas
        with open("metricas_saw.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["seq", "rtt_s", "throughput_Bps", "retransmissoes", "timeout_ocorrido"])
            writer.writerows(metricas)
        print("    Métricas salvas em 'metricas_saw.csv'.")
        
        # Geração de Gráfico
        gerar_grafico(metricas)

        # Passo 4 - FIN e DONE
        print("[4] ENCERRAMENTO E VALIDAÇÃO")
        md5_calculado = hashlib.md5(dados_completos).hexdigest()
        pacote_fin = f"FIN|checksum={md5_calculado}".encode("utf-8")
        
        recebeu_done = False
        
        # Tenta enviar o FIN e aguardar o DONE em até 5 tentativas
        for tentativa in range(5):
            sock.sendto(pacote_fin, servidor)
            
            try:
                # Laço interno: esvazia o buffer de pacotes DATA atrasados até achar o DONE
                while True:
                    # Usa buffer grande pois pacotes DATA residuais podem ter até 65KB
                    dados_done, _ = sock.recvfrom(65507)
                    
                    # Checa o cabeçalho com segurança, ignorando bytes binários ilegais
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
                        break # Encerra o laço interno (while)
                        
            except socket.timeout:
                print(f"    Timeout aguardando DONE (tentativa {tentativa+1}/5). Reenviando FIN...")
                continue # Volta para o começo do for, enviando o FIN novamente
                
            if recebeu_done:
                break # Encerra o laço externo de tentativas (for)
                
        if not recebeu_done:
            print("    [ERRO] O servidor não respondeu com DONE após várias tentativas.")

    except Exception as e:
        print(f"\nErro de execução: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    main()